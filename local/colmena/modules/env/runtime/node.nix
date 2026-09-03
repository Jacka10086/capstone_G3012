
{ pkgs, lib, ... }:

{
  environment.systemPackages = with pkgs; [

    nodejs
    nodePackages.npm
    nodePackages.yarn


    nodePackages.typescript
    nodePackages.ts-node
    nodePackages.nodemon
    nodePackages.pm2


    htop
    git
    curl
    wget
    nano
    tmux
    tree
  ];


  environment.variables = {
    NODE_ENV = "development";
    NPM_CONFIG_PREFIX = "/etc/node";
    NODE_PATH = "/etc/node/lib/node_modules";
  };


  systemd.tmpfiles.rules = [
    "d /etc/node 0755 root root -"
    "d /var/lib/node-projects 0755 root root -"
    "d /var/lib/node-projects/apps 0755 root root -"
    "d /var/lib/node-projects/libs 0755 root root -"
  ];


  environment.etc."npmrc".text = ''
    prefix=/etc/node
    cache=/var/cache/npm
    registry=https://registry.npmjs.org/
  '';
}