{ config, pkgs, lib, ... }:

let
  capstoneZombieTraffic = pkgs.writeScriptBin "capstone-zombie-traffic" ''

    ${builtins.readFile ../../packages/capstone-zombie-traffic.py}
  '';
  mqttBrokerAddr = "10.77.20.2";
  junkTargetPort = "19999";
in

{
  systemd.services.capstone-zombie-traffic = {
    description = "Capstone zombie IoT UDP traffic generator (blocked by Snort)";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "simple";
      User = "root";
      Restart = "on-failure";
      RestartSec = "5s";
      TimeoutStopSec = "10s";
      ExecStart = lib.concatStringsSep " " [
        "${capstoneZombieTraffic}/bin/capstone-zombie-traffic"
        "--target ${mqttBrokerAddr}"
        "--port ${junkTargetPort}"
        "--packet-size 256"
        "--sockets 20"
        "--mode-file /var/lib/capstone-zombie/mode"
        "--output /var/lib/node_exporter/textfile_collector/capstone_zombie.prom"
        "--state /var/lib/capstone-zombie/state.json"
        "--metrics-interval 15"
      ];

      ExecStop = "${pkgs.coreutils}/bin/rm -f /var/lib/node_exporter/textfile_collector/capstone_zombie.prom";
    };
  };

  systemd.tmpfiles.rules = [
    "d /var/lib/capstone-zombie 0700 root root -"
    "f /var/lib/capstone-zombie/mode 0644 root root - off"
  ];
}
