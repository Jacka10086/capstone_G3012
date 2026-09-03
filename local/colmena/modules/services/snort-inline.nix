{ config, pkgs, lib, ... }:

let
  libdaqNfq = pkgs.libdaq.overrideAttrs (old: {
    buildInputs = (old.buildInputs or []) ++ [ pkgs.libmnl ];
  });

  snortNfqBase = pkgs.snort.override { libdaq = libdaqNfq; };
  snortNfq = snortNfqBase.overrideAttrs (old: {
    buildInputs = (old.buildInputs or []) ++ [ pkgs.libmnl ];
  });

  daqDir = "${libdaqNfq.lib}/lib/daq";
  snortDefaults = "${snortNfq}/etc/snort/snort_defaults.lua";

  normalConfig = pkgs.writeText "capstone-snort-normal.lua" ''
    HOME_NET = '[10.77.10.0/30,10.77.20.0/30]'
    EXTERNAL_NET = 'any'

    include '${snortDefaults}'

    stream = {}
    stream_ip = {}
    stream_icmp = {}
    stream_udp = {}
    wizard = default_wizard

    ips = {
      mode = 'inline',
      variables = default_variables,
      rules = [[
        pass tcp 10.77.10.0/30 any -> 10.77.20.0/30 1883 (msg:"CAPSTONE MQTT traffic"; sid:1000002; rev:1;)
        pass udp 10.77.10.0/30 any -> 10.77.20.0/30 5202 (msg:"CAPSTONE iPerf load"; sid:1000004; rev:1;)
        block udp 10.77.10.0/30 any -> 10.77.20.0/30 19999 (msg:"CAPSTONE BLOCK zombie UDP 19999"; sid:1000003; rev:2;)
        alert icmp 10.77.10.0/30 any -> 10.77.20.0/30 any (msg:"CAPSTONE ICMP observed"; sid:1000000; rev:1;)
      ]]
    }

    alert_json = {
      file = true,
      fields = 'timestamp proto src_addr src_port dst_addr dst_port msg action sid'
    }

    perf_monitor = {
      base = true,
      seconds = 15,
      packets = 0,
      output = 'file',
      format = 'json',
      modules = {
        { name = 'daq', pegs = 'analyzed block dropped' },
        { name = 'detection', pegs = 'total_alerts' }
      }
    }
  '';

  dropTestConfig = pkgs.writeText "capstone-snort-drop-test.lua" ''
    HOME_NET = '[10.77.10.0/30,10.77.20.0/30]'
    EXTERNAL_NET = 'any'

    include '${snortDefaults}'

    stream = {}
    stream_ip = {}
    stream_icmp = {}
    stream_udp = {}
    wizard = default_wizard

    ips = {
      mode = 'inline',
      variables = default_variables,
      rules = [[
        alert icmp 10.77.10.0/30 any -> 10.77.20.0/30 any (msg:"CAPSTONE inline ICMP observed"; sid:1000000; rev:1;)
        block udp 10.77.10.2 any -> 10.77.20.2 5201 (msg:"CAPSTONE TEST BLOCK UDP 5201"; sid:1000001; rev:5;)
        pass tcp 10.77.10.0/30 any -> 10.77.20.0/30 1883 (msg:"CAPSTONE MQTT traffic"; sid:1000002; rev:1;)
        pass udp 10.77.10.0/30 any -> 10.77.20.0/30 5202 (msg:"CAPSTONE iPerf load"; sid:1000004; rev:1;)
        block udp 10.77.10.0/30 any -> 10.77.20.0/30 19999 (msg:"CAPSTONE BLOCK junk UDP 19999"; sid:1000003; rev:1;)
      ]]
    }

    alert_json = {
      file = true,
      fields = 'timestamp proto src_addr src_port dst_addr dst_port msg action sid'
    }

    perf_monitor = {
      base = true,
      seconds = 15,
      packets = 0,
      output = 'file',
      format = 'json',
      modules = {
        { name = 'daq', pegs = 'analyzed block dropped' },
        { name = 'detection', pegs = 'total_alerts' }
      }
    }
  '';

  configForMode = mode:
    if mode == "drop-test" then dropTestConfig else normalConfig;

  snortRunner = pkgs.writeShellScript "capstone-snort-inline" ''
    set -euo pipefail

    mode=normal
    if [ -r /var/lib/capstone-snort/mode ]; then
      mode=$(tr -d '[:space:]' < /var/lib/capstone-snort/mode)
    fi

    case "$mode" in
      normal) config=${lib.escapeShellArg (toString (configForMode "normal"))} ;;
      drop-test) config=${lib.escapeShellArg (toString (configForMode "drop-test"))} ;;
      *) echo "Invalid Capstone Snort mode: $mode" >&2; exit 1 ;;
    esac

    exec ${snortNfq}/bin/snort \
      -Q \
      --daq nfq \
      --daq-dir ${daqDir} \
      -i 0 \
      -k none \
      -c "$config" \
      -l /var/lib/capstone-snort/log
  '';

  metricsExporter = pkgs.writeScriptBin "capstone-snort-metrics" ''

    ${builtins.readFile ../../packages/capstone-snort-metrics.py}
  '';

  modeTool = pkgs.writeShellScriptBin "capstone-snort-mode" ''
    set -euo pipefail

    action="''${1:-status}"
    case "$action" in
      normal) config=${lib.escapeShellArg (toString (configForMode "normal"))} ;;
      drop-test) config=${lib.escapeShellArg (toString (configForMode "drop-test"))} ;;
      status)
        mode=normal
        [ -r /var/lib/capstone-snort/mode ] && mode=$(tr -d '[:space:]' < /var/lib/capstone-snort/mode)
        printf '%s\n' "$mode"
        exit 0
        ;;
      *) echo "usage: capstone-snort-mode [normal|drop-test|status]" >&2; exit 2 ;;
    esac

    mkdir -p /var/lib/capstone-snort/log
    ${snortNfq}/bin/snort -T --daq-dir ${daqDir} -c "$config" -l /var/lib/capstone-snort/log
    tmp=$(mktemp /var/lib/capstone-snort/.mode.XXXXXX)
    printf '%s\n' "$action" > "$tmp"
    chmod 0644 "$tmp"
    mv "$tmp" /var/lib/capstone-snort/mode
    systemctl restart snort-inline.service
  '';
