# Orin Nano Super — NixOS template

For **Jetson Orin Nano Super Developer Kit** (`som = orin-nano`, `carrierBoard = devkit`, `super = true`).

## Guided (recommended)

From the **installer live session** (this repo’s ISO includes the helpers):

1. **Disk (optional automation)**  
   - `sudo prepare-orin-nano-super-disk` — if you answer **yes**, it wipes the chosen whole disk (GPT: EFI + ext4), mounts it on `/mnt`, and prints the next commands.  
   - If you answer **no**, it only prints the **manual** partitioning steps (same as the NixOS handbook); you can run the command again later when you want automation.

2. `sudo nixos-generate-config --root /mnt`

3. `sudo install-orin-nano-super`

4. `sudo nixos-install --root /mnt --flake /mnt/etc/nixos#nixos`

To print manual steps only: `prepare-orin-nano-super-disk --manual-only`

## Manual

1. Copy everything in this directory to `/mnt/etc/nixos/`.
2. Edit `local.nix` (hostname, user, `initialPassword` or `hashedPassword`).
3. Ensure `flake.nix` `inputs.jetpack.url` points at the flake you use.
4. `nixos-install --root /mnt --flake /mnt/etc/nixos#nixos`

After boot, run `passwd` immediately if you used `initialPassword`.
