{ config, pkgs, lib, ... }:



{
  systemd.services.iperf3-sink = {
    description = "Capstone Broker iPerf3 Traffic Sink";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      ExecStart = "${pkgs.iperf3}/bin/iperf3 -s -B 10.77.20.2 -p 5201";
      Restart = "always";
      RestartSec = "2s";
    };
  };
}
