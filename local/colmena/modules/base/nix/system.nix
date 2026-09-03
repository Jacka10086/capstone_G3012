{ config, pkgs, lib, ... }:
{

  boot.loader.grub.enable = false;
  boot.isContainer = true;

  fileSystems."/" =
    { device = "/dev/mapper/000000-000000--000000--disk--0";
      fsType = "ext4";
    };

  systemd.suppressedSystemUnits = [
    "dev-mqueue.mount"
    "sys-kernel-debug.mount"
    "sys-fs-fuse-connections.mount"
  ];
}
