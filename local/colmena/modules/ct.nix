{ config, pkgs, lib, ... }:
{

  imports = [
    ./vm.nix
    ./base/nix/system.nix
    ./base/nix/proxmox-lxc.nix
  ];
}
