{ pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    htop
    wget
    curl
    nano
  ];
}
