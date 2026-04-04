# Machine-specific settings. The guided installer overwrites this file with a hashed password.
# If you copy this template by hand, change hostname, user name, and password before first boot.
{ ... }:

{
  networking.hostName = "orin-nano";

  users.users.nixos = {
    isNormalUser = true;
    extraGroups = [
      "wheel"
      "video"
      "docker"
    ];
    # Remove this and use hashedPassword (see NixOS manual) after first login if you prefer.
    initialPassword = "changeme";
  };

  security.sudo.wheel.enable = true;
}