in
{
  boot.kernelModules = [ "nfnetlink_queue" ];

  environment.systemPackages = [
    snortNfq
    libdaqNfq
    modeTool
    metricsExporter
    pkgs.nftables
  ];

  systemd.tmpfiles.rules = [
    "d /var/lib/capstone-snort 0755 root root -"
    "d /var/lib/capstone-snort/log 0755 root root -"
    "f /var/lib/capstone-snort/mode 0644 root root - normal"
  ];

  networking.nftables.enable = true;
  networking.nftables.tables.capstone_inline = {
    family = "inet";
    content = ''
      chain forward {
        type filter hook forward priority mangle; policy accept;

        iifname "ens19" oifname "ens20" ip saddr 10.77.10.0/30 ip daddr 10.77.20.0/30 counter queue num 0 bypass
        iifname "ens20" oifname "ens19" ip saddr 10.77.20.0/30 ip daddr 10.77.10.0/30 counter queue num 0 bypass
      }
    '';
  };

  networking.firewall.filterForward = true;
  networking.firewall.extraForwardRules = ''
    iifname "ens19" oifname "ens20" ip saddr 10.77.10.0/30 ip daddr 10.77.20.0/30 accept
    iifname "ens20" oifname "ens19" ip saddr 10.77.20.0/30 ip daddr 10.77.10.0/30 accept
  '';

  systemd.services.snort-inline = {
    description = "Capstone Snort 3 NFQUEUE Inline VNF";
    after = [ "network-online.target" "nftables.service" ];
    wants = [ "network-online.target" ];
    requires = [ "nftables.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "simple";
      User = "root";
      ExecStartPre = "${snortNfq}/bin/snort -T --daq-dir ${daqDir} -c ${normalConfig} -l /var/lib/capstone-snort/log";
      ExecStart = snortRunner;
      Restart = "on-failure";
      RestartSec = "2s";
      TimeoutStopSec = "20s";
      LimitNOFILE = 65536;
    };
  };

  systemd.services.snort-nfq-readiness = {
    description = "Verify the Capstone Snort build includes NFQUEUE DAQ";
    before = [ "snort-inline.service" ];
    requiredBy = [ "snort-inline.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = pkgs.writeShellScript "verify-snort-nfq" ''
        set -euo pipefail
        ${snortNfq}/bin/snort --daq-dir ${daqDir} --daq-list | ${pkgs.gnugrep}/bin/grep -q 'nfq'
      '';
    };
  };

  systemd.services.capstone-snort-metrics = {
    description = "Collect Capstone Snort NFQUEUE metrics";
    after = [ "snort-inline.service" ];
    serviceConfig = {
      Type = "oneshot";
      User = "root";
      ExecStart = lib.concatStringsSep " " [
        "${metricsExporter}/bin/capstone-snort-metrics"
        "--perf-glob '/var/lib/capstone-snort/log/perf_monitor*.json'"
        "--alert-glob '/var/lib/capstone-snort/log/alert_json*.txt'"
        "--state /var/lib/capstone-snort/metrics-state.json"
        "--output /var/lib/node_exporter/textfile_collector/capstone_snort.prom"
        "--mode-file /var/lib/capstone-snort/mode"
        "--snort ${snortNfq}/bin/snort"
        "--daq-dir ${daqDir}"
        "--systemctl ${pkgs.systemd}/bin/systemctl"
        "--nft ${pkgs.nftables}/bin/nft"
        "--freshness-seconds 60"
      ];
    };
  };

  systemd.timers.capstone-snort-metrics = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "15s";
      OnUnitActiveSec = "15s";
      AccuracySec = "2s";
      Unit = "capstone-snort-metrics.service";
    };
  };
}
