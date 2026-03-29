{ config, lib, pkgs, ... }:
{
  # Prevent switching to a NixOS generation built for a lower L4T
  # version than the currently running firmware. Downgrading
  # requires re-flashing the device.
  # Only when Jetpack is enabled: `pkgs.nvidia-jetpack` exists only after overlays apply.
  config = lib.mkIf config.hardware.nvidia-jetpack.enable {
    system.preSwitchChecks.jetpackDowngrade =
      # bash
      ''
        # shellcheck disable=SC2034
        incoming="''${1-}"
        action="''${2-}"
        if [ "$action" = "test" ]; then
          echo "Not checking for Jetpack (L4T) downgrade (action = $action)"
          exit 0
        fi

        # Skip in chroot (e.g. nixos-install)
        if systemd-detect-virt --chroot 2>/dev/null; then
          echo "Running in chroot (likely nixos-install)"
          echo "Skipping Jetpack (L4T) downgrade check"
          exit 0
        fi

        if [ ! -f /sys/devices/virtual/dmi/id/bios_version ]; then
          echo "Warning: /sys/devices/virtual/dmi/id/bios_version not found, skipping Jetpack (L4T) downgrade check"
          exit 0
        fi

        # switch-to-configuration runs this script with a minimal PATH
        SED=${lib.getExe' pkgs.gnused "sed"}
        SORT=${lib.getExe' pkgs.coreutils "sort"}
        HEAD=${lib.getExe' pkgs.coreutils "head"}

        # bios_version contains the L4T version, possibly with a unique hash suffix
        # Strip everything after major.minor.patch
        running_l4t="$("$SED" 's/^\([0-9]\+\.[0-9]\+\.[0-9]\+\).*/\1/' < /sys/devices/virtual/dmi/id/bios_version)"
        target_l4t="${pkgs.nvidia-jetpack.l4tMajorMinorPatchVersion}"

        # If target is the lesser version after sorting, it's a downgrade
        oldest="$(printf '%s\n%s' "$target_l4t" "$running_l4t" | "$SORT" -V | "$HEAD" -n1)"
        if [ "$oldest" = "$target_l4t" ] && [ "$target_l4t" != "$running_l4t" ]; then
          echo "Error: L4T version downgrade detected!"
          echo "Running L4T version: $running_l4t"
          echo "Target L4T version:  $target_l4t"
          echo "Downgrading the L4T version is not supported."
          echo "This requires re-flashing the device firmware."
          exit 1
        fi

        echo "Jetpack (L4T) downgrade check passed (running: $running_l4t, target: $target_l4t)"
      '';
  };
}
