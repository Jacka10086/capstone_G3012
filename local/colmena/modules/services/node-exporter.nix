{ config, lib, ... }:





























let
  cfg = config.services.capstone-node-exporter;
  collectors =
    cfg.collectors
    ++ lib.optionals cfg.textfile [ "textfile" ]
    ++ lib.optionals cfg.systemd [ "systemd" ];
in
{
  options.services.capstone-node-exporter = {
    enable = lib.mkEnableOption "Capstone node_exporter on TCP 9100";

    collectors = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "cpu" "meminfo" "netdev" ];
      description = "Shared host collectors. cpu/meminfo/netdev are already node_exporter defaults; listed here so the experiment KPI set is explicit.";
    };

    textfile = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable the textfile collector and create textfileDirectory (iot/vnf custom capstone_*.prom).";
    };

    systemd = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable the systemd unit-state collector (broker/brain).";
    };

    textfileDirectory = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/node_exporter/textfile_collector";
      description = "Directory node_exporter scrapes for *.prom textfiles.";
    };

    listenAddress = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Bind address. null = NixOS default (all interfaces). Use 127.0.0.1 for brain self-scrape.";
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Open TCP 9100. Disable on brain (localhost scrape only).";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 9100;
    };
  };

  config = lib.mkIf cfg.enable (lib.mkMerge [
    {
      services.prometheus.exporters.node = {
        enable = true;
        inherit (cfg) port openFirewall;
        enabledCollectors = collectors;
        extraFlags = lib.optionals cfg.textfile [
          "--collector.textfile.directory=${cfg.textfileDirectory}"
        ];
      } // lib.optionalAttrs (cfg.listenAddress != null) {
        listenAddress = cfg.listenAddress;
      };
    }
    (lib.mkIf cfg.textfile {
      systemd.tmpfiles.rules = [
        "d ${cfg.textfileDirectory} 0755 root root -"
      ];

      systemd.services.prometheus-node-exporter.serviceConfig.BindReadOnlyPaths = [
        cfg.textfileDirectory
      ];
    })
  ]);
}
