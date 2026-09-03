import (fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/nixos-25.05.tar.gz";
  sha256 = "0v6bd1xk8a2aal83karlvc853x44dg1n4nk08jg3dajqyy0s98np";
}) {
  config = {
    allowUnfree = true;
    android_sdk.accept_license = true;
  };
}
