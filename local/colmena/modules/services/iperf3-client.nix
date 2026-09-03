{ config, pkgs, lib, ... }:

let
  cfg = config.services.capstone-iperf3-client;
  capstoneIperf3Client = pkgs.writeScriptBin "capstone-iperf3-client" ''

    ${builtins.readFile ../../packages/capstone-iperf3-client.py}
  '';
in






{
  options.services.capstone-iperf3-client = {
    enable = lib.mkEnableOption "Capstone iperf3 background traffic client (iot -> broker :5202)";
  };

  config = lib.mkIf cfg.enable {
    systemd.services.capstone-iperf3-client = {
      description = "Capstone iperf3 background traffic client (iot -> broker :5202)";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        Type = "simple";
        User = "root";
        Restart = "no";
        ExecStart = lib.concatStringsSep " " [
          "${capstoneIperf3Client}/bin/capstone-iperf3-client"
          "--server 10.77.20.2"
          "--port 5202"
          "--output /var/lib/node_exporter/textfile_collector/capstone_iperf.prom"
          "--bandwidth 100M"
          "--length 1400"
          "--duration 5"
          "--interval 15"
        ];
      };
    };
  };
}
