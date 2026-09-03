{ config, pkgs, lib, ... }:
{
  imports = [
    ../../modules/ct.nix
  ];

  networking.hostName = "devshell";

  time.timeZone = "UTC";

  environment.systemPackages = with pkgs; [
    colmena
    curl
    openssh
    python3
  ];

  services.prometheus.exporters.node = {
    enable = true;
    port = 9100;
    openFirewall = true;
    enabledCollectors = [ "textfile" ];
    extraFlags = [ "--collector.textfile.directory=/var/lib/node_exporter/textfile_collector" ];
  };

  systemd.services.capstone-control-exporter = let
    renderScript = pkgs.writeText "capstone-control-render.py" ''

      import json
      import os
      import subprocess
      import time

      STATE_FILE = "/home/jacka1/.capstone-control/state.json"
      OUT_FILE = "/var/lib/node_exporter/textfile_collector/capstone_control.prom"



      MACHINES = [
          ("iot", "192.168.88.175", [
              ("mqtt-traffic", "capstone-mqtt-traffic"),
              ("zombie-traffic", "capstone-zombie-traffic"),
              ("mqtt-probe", "capstone-mqtt-probe"),
              ("iperf3-client", "pgrep -x iperf3 >/dev/null && echo active || echo inactive"),
              ("node_exporter", "prometheus-node-exporter"),
          ]),
          ("vnf", "192.168.88.174", [
              ("snort-inline", "snort-inline"),
              ("snort-passive", "snort-passive"),
              ("capstone-vfw", "capstone-vfw"),
              ("node_exporter", "prometheus-node-exporter"),
          ]),
          ("broker", "192.168.88.171", [
              ("mosquitto", "mosquitto"),
              ("iperf3-sink", "iperf3-sink"),
              ("iperf3-load-sink", "iperf3-load-sink"),
              ("node_exporter", "prometheus-node-exporter"),
          ]),
          ("brain", "192.168.88.173", [
              ("prometheus", "prometheus"),
              ("grafana", "grafana"),
              ("node_exporter", "prometheus-node-exporter"),
          ]),
      ]
      DOCKER_CHECKS = [("elasticsearch", "elasticsearch"), ("kibana", "kibana")]

      def ssh_check(host, cmd):


          proc = subprocess.run(
              ["/run/wrappers/bin/sudo", "-u", "jacka1",
               "/run/current-system/sw/bin/ssh", "-o", "BatchMode=yes",
               "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no",
               "-o", "UserKnownHostsFile=/dev/null",
               "jacka1@" + host, cmd],
              capture_output=True, text=True, timeout=15,
          )
          return proc.stdout if proc.returncode == 0 else ""

      def real_service_lines():
          out = []
          for machine, host, units in MACHINES:




              cmd = "; ".join(
                  "systemctl is-active %s 2>/dev/null" % u
                  for _, u in units
              ) + "; true"
              states = ssh_check(host, cmd).strip().split("\n")
              for i, (display, _u) in enumerate(units):
                  state = states[i].strip() if i < len(states) else "inactive"
                  on = 1 if state == "active" else 0
                  out.append('capstone_service_up{machine="%s",service="%s"} %d'
                             % (machine, display, on))
          for display, cname in DOCKER_CHECKS:
              names = set(ssh_check("192.168.88.173",
                                    "docker ps --format '{{.Names}}'").split())
              on = 1 if cname in names else 0
              out.append('capstone_service_up{machine="brain",service="%s"} %d'
                         % (display, on))
          return out

      DEFAULTS = {
          "vnf_profile": "inline",
          "zombie_mode": "off",
          "traffic": {"mqtt": True, "zombie": True, "iperf": False, "probe": True},
          "link_capacity": "unlimited",
          "broker": {"mosquitto": True, "iperf_sink": True, "iperf_load_sink": True},
          "node_exporter": {"iot": True, "vnf": True, "broker": True, "brain": True},
          "brain": {"prometheus": True, "grafana": True, "elasticsearch_kibana": True},
          "updated_at": 0,
          "changes": {},
      }

      def main():
          os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
          if not os.path.exists(STATE_FILE):
              return
          try:
              with open(STATE_FILE, "r", encoding="utf-8") as f:
                  s = json.load(f)
          except Exception:
              return
          merged = dict(DEFAULTS)
          merged.update(s)
          merged["traffic"] = dict(DEFAULTS["traffic"], **(s.get("traffic") or {}))
          merged["broker"] = dict(DEFAULTS["broker"], **(s.get("broker") or {}))
          merged["node_exporter"] = dict(DEFAULTS["node_exporter"], **(s.get("node_exporter") or {}))
          merged["brain"] = dict(DEFAULTS["brain"], **(s.get("brain") or {}))
          merged["changes"] = s.get("changes") or {}

          lines = []

          def state(switch, value):
              lines.append('capstone_control_state{switch="%s",value="%s"} 1' % (switch, value))

          state("vnf_profile", merged["vnf_profile"])
          state("zombie_mode", merged["zombie_mode"])
          for k in ("mqtt", "zombie", "iperf", "probe"):
              state("traffic_" + k, "on" if merged["traffic"].get(k) else "off")
          state("link_capacity", merged["link_capacity"])
          for k in ("mosquitto", "iperf_sink", "iperf_load_sink"):
              state("broker_" + k, "on" if merged["broker"].get(k) else "off")
          for k in ("iot", "vnf", "broker", "brain"):
              state("node_exporter_" + k, "on" if merged["node_exporter"].get(k) else "off")
          for k in ("prometheus", "grafana", "elasticsearch_kibana"):
              state("brain_" + k, "on" if merged["brain"].get(k) else "off")

          body = "# HELP capstone_control_state Current experiment control switch positions.\n"
          body += "# TYPE capstone_control_state gauge\n" + "\n".join(lines) + "\n"

          chg_lines = []
          for sw, c in merged["changes"].items():
              n = int(c.get("count") or 0)
              if n > 0:


                  chg_lines.append('capstone_control_changes_total{switch="%s"} %d' % (sw, n))
          body += "# HELP capstone_control_changes_total Number of control switch changes.\n"
          body += "# TYPE capstone_control_changes_total counter\n" + "\n".join(chg_lines) + "\n"

          body += "# HELP capstone_control_updated_at Unix timestamp of the last control change.\n"
          body += "# TYPE capstone_control_updated_at gauge\n"
          body += "capstone_control_updated_at %d\n" % int(merged.get("updated_at") or 0)


          oracle = {}
          try:
              with open("/home/jacka1/.capstone-oracle/state.json", "r", encoding="utf-8") as f:
                  oracle = json.load(f)
          except Exception:
              pass
          running = bool(oracle.get("running"))
          prof = oracle.get("profile") or ""
          body += "# HELP capstone_oracle_running Whether an oracle data-collection sweep is running.\n"
          body += "# TYPE capstone_oracle_running gauge\n"
          body += "capstone_oracle_running %d\n" % (1 if running else 0)
          body += "# HELP capstone_oracle_profile Current oracle profile being collected.\n"
          body += "# TYPE capstone_oracle_profile gauge\n"
          for p in ("inline", "passive", "vfw"):
              body += "capstone_oracle_profile{profile=\"%s\"} %d\n" % (p, 1 if (running and prof == p) else 0)
          body += "# HELP capstone_oracle_rows Data rows in the collected csv of each profile.\n"
          body += "# TYPE capstone_oracle_rows gauge\n"
          for p in ("inline", "passive", "vfw"):
              csvf = "${../../../../datasets}/%s.csv" % p
              n = 0
              try:
                  with open(csvf, "r", encoding="utf-8") as f:
                      n = max(0, len([l for l in f.read().split("\n") if l.strip()]) - 1)
              except Exception:
                  pass
              body += "capstone_oracle_rows{profile=\"%s\"} %d\n" % (p, n)


          body += "# HELP capstone_service_up Real service running state (1=active, 0=inactive/unknown).\n"
          body += "# TYPE capstone_service_up gauge\n"
          for line in real_service_lines():
              body += line + "\n"

          tmp = OUT_FILE + ".tmp"
          with open(tmp, "w", encoding="utf-8") as f:
              f.write(body)
          os.replace(tmp, OUT_FILE)

      if __name__ == "__main__":
          while True:
              try:
                  main()
              except Exception:
                  pass
              time.sleep(5)
    '';
  in {
    description = "Export capstone control switch state as a Prometheus textfile";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];

    serviceConfig = {
      Type = "simple";
      User = "root";
      ExecStart = "${pkgs.python3}/bin/python3 ${renderScript}";
      Restart = "always";
      RestartSec = "5s";
    };
  };

  services.openssh = {
  enable = true;
  ports = [ 22 ];
  openFirewall = true;
  settings = lib.mkForce {
    PermitRootLogin = "no";
    PasswordAuthentication = false;
    PermitEmptyPasswords = false;
    AllowUsers = [ "jacka1" ];
  };
};
}
