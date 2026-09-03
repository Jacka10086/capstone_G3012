{ config, pkgs, lib, ... }:

let
  capstonePython = pkgs.python3.withPackages (ps: [ ps.paho-mqtt ]);
  capstoneMqttProbe = pkgs.writeScriptBin "capstone-mqtt-probe" ''

    ${builtins.readFile ../../packages/capstone-mqtt-probe.py}
  '';
  mqttBrokerAddr = "10.77.20.2";
in


{
  systemd.services.capstone-mqtt-probe = {
    description = "Capstone MQTT QoS probe through vnf-snort";
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
        "${capstoneMqttProbe}/bin/capstone-mqtt-probe"
        "--broker ${mqttBrokerAddr}"
        "--port 1883"
        "--topic home/probe/qos"
        "--client-id capstone-mqtt-probe"
        "--rate 10"
        "--payload-size 256"
        "--qos 1"
        "--output /var/lib/node_exporter/textfile_collector/capstone_mqtt_probe.prom"
        "--state /var/lib/capstone-mqtt-probe/state.json"
        "--metrics-interval 15"
        "--window 60"
      ];

      ExecStop = "${pkgs.coreutils}/bin/rm -f /var/lib/node_exporter/textfile_collector/capstone_mqtt_probe.prom";
    };
  };

  systemd.tmpfiles.rules = [
    "d /var/lib/capstone-mqtt-probe 0700 root root -"
  ];
}
