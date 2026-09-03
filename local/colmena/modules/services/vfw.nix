{ config, pkgs, lib, ... }:

let
  vfwMetrics = pkgs.writeScriptBin "capstone-vfw-metrics" ''

    from __future__ import annotations

    import argparse
    import json
    import math
    import os
    import subprocess
    import sys
    import tempfile
    from pathlib import Path


    def atomic_write(path: Path, content: str, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                os.fchmod(handle.fileno(), mode)
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise


    def run_nft(nft: str, args: list[str]) -> dict | None:
        try:
            completed = subprocess.run(
                [nft] + args,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None


    def find_counters(obj, found=None):
        if found is None:
            found = []
        if isinstance(obj, dict):

            if "counter" in obj and isinstance(obj["counter"], dict):
                found.append(obj["counter"])
            elif obj.get("type") == "counter":
                found.append(obj)
            for value in obj.values():
                find_counters(value, found)
        elif isinstance(obj, list):
            for item in obj:
                find_counters(item, found)
        return found


    def service_active(systemctl: str, service_name: str) -> bool:
        try:
            completed = subprocess.run(
                [systemctl, "is-active", "--quiet", service_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--service-name", default="capstone-vfw.service")
        parser.add_argument("--systemctl", default="systemctl")
        parser.add_argument("--nft", default="nft")
        parser.add_argument("--metric-prefix", default="capstone_vfw")
        parser.add_argument("--metric-labels", default="vnf=vfw", help="Comma-separated key=value labels")
        args = parser.parse_args()

        up = float(service_active(args.systemctl, args.service_name))
        data = run_nft(args.nft, ["-j", "list", "table", "inet", "capstone_vfw"])

        counters = find_counters(data) if data else []
        counter_values = {}
        for counter in counters:
            name = counter.get("name", "unknown")
            handle = counter.get("handle")
            if name == "unknown" and handle is not None:
                name = f"handle_{handle}"
            packets = counter.get("packets", 0)
            bytes_ = counter.get("bytes", 0)
            counter_values[name] = {"packets": packets, "bytes": bytes_}

        labels_str = ""
        if args.metric_labels:
            pairs = [pair.strip() for pair in args.metric_labels.split(",") if "=" in pair]
            labels_str = "{" + ",".join(f'{k.strip()}="{v.strip()}"' for k, v in (p.split("=", 1) for p in pairs)) + "}"

        lines = []
        lines.append(f"# HELP {args.metric_prefix}_up Whether the vFW service is active.")
        lines.append(f"# TYPE {args.metric_prefix}_up gauge")
        lines.append(f"{args.metric_prefix}_up{labels_str} {format(up, '.17g')}")

        lines.append(f"# HELP {args.metric_prefix}_forwarded_packets_total Packets forwarded by the vFW.")
        lines.append(f"# TYPE {args.metric_prefix}_forwarded_packets_total counter")
        forwarded = counter_values.get("fwd_count", {}).get("packets", 0)
        lines.append(f"{args.metric_prefix}_forwarded_packets_total{labels_str} {format(float(forwarded), '.17g')}")

        lines.append(f"# HELP {args.metric_prefix}_dropped_packets_total Packets dropped by the vFW.")
        lines.append(f"# TYPE {args.metric_prefix}_dropped_packets_total counter")
        dropped = counter_values.get("drop_count", {}).get("packets", 0)
        lines.append(f"{args.metric_prefix}_dropped_packets_total{labels_str} {format(float(dropped), '.17g')}")

        lines.append(f"# HELP {args.metric_prefix}_forwarded_bytes_total Bytes forwarded by the vFW.")
        lines.append(f"# TYPE {args.metric_prefix}_forwarded_bytes_total counter")
        forwarded_bytes = counter_values.get("fwd_count", {}).get("bytes", 0)
        lines.append(f"{args.metric_prefix}_forwarded_bytes_total{labels_str} {format(float(forwarded_bytes), '.17g')}")

        lines.append(f"# HELP {args.metric_prefix}_dropped_bytes_total Bytes dropped by the vFW.")
        lines.append(f"# TYPE {args.metric_prefix}_dropped_bytes_total counter")
        dropped_bytes = counter_values.get("drop_count", {}).get("bytes", 0)
        lines.append(f"{args.metric_prefix}_dropped_bytes_total{labels_str} {format(float(dropped_bytes), '.17g')}")

        atomic_write(args.output, "\n".join(lines) + "\n", 0o644)
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())
  '';

  vfwRuleScript = pkgs.writeShellScript "capstone-vfw-rules" ''
    set -euo pipefail

    action="''${1:-load}"
    nft="${pkgs.nftables}/bin/nft"

    if [ "$action" = "unload" ]; then
      $nft delete table inet capstone_vfw 2>/dev/null || true
      exit 0
    fi


    $nft delete table inet capstone_inline 2>/dev/null || true
    $nft delete table inet capstone_vfw 2>/dev/null || true

    rules_file=$(mktemp)
    trap 'rm -f "$rules_file"' EXIT
    cat > "$rules_file" <<'NFTABLES'
table inet capstone_vfw {
  counter fwd_count {}
  counter drop_count {}

  chain forward {
    type filter hook forward priority 0; policy drop;


    iifname "ens19" oifname "ens20" ip saddr 10.77.10.0/30 ip daddr 10.77.20.0/30 tcp dport 1883 counter name fwd_count accept
    iifname "ens19" oifname "ens20" ip saddr 10.77.10.0/30 ip daddr 10.77.20.0/30 tcp dport 5202 counter name fwd_count accept
    iifname "ens19" oifname "ens20" ip saddr 10.77.10.0/30 ip daddr 10.77.20.0/30 udp dport 5202 counter name fwd_count accept
    iifname "ens19" oifname "ens20" ip saddr 10.77.10.0/30 ip daddr 10.77.20.0/30 udp dport 19999 counter name drop_count drop


    iifname "ens20" oifname "ens19" ip saddr 10.77.20.0/30 ip daddr 10.77.10.0/30 tcp sport 1883 counter name fwd_count accept
    iifname "ens20" oifname "ens19" ip saddr 10.77.20.0/30 ip daddr 10.77.10.0/30 tcp sport 5202 counter name fwd_count accept
    iifname "ens20" oifname "ens19" ip saddr 10.77.20.0/30 ip daddr 10.77.10.0/30 udp sport 5202 counter name fwd_count accept


    ct state established,related counter accept


    limit rate 5/second burst 5 packets log prefix "capstone-vfw-drop: "
    counter name drop_count drop
  }
}
NFTABLES
    $nft -f "$rules_file"
  '';
in
{
  environment.systemPackages = [
    vfwMetrics
    pkgs.nftables
  ];

  systemd.tmpfiles.rules = [
    "d /var/lib/node_exporter/textfile_collector 0755 root root -"
  ];

  networking.nftables.enable = true;

  systemd.services.capstone-vfw = {
    description = "Capstone Virtual Firewall (nftables)";
    after = [ "network-online.target" "nftables.service" ];
    wants = [ "network-online.target" ];
    requires = [ "nftables.service" ];
    wantedBy = [ ];
    serviceConfig = {
      Type = "oneshot";
      User = "root";
      RemainAfterExit = true;
      ExecStart = "${vfwRuleScript} load";
      ExecStop = "${vfwRuleScript} unload";
    };
  };

  systemd.services.capstone-vfw-metrics = {
    description = "Collect Capstone vFW metrics";
    after = [ "capstone-vfw.service" ];
    serviceConfig = {
      Type = "oneshot";
      User = "root";
      ExecStart = lib.concatStringsSep " " [
        "${vfwMetrics}/bin/capstone-vfw-metrics"
        "--output /var/lib/node_exporter/textfile_collector/capstone_vfw.prom"
        "--service-name capstone-vfw.service"
        "--metric-prefix capstone_vfw"
        "--metric-labels vnf=vfw,mode=vfw"
        "--systemctl ${pkgs.systemd}/bin/systemctl"
        "--nft ${pkgs.nftables}/bin/nft"
      ];
    };
  };

  systemd.timers.capstone-vfw-metrics = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "15s";
      OnUnitActiveSec = "15s";
      AccuracySec = "2s";
      Unit = "capstone-vfw-metrics.service";
    };
  };
}
