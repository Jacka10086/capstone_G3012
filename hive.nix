{
  meta = {
    nixpkgs = import ./nixpkgs.nix;
    description = "Bristol Capstone Colmena fleet (capstone nodes)";
  };


  iot = { name, nodes, ... }: {
    deployment = {
      targetHost = "192.168.88.175";
      targetPort = 22;
      targetUser = "jacka1";
    };

    imports = [
      ./local/colmena/hosts/ct/iot.nix
    ];
  };


  vnf = { name, nodes, ... }: {
    deployment = {
      targetHost = "192.168.88.174";
      targetPort = 22;
      targetUser = "jacka1";
    };

    imports = [
      ./local/colmena/hosts/vm/vnf.nix
    ];
  };


  brain = { name, nodes, ... }: {
    deployment = {
      targetHost = "192.168.88.173";
      targetPort = 22;
      targetUser = "jacka1";
    };

    imports = [
      ./local/colmena/hosts/ct/brain.nix
    ];
  };


  broker = { name, nodes, ... }: {
    deployment = {
      targetHost = "192.168.88.171";
      targetPort = 22;
      targetUser = "jacka1";
    };

    imports = [
      ./local/colmena/hosts/ct/broker.nix
    ];
  };
}