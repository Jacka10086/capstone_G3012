





















set -u
eval "$(ssh-agent -s)" >/dev/null 2>&1
ssh-add ~/.ssh/id_ed25519 >/dev/null 2>&1 || true

SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10"
PROXMOX_HOST="root@192.168.88.21"
IOT_HOST="jacka1@192.168.88.175"
BRAIN_HOST="jacka1@192.168.88.173"
VNF_HOST="jacka1@192.168.88.174"
VMID=101
BROKER_IP="10.77.20.2"
IPERF_PORT=5202

REPS="${REPS:-12}"
HOLDOUT="${HOLDOUT:-72}"
SHUFFLE_SEED="${SHUFFLE_SEED:-42}"
SETTLE_S="${SETTLE_S:-60}"

VCPUS=(1 2 3 4)
MEMS=(256 384 512 640 768 896 1024)
LCS=(25 30 35 40 45 50 55 60 65 70 75 80 85 90 95 100 unlimited)


case "$PROFILE" in
  passive)
    VNF_SERVICE="snort-passive"
    METRICS_SERVICE="capstone-snort-passive-metrics"
    STOP_OTHERS="snort-inline capstone-snort-metrics capstone-vfw capstone-vfw-metrics"
    HEADER='vnf_profile,vCPU_cores,VNF_memory_MB,Link_Capacity_limit_Mbps,offered_load_pps,offered_load_mbps,VNF_cpu_utilization_pct,VNF_memory_utilization_pct,passive_processed_packets_per_sec,passive_alerts_per_sec,passive_daq_drops_per_sec,MQTT_package_latency_p99_ms,MQTT_package_loss_pct,MQTT_devices_connected'
    ;;
  inline)
    VNF_SERVICE="snort-inline"
    METRICS_SERVICE="capstone-snort-metrics"
    STOP_OTHERS="snort-passive capstone-snort-passive-metrics capstone-vfw capstone-vfw-metrics"
    HEADER='vnf_profile,vCPU_cores,VNF_memory_MB,Link_Capacity_limit_Mbps,offered_load_pps,offered_load_mbps,VNF_cpu_utilization_pct,VNF_memory_utilization_pct,MQTT_package_latency_p99_ms,MQTT_package_latency_average_ms,MQTT_package_loss_pct,MQTT_devices_connected,inline_analyzed_packets_per_sec,inline_blocked_packets_per_sec'
    ;;
  vfw)
    VNF_SERVICE="capstone-vfw"
    METRICS_SERVICE="capstone-vfw-metrics"
    STOP_OTHERS="snort-inline snort-passive capstone-snort-metrics capstone-snort-passive-metrics"
    HEADER='vnf_profile,vCPU_cores,VNF_memory_MB,Link_Capacity_limit_Mbps,offered_load_pps,offered_load_mbps,VNF_cpu_utilization_pct,VNF_memory_utilization_pct,vfw_forwarded_packets_per_sec,vfw_dropped_packets_per_sec,MQTT_package_latency_p99_ms,MQTT_package_loss_pct,MQTT_devices_connected'
    ;;
  *) echo "PROFILE must be passive|inline|vfw" >&2; exit 1 ;;
esac


prom() {
  local val
  val=$(ssh $SSH_OPTS "$BRAIN_HOST" "curl -s --max-time 5 --noproxy '*' --data-urlencode 'query=$1' 'http://127.0.0.1:9090/api/v1/query'" 2>/dev/null | python3 -c "import sys,json;r=json.load(sys.stdin)['data']['result'];print(f'{float(r[0][\"value\"][1]):.4f}' if r else 'N/A')" 2>/dev/null) || true
  echo "${val:-ERR}"
}

set_tc() {
  local rate="$1"
  if [ "$rate" = "unlimited" ]; then
    ssh $SSH_OPTS "$PROXMOX_HOST" "tc qdisc del dev tap101i1 root 2>/dev/null; tc qdisc del dev tap101i2 root 2>/dev/null" >/dev/null 2>&1 || true
  else
    ssh $SSH_OPTS "$PROXMOX_HOST" "tc qdisc del dev tap101i1 root 2>/dev/null; tc qdisc add dev tap101i1 root tbf rate ${rate}mbit burst 64kbit latency 50ms" >/dev/null 2>&1
  fi
}




