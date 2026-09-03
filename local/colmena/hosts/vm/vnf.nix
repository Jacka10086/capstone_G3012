{ config, pkgs, lib, modulesPath, ... }:
{
  imports = [
    (modulesPath + "/profiles/qemu-guest.nix")
    ../../modules/vm.nix
    ../../modules/services/snort-inline.nix
    ../../modules/services/snort-passive.nix
    ../../modules/services/vfw.nix
    ../../modules/services/node-exporter.nix
  ];

  networking.hostName = "vnf";

  time.timeZone = "UTC";
  system.stateVersion = "25.05";

  networking.interfaces.ens19 = {
    useDHCP = false;
    ipv4.addresses = [{
      address = "10.77.10.1";
      prefixLength = 30;
    }];
  };
  networking.interfaces.ens20 = {
    useDHCP = false;
    ipv4.addresses = [{
      address = "10.77.20.1";
      prefixLength = 30;
    }];
  };
  networking.firewall.checkReversePath = "loose";
  boot.kernel.sysctl."net.ipv4.ip_forward" = 1;

  boot.loader.grub.enable = true;
  boot.loader.grub.devices = [ "/dev/sda" ];

  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "ext4";
  };

  environment.systemPackages = with pkgs; [

    iperf3
    tcpdump
  ];

  networking.firewall.allowedTCPPorts = [ 22 ];

  services.openssh.openFirewall = true;

  services.capstone-node-exporter = {
    enable = true;
    textfile = true;
  };
}
