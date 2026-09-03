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

  passiveConfig = pkgs.writeText "capstone-snort-passive.lua" ''
    HOME_NET = '[10.77.10.0/30,10.77.20.0/30]'
    EXTERNAL_NET = 'any'

    include '${snortDefaults}'

    stream = {}
    stream_ip = {}
    stream_icmp = {}
    stream_udp = {}
    wizard = default_wizard

    ips = {
      mode = 'tap',
      variables = default_variables,
      rules = [[
        alert tcp 10.77.10.0/30 any -> 10.77.20.0/30 1883 (msg:"CAPSTONE PASSIVE MQTT traffic"; sid:1000102; rev:1;)
        alert udp 10.77.10.0/30 any -> 10.77.20.0/30 5202 (msg:"CAPSTONE PASSIVE iPerf load"; sid:1000104; rev:1;)
        alert udp 10.77.10.0/30 any -> 10.77.20.0/30 19999 (msg:"CAPSTONE PASSIVE zombie UDP 19999"; sid:1000103; rev:1;)
        alert icmp 10.77.10.0/30 any -> 10.77.20.0/30 any (msg:"CAPSTONE PASSIVE ICMP observed"; sid:1000100; rev:1;)
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
        { name = 'daq', pegs = 'analyzed dropped' },
        { name = 'detection', pegs = 'total_alerts' }
      }
    }
  '';

  passiveSnortRunner = pkgs.writeShellScript "capstone-snort-passive" ''
    set -euo pipefail

    exec ${snortNfq}/bin/snort \
      --daq pcap \
      --daq-dir ${daqDir} \
      -i ens19 \
      -k none \
      -c ${passiveConfig} \
      -l /var/lib/capstone-snort-passive/log
  '';

  metricsExporter = pkgs.writeScriptBin "capstone-snort-metrics" ''

    ${builtins.readFile ../../packages/capstone-snort-metrics.py}
  '';
in
{
  environment.systemPackages = [
    snortNfq
    libdaqNfq
    metricsExporter
    pkgs.iproute2
  ];

  systemd.tmpfiles.rules = [
    "d /var/lib/capstone-snort-passive 0755 root root -"
    "d /var/lib/capstone-snort-passive/log 0755 root root -"
    "d /var/lib/node_exporter/textfile_collector 0755 root root -"
  ];

  systemd.services.snort-passive = {
    description = "Capstone Snort 3 Passive Profiler";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "simple";
      User = "root";
      ExecStartPre = [
        "${pkgs.iproute2}/bin/ip link set ens19 promisc on"
        "${snortNfq}/bin/snort -T --daq-dir ${daqDir} -c ${passiveConfig} -l /var/lib/capstone-snort-passive/log"
      ];
      ExecStart = passiveSnortRunner;
      Restart = "on-failure";
      RestartSec = "2s";
      TimeoutStopSec = "20s";
      LimitNOFILE = 65536;
    };
  };

  systemd.services.capstone-snort-passive-metrics = {
    description = "Collect Capstone Snort Passive metrics";
    after = [ "snort-passive.service" ];
    serviceConfig = {
      Type = "oneshot";
      User = "root";
      ExecStart = lib.concatStringsSep " " [
        "${metricsExporter}/bin/capstone-snort-metrics"
        "--perf-glob '/var/lib/capstone-snort-passive/log/perf_monitor*.json'"
        "--alert-glob '/var/lib/capstone-snort-passive/log/alert_json*.txt'"
        "--state /var/lib/capstone-snort-passive/metrics-state.json"
        "--output /var/lib/node_exporter/textfile_collector/capstone_snort_passive.prom"
        "--snort ${snortNfq}/bin/snort"
        "--daq-dir ${daqDir}"
        "--daq-kind pcap"
        "--service-name snort-passive.service"
        "--metric-prefix capstone_snort_passive"
        "--metric-labels vnf=snort-passive,mode=passive"
        "--skip-nft-check"
        "--systemctl ${pkgs.systemd}/bin/systemctl"
        "--freshness-seconds 60"
      ];
    };
  };

  systemd.timers.capstone-snort-passive-metrics = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "15s";
      OnUnitActiveSec = "15s";
      AccuracySec = "2s";
      Unit = "capstone-snort-passive-metrics.service";
    };
  };
}
