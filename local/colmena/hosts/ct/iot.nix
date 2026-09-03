{ config, pkgs, lib, ... }:

let
  zombieModeTool = pkgs.writeShellScriptBin "capstone-zombie-mode" ''
    set -euo pipefail

    action="''${1:-status}"
    state=/var/lib/capstone-zombie/mode
    case "$action" in
      off|low|high|panic|critical)
        tmp=$(mktemp /var/lib/capstone-zombie/.mode.XXXXXX)
        printf '%s\n' "$action" > "$tmp"
        chmod 0644 "$tmp"
        mv "$tmp" "$state"
        systemctl restart capstone-zombie-traffic.service
        ;;
      status)
        mode=off
        [ -r "$state" ] && mode=$(tr -d '[:space:]' < "$state")
        printf '%s\n' "$mode"
        ;;
      *) echo "usage: capstone-zombie-mode [off|low|high|panic|critical|status]" >&2; exit 2 ;;
    esac
  '';
in
{
  imports = [
    ../../modules/ct.nix
    ../../modules/base/ssh-user-key.nix
    ../../modules/services/node-exporter.nix
    ../../modules/services/iperf3-client.nix
    ../../modules/services/capstone-mqtt-traffic.nix
    ../../modules/services/capstone-zombie-traffic.nix
    ../../modules/services/capstone-mqtt-probe.nix
  ];

  networking.hostName = "iot";

  time.timeZone = "UTC";
  system.stateVersion = "25.05";

  systemd.network.networks."10-capstone-data" = {
    matchConfig.MACAddress = "02:77:10:00:01:00";
    address = [ "10.77.10.2/30" ];
    routes = [{
      Destination = "10.77.20.0/30";
      Gateway = "10.77.10.1";
    }];
    linkConfig.RequiredForOnline = "no";
    networkConfig = {
      DHCP = "no";
      IPv6AcceptRA = false;
      LinkLocalAddressing = "no";
    };
  };

  services.user-ssh-key.enable = true;

  environment.systemPackages = with pkgs; [
    mosquitto
    curl
    wget
    iperf3
    zombieModeTool
  ];

  services.capstone-node-exporter = {
    enable = true;
    textfile = true;
  };

  services.capstone-iperf3-client = {
    enable = true;
  };


}
