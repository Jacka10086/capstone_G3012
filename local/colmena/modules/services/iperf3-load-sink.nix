{ config, pkgs, lib, ... }:



{
  systemd.services.iperf3-load-sink = {
    description = "Capstone Broker iPerf3 Load Sink (port 5202)";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      ExecStart = "${pkgs.iperf3}/bin/iperf3 -s -B 10.77.20.2 -p 5202";
      Restart = "always";
      RestartSec = "2s";
    };
  };
}
