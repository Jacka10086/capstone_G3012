{ config, lib, pkgs, ... }:

with lib;

let
  cfg = config.services.elasticsearch-kibana;
  provisionScript = pkgs.writeScript "kibana-provision-capstone" (
    builtins.readFile ./kibana-provision-capstone.py
  );
in
{
  options.services.elasticsearch-kibana = {
    enable = mkEnableOption "Elasticsearch + Kibana (Docker) for Capstone dataset exploration";

    elasticsearchImage = mkOption {
      type = types.str;
      default = "docker.elastic.co/elasticsearch/elasticsearch:7.17.27";
      description = "Elasticsearch container image.";
    };

    kibanaImage = mkOption {
      type = types.str;
      default = "docker.elastic.co/kibana/kibana:7.17.27";
      description = "Kibana container image (must match Elasticsearch major.minor).";
    };

    clusterName = mkOption {
      type = types.str;
      default = "capstone-brain";
      description = "Elasticsearch cluster.name.";
    };

    dataDir = mkOption {
      type = types.path;
      default = "/var/lib/elasticsearch-docker";
      description = "Host path mounted as Elasticsearch data directory.";
    };

    elasticsearchHost = mkOption {
      type = types.str;
      default = "127.0.0.1";
      description = "Address Elasticsearch binds to (keep localhost; do not expose publicly).";
    };

    elasticsearchPort = mkOption {
      type = types.port;
      default = 9200;
      description = "Elasticsearch HTTP port.";
    };

    kibanaPort = mkOption {
      type = types.port;
      default = 5601;
      description = "Kibana HTTP port (public via FRPC/Caddy).";
    };

    kibanaPublicBaseUrl = mkOption {
      type = types.str;
      default = "https://kibana.ejun.org";
      description = "Kibana server.publicBaseUrl.";
    };

    javaOpts = mkOption {
      type = types.str;
      default = "-Xms512m -Xmx512m";
      description = "ES_JAVA_OPTS heap settings.";
    };

    openFirewall = mkOption {
      type = types.bool;
      default = true;
      description = "Open kibanaPort in the host firewall (not elasticsearchPort).";
    };

    credentialsFile = mkOption {
      type = types.path;
      default = "/run/keys/elasticsearch.env";
      description = "Runtime env file holding ELASTIC_PASSWORD and ELASTICSEARCH_USERNAME/ELASTICSEARCH_PASSWORD for the containers and the provisioning service; credentials stay out of this repository.";
    };

    provisionCapstoneDashboard = mkOption {
      type = types.bool;
      default = true;
      description = "After Kibana is up, upsert Capstone index-pattern/visualizations/dashboard via saved-objects API.";
    };
  };

  config = mkIf cfg.enable {
    virtualisation.docker.enable = true;
    virtualisation.oci-containers.backend = "docker";

    networking.firewall.allowedTCPPorts = mkIf cfg.openFirewall [ cfg.kibanaPort ];

    systemd.tmpfiles.rules = [
      "d ${cfg.dataDir} 0755 1000 1000 -"
    ];

    virtualisation.oci-containers.containers.elasticsearch = {
      image = cfg.elasticsearchImage;
      autoStart = true;
      extraOptions = [ "--network=host" ];
      environmentFiles = [ cfg.credentialsFile ];
      environment = {
        "discovery.type" = "single-node";
        "ES_JAVA_OPTS" = cfg.javaOpts;
        "xpack.security.enabled" = "true";
        "cluster.name" = cfg.clusterName;
        "network.host" = cfg.elasticsearchHost;
        "http.port" = toString cfg.elasticsearchPort;
      };
      volumes = [ "${cfg.dataDir}:/usr/share/elasticsearch/data" ];
    };

    virtualisation.oci-containers.containers.kibana = {
      image = cfg.kibanaImage;
      autoStart = true;
      extraOptions = [ "--network=host" ];
      environmentFiles = [ cfg.credentialsFile ];
      environment = {
        ELASTICSEARCH_HOSTS = "http://${cfg.elasticsearchHost}:${toString cfg.elasticsearchPort}";
        SERVER_HOST = "0.0.0.0";
        SERVER_PORT = toString cfg.kibanaPort;
        SERVER_PUBLICBASEURL = cfg.kibanaPublicBaseUrl;
        SERVER_NAME = "kibana";
        XPACK_SECURITY_ENABLED = "true";
      };
    };

    systemd.services.docker-kibana = {
      after = [ "docker-elasticsearch.service" ];
      requires = [ "docker-elasticsearch.service" ];
    };

    systemd.services.docker-elasticsearch.serviceConfig.ExecStartPre = [
      "-${pkgs.docker}/bin/docker rm -f elasticsearch"
    ];
    systemd.services.docker-kibana.serviceConfig.ExecStartPre = [
      "-${pkgs.docker}/bin/docker rm -f kibana"
    ];

    systemd.services.kibana-provision-capstone = mkIf cfg.provisionCapstoneDashboard {
      description = "Provision Capstone Kibana dashboard (saved objects)";
      after = [ "docker-kibana.service" ];
      wants = [ "docker-kibana.service" ];
      wantedBy = [ "multi-user.target" ];
      path = [ pkgs.python3 ];
      environment = {
        KIBANA_URL = "http://127.0.0.1:${toString cfg.kibanaPort}";
        http_proxy = "";
        https_proxy = "";
        HTTP_PROXY = "";
        HTTPS_PROXY = "";
        ALL_PROXY = "";
        NO_PROXY = "*";
      };
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        EnvironmentFile = [ cfg.credentialsFile ];
        ExecStart = "${pkgs.python3}/bin/python3 ${provisionScript}";
      };
      restartTriggers = [ provisionScript ];
    };

    environment.systemPackages = with pkgs; [ curl jq python3 ];
  };
}
