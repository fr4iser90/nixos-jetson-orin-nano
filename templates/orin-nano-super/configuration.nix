# Edit ./local.nix for hostname, user, and passwords (or run install-orin-nano-super from the installer ISO).
{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./local.nix
  ];

  hardware.nvidia-jetpack.enable = true;
  hardware.nvidia-jetpack.som = "orin-nano";
  hardware.nvidia-jetpack.carrierBoard = "devkit";
  hardware.nvidia-jetpack.super = true;
  hardware.graphics.enable = true;

  # For Docker examples under ~/jetpack-nixos/examples (optional: disable if unused).
  virtualisation.docker.enable = true;
  hardware.nvidia-container-toolkit.enable = true;

  services.openssh.enable = true;

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  system.stateVersion = "25.11";
}
