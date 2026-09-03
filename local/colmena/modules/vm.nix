{ config, pkgs, lib, ... }:
{

  imports = [
    ./base/nix/common.nix
    ./base/nix/nix-cache.nix
    ./base/tools.nix
  ];
}
