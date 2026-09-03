{ config, pkgs, lib, ... }:

let
  capstonePython = pkgs.python3.withPackages (ps: [ ps.paho-mqtt ]);
  capstoneMqttTraffic = pkgs.writeScriptBin "capstone-mqtt-traffic" ''

    ${builtins.readFile ../../packages/capstone-mqtt-traffic.py}
  '';
  mqttBrokerAddr = "10.77.20.2";
in


{
  systemd.services.capstone-mqtt-traffic = {
    description = "Capstone smart-home MQTT device traffic generator";
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
        "${capstoneMqttTraffic}/bin/capstone-mqtt-traffic"
        "--broker ${mqttBrokerAddr}"
        "--port 1883"
        "--output /var/lib/node_exporter/textfile_collector/capstone_mqtt.prom"
        "--state /var/lib/capstone-mqtt/state.json"
        "--metrics-interval 15"
      ];

      ExecStop = "${pkgs.coreutils}/bin/rm -f /var/lib/node_exporter/textfile_collector/capstone_mqtt.prom";
    };
  };

  systemd.tmpfiles.rules = [
    "d /var/lib/capstone-mqtt 0700 root root -"
  ];
}