apply_config() {
  local cores="$1" mem="$2" lc="$3"
  ssh $SSH_OPTS "$VNF_HOST" "sudo systemctl set-property --runtime $VNF_SERVICE AllowedCPUs=0-$((cores-1))" >/dev/null 2>&1
  ssh $SSH_OPTS "$PROXMOX_HOST" "printf 'balloon %s\n' '$mem' | qm monitor $VMID" >/dev/null 2>&1
  set_tc "$lc"

  ssh $SSH_OPTS "$VNF_HOST" "sudo systemctl stop $STOP_OTHERS 2>/dev/null; sudo systemctl restart $VNF_SERVICE $METRICS_SERVICE" >/dev/null 2>&1
  sleep 8
}

start_attack() {
  ssh $SSH_OPTS "$IOT_HOST" "sudo capstone-zombie-mode panic" >/dev/null 2>&1
  ssh $SSH_OPTS "$IOT_HOST" "sudo systemctl start capstone-iperf3-client" >/dev/null 2>&1
  sleep 5
}

stop_attack() {
  ssh $SSH_OPTS "$IOT_HOST" "sudo systemctl stop capstone-iperf3-client" >/dev/null 2>&1
  ssh $SSH_OPTS "$IOT_HOST" "sudo capstone-zombie-mode off" >/dev/null 2>&1
}



cpu_query() {
  local cores="$1" re
  re=$(seq 0 $((cores-1)) | paste -sd'|')
  prom "100 - avg(rate(node_cpu_seconds_total{job=\"vnf-snort\",mode=\"idle\",cpu=~\"$re\"}[1m])) * 100"
}

append_csv() {
  local cores="$1" mem="$2" lc="$3"
  local offered_pps offered_mbps cpu mem_pct latency loss connected
  offered_pps=$(prom 'rate(node_network_receive_packets_total{job="vnf-snort",device="ens19"}[1m])')
  offered_mbps=$(prom 'rate(node_network_receive_bytes_total{job="vnf-snort",device="ens19"}[1m]) * 8 / 1000000')
  cpu=$(cpu_query "$cores")
  mem_pct=$(prom '100 * (1 - node_memory_MemAvailable_bytes{job="vnf-snort"} / node_memory_MemTotal_bytes{job="vnf-snort"})')
  latency=$(prom 'capstone_mqtt_probe_latency_seconds_p99{job="iot-devices"}')
  loss=$(prom 'capstone_mqtt_probe_loss_ratio{job="iot-devices"}')
  connected=$(prom 'capstone_mqtt_connected_devices{job="iot-devices"}')

  [ ! -f "$CSV" ] && printf '%s\n' "$HEADER" > "$CSV"
  case "$PROFILE" in
    passive)
      local p_proc p_alrt p_drop
      p_proc=$(prom 'rate(capstone_snort_passive_processed_packets_total{job="vnf-snort"}[1m])')
      p_alrt=$(prom 'rate(capstone_snort_passive_alerts_total{job="vnf-snort"}[1m])')
      p_drop=$(prom 'rate(capstone_snort_passive_daq_dropped_packets_total{job="vnf-snort"}[1m])')
      printf 'passive,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$cores" "$mem" "$lc" "$offered_pps" "$offered_mbps" "$cpu" "$mem_pct" \
        "$p_proc" "$p_alrt" "$p_drop" "$latency" "$loss" "$connected" >> "$CSV"
      ;;
    inline)
      local lat_avg analyzed blocked
      lat_avg=$(prom 'capstone_mqtt_probe_latency_seconds_average{job="iot-devices"}')
      analyzed=$(prom 'rate(capstone_snort_processed_packets_total{job="vnf-snort"}[1m])')
      blocked=$(prom 'rate(node_network_receive_packets_total{job="vnf-snort",device="ens19"}[1m]) - ignoring(device) rate(node_network_transmit_packets_total{job="vnf-snort",device="ens20"}[1m])')
      printf 'inline,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$cores" "$mem" "$lc" "$offered_pps" "$offered_mbps" "$cpu" "$mem_pct" \
        "$latency" "$lat_avg" "$loss" "$connected" "$analyzed" "$blocked" >> "$CSV"
      ;;
    vfw)
      local fwd drop
      fwd=$(prom 'rate(capstone_vfw_forwarded_packets_total{job="vnf-snort"}[1m])')
      drop=$(prom 'rate(capstone_vfw_dropped_packets_total{job="vnf-snort"}[1m])')
      printf 'vfw,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$cores" "$mem" "$lc" "$offered_pps" "$offered_mbps" "$cpu" "$mem_pct" \
        "$fwd" "$drop" "$latency" "$loss" "$connected" >> "$CSV"
      ;;
  esac
}

