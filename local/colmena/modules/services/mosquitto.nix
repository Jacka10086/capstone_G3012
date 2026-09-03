{ config, pkgs, lib, ... }:



{
  services.mosquitto = {
    enable = true;
    listeners = [{
      address = "10.77.20.2";
      port = 1883;
      settings = {
        allow_anonymous = false;
        password_file = "/run/keys/mosquitto.passwd";
      };
    }];
  };
}
