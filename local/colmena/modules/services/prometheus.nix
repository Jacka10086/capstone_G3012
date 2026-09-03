{ config, pkgs, lib, ... }:




{
  services.prometheus = {
    enable = true;
    port = 9090;
    globalConfig = {
      scrape_interval = "15s";
      evaluation_interval = "15s";
    };

    extraFlags = [
      "--web.enable-remote-write-receiver"
      "--storage.tsdb.retention.time=7d"
    ];
    scrapeConfigs = [
      { job_name = "vnf-snort"; static_configs = [{ targets = [ "192.168.88.174:9100" ]; labels = { host = "vnf"; role = "snort"; }; }]; }
      { job_name = "iot-devices"; static_configs = [{ targets = [ "192.168.88.175:9100" ]; labels = { host = "iot"; role = "traffic-gen"; }; }]; }
      { job_name = "broker-sink"; static_configs = [{ targets = [ "192.168.88.171:9100" ]; labels = { host = "broker"; role = "traffic-sink"; }; }]; }


      { job_name = "devshell-control"; static_configs = [{ targets = [ "192.168.88.198:9100" ]; labels = { instance = "devshell"; role = "control"; }; }]; }

      { job_name = "pve01"; static_configs = [{ targets = [ "192.168.88.21:9100" ]; labels = { instance = "pve01"; role = "host"; }; }]; }
      { job_name = "brain-self"; static_configs = [{ targets = [ "127.0.0.1:9100" ]; labels = { instance = "brain"; role = "self"; }; }]; }
    ];
    listenAddress = "0.0.0.0";
  };
}
