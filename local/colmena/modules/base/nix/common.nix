{ config, pkgs, lib, ... }:
{

  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  time.timeZone = lib.mkDefault "America/Los_Angeles";
  nixpkgs.config.allowUnfree = true;
  nix.settings.sandbox = false;

  nix.settings.trusted-users = [ "root" "jacka1" ];
}
