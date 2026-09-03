{ config, pkgs, lib, ... }:

let




  dashboardDir = pkgs.runCommand "capstone-grafana-dashboards" {} ''
    mkdir -p $out
    cp ${../../hosts/ct/wangzheng.json} $out/wangzheng.json
  '';
in


{
  services.grafana = {
    enable = true;
    settings = {
      server = {
        http_addr = "0.0.0.0";
        http_port = 3000;
        domain = "grafana.ejun.org";
        root_url = "https://grafana.ejun.org/";
      };
      security = {
        admin_user = "admin";
        admin_password = "$__file{/run/keys/grafana-admin-password}";
      };
      auth.anonymous = { enabled = true; org_role = "Viewer"; };
    };
    provision = {
      enable = true;
      datasources.settings = {
        apiVersion = 1;
        datasources = [{ name = "Prometheus"; type = "prometheus"; uid = "prometheus"; access = "proxy"; url = "http://127.0.0.1:9090"; isDefault = true; editable = false; }];
      };
      dashboards.settings = {
        apiVersion = 1;
        providers = [{ name = "capstone"; orgId = 1; folder = "Capstone"; type = "file"; disableDeletion = false; updateIntervalSeconds = 30; options.path = "${dashboardDir}"; }];
      };
    };
  };
}
