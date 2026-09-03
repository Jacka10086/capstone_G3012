{ config, pkgs, lib, ... }:

let
  cfg = config.services.user-ssh-key;
in
{
  options.services.user-ssh-key = {
    enable = lib.mkEnableOption "auto-generate user SSH ed25519 key if missing";

    user = lib.mkOption {
      type = lib.types.str;
      default = "jacka1";
      description = "User for whom to ensure an SSH key exists.";
    };
  };

  config = lib.mkIf cfg.enable {
    system.activationScripts.userSshKey = lib.stringAfter [ "users" ] ''
      TARGET_USER="${cfg.user}"
      HOME_DIR="/home/$TARGET_USER"
      SSH_DIR="$HOME_DIR/.ssh"
      KEY_FILE="$SSH_DIR/id_ed25519"

      mkdir -p "$SSH_DIR"

      if [ ! -f "$KEY_FILE" ]; then
        ${pkgs.openssh}/bin/ssh-keygen -t ed25519 -C "$TARGET_USER@$(hostname)" -f "$KEY_FILE" -N ""
        echo "Generated SSH key for $TARGET_USER"
      fi


      chown -R "$TARGET_USER" "$SSH_DIR"
      chmod 700 "$SSH_DIR"
      chmod 600 "$KEY_FILE"
      chmod 644 "$KEY_FILE.pub"
    '';
  };
}
