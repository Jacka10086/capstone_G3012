{ config, pkgs, lib, ... }:
{
  imports = [
    ../../modules/ct.nix
    ../../modules/base/ssh-user-key.nix
    ../../modules/services/node-exporter.nix
    ../../modules/services/mosquitto.nix
    ../../modules/services/iperf3-sink.nix
    ../../modules/services/iperf3-load-sink.nix
  ];

  networking.hostName = "broker";

  time.timeZone = "UTC";
  system.stateVersion = "25.05";

  services.user-ssh-key.enable = true;

  systemd.network.networks."10-capstone-data" = {
    matchConfig.MACAddress = "02:77:20:00:01:03";
    address = [ "10.77.20.2/30" ];
    routes = [{
      Destination = "10.77.10.0/30";
      Gateway = "10.77.20.1";
    }];
    linkConfig.RequiredForOnline = "no";
    networkConfig = {
      DHCP = "no";
      IPv6AcceptRA = false;
      LinkLocalAddressing = "no";
    };
  };

  environment.systemPackages = with pkgs; [
    iperf3
    tcpdump
    mosquitto
  ];

  networking.firewall.interfaces.eth1 = {
    allowedTCPPorts = [ 5201 5202 1883 ];
    allowedUDPPorts = [ 5201 5202 ];
  };


  services.capstone-node-exporter = {
    enable = true;
    systemd = true;
  };
}
