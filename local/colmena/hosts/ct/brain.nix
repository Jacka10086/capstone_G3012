{ config, pkgs, lib, ... }:

{
  imports = [
    ../../modules/ct.nix
    ../../modules/base/ssh-user-key.nix
    ../../modules/env/runtime/node.nix
    ../../modules/services/elasticsearch-kibana.nix
    ../../modules/services/node-exporter.nix
    ../../modules/services/prometheus.nix
    ../../modules/services/grafana.nix
  ];

  networking.hostName = "brain";

  time.timeZone = "UTC";
  system.stateVersion = "25.05";

  services.user-ssh-key.enable = true;

  environment.systemPackages = with pkgs; [ python3 ];

  networking.firewall.allowedTCPPorts = [ 3000 9090 ];

  services.elasticsearch-kibana = {
    enable = true;
    kibanaPublicBaseUrl = "https://kibana.ejun.org";
  };

  users.users.jacka1.extraGroups = [ "docker" ];




  services.capstone-node-exporter = {
    enable = true;
    systemd = true;
    listenAddress = "127.0.0.1";
    openFirewall = false;
  };


}
