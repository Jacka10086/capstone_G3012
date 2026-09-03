{ config, modulesPath, pkgs, lib, ... }:
{
  imports = [
    (modulesPath + "/virtualisation/proxmox-lxc.nix")
  ];

  proxmoxLXC = {
    manageNetwork = false;



    manageHostName = true;
    privileged = true;
  };
  security.pam.services.sshd.allowNullPassword = true;
}