reps_done() {
  grep -c "^${PROFILE},$1,$2,$3," "$CSV" 2>/dev/null || echo 0
}



mapfile -t GRID < <(
  for c in "${VCPUS[@]}"; do for m in "${MEMS[@]}"; do for l in "${LCS[@]}"; do
    echo "$c $m $l"
  done; done; done | shuf --random-source=<(yes "$SHUFFLE_SEED")
)
echo "grid: ${#GRID[@]} configs x $REPS reps + $HOLDOUT holdout rows"


ssh $SSH_OPTS "$PROXMOX_HOST" "qm set $VMID --cores 4 --memory 1024 --balloon 1024" >/dev/null 2>&1
ssh $SSH_OPTS "$PROXMOX_HOST" "qm status $VMID" | grep -q running || ssh $SSH_OPTS "$PROXMOX_HOST" "qm start $VMID" >/dev/null 2>&1
sleep 20

total_rows=0
for cfg in "${GRID[@]}"; do
  read -r cores mem lc <<< "$cfg"
  lc_value="$lc"; [ "$lc" = "unlimited" ] && lc_value="99999"
  done_n=$(reps_done "$cores" "$mem" "$lc_value")
  [ "$done_n" -ge "$REPS" ] && continue

  echo "═══ cores=$cores mem=$mem lc=$lc (resume at rep $((done_n+1))) ═══"
  apply_config "$cores" "$mem" "$lc"
  start_attack
  for ((rep=done_n+1; rep<=REPS; rep++)); do
    sleep "$SETTLE_S"
    append_csv "$cores" "$mem" "$lc_value"
    total_rows=$((total_rows+1))
    echo "  rep $rep/$REPS -> $(tail -1 "$CSV" | cut -d, -f5-8)"
  done
  stop_attack
done


if [ "$HOLDOUT" -gt 0 ]; then
  echo "═══ holdout: $HOLDOUT extra rows ═══"
  mapfile -t HO < <(printf '%s\n' "${GRID[@]}" | shuf -n "$HOLDOUT" --random-source=<(yes "$((SHUFFLE_SEED+1))"))
  for cfg in "${HO[@]}"; do
    read -r cores mem lc <<< "$cfg"
    lc_value="$lc"; [ "$lc" = "unlimited" ] && lc_value="99999"
    apply_config "$cores" "$mem" "$lc"
    start_attack
    sleep "$SETTLE_S"
    append_csv "$cores" "$mem" "$lc_value"
    stop_attack
  done
fi


ssh $SSH_OPTS "$VNF_HOST" "sudo systemctl revert $VNF_SERVICE 2>/dev/null || true" >/dev/null 2>&1
ssh $SSH_OPTS "$PROXMOX_HOST" "printf 'balloon 1024\n' | qm monitor $VMID" >/dev/null 2>&1
set_tc unlimited

echo " Done — $total_rows new rows -> $CSV"
echo "   next: python3 add_data_split.py  (adds train/validation/test column)"
