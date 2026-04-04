# Roadmap: Orin Nano Super, easy install, examples

This file is the **project direction** for a fork focused on **Jetson Orin Nano Super Developer Kit** and **non-expert** users. It does not commit to dates; it orders work by impact and effort.

## Vision

- **One hardware target** for the “happy path”: Orin Nano Super + devkit (`som = "orin-nano"`, `carrierBoard = "devkit"`, `super = true`).
- After flashing firmware and running the installer, users should **not** need to hand-edit `fetchTarball` URLs or understand flakes to get a working GPU stack.
- **Examples** (`examples/`) should be runnable from a **normal user account** with minimal commands (optional `start.sh` per stack).

## Current baseline (what works today)

- Flash script, minimal installer ISO (JetPack enabled in the **live** installer — see `installer_minimal_config` in `flake.nix`).
- **Implemented:** `templates/orin-nano-super/`, `install-orin-nano-super` on the ISO (`modules/installer-orin-nano-helper.nix`), and `examples/*/docker/start.sh` — see main `README.md` and `examples/README.md`.
- **Still open:** Phase 0 “golden path” doc as a single linear guide; Phase 3 “default install layout without running the script” if you want zero questions beyond disk layout.

---

## Phase 0 — Clarify the golden path (docs only)

**Goal:** One ordered checklist: recovery mode → flash UEFI (if needed) → write ISO → UEFI boot → partition → install → first boot.

**Deliverables:**

- Short “Orin Nano Super only” walkthrough (README section or separate `docs/install-orin-nano-super.md`).
- Explicit note: ISO live session ≠ installed config; users must still merge JetPack into `/etc/nixos` until Phase 2/3.

**You:** Write or review that doc; no Nix code required.

---

## Phase 1 — Template configuration (low code, high win)

**Goal:** Copy-paste **one** known-good layout instead of composing snippets from the README.

**Deliverables:**

- Directory e.g. `templates/orin-nano-super/` containing:
  - `flake.nix` (pinned `nixpkgs` + input to this flake, `nixosModules.default`).
  - `configuration.nix` with only Orin Nano Super `hardware.nvidia-jetpack.*` and `hardware.graphics.enable`.
- `README` or doc: after `nixos-generate-config --root /mnt`, either merge `imports` or use the template as the new `/etc/nixos` and add `hardware-configuration.nix`.

**You:** Done — `templates/orin-nano-super/README.md`.

---

## Phase 2 — Guided post-partition script (best UX / effort ratio)

**Goal:** From the **live USB**, a script asks a few questions (**hostname**, **username**, **real name**, **password or “SSH key later”**) and writes `/mnt/etc/nixos/*` using the Phase 1 template + generated `hardware-configuration.nix` if present.

**Deliverables:**

- `scripts/install-orin-nano-super.sh` (or similar), idempotent where possible, clear errors.
- Optional: ship the script **on the ISO** via a small NixOS installer module (`environment.systemPackages` or a desktop file — whatever fits the minimal ISO).

**You:** Done — `scripts/install-orin-nano-super.sh`, packaged as `orin-nano-super-install-helper`, on the minimal ISO.

---

## Phase 3 — Installer ISO bakes in default Orin Nano Super config (optional, more maintenance)

**Goal:** `nixos-install` without a separate script — the **default** files prepared for install already include the JetPack module for Orin Nano Super.

**Deliverables:**

- Extend installer configuration in `flake.nix` so the target configuration template matches Phase 1 (only disk layout remains user-specific).
- Regression testing on real hardware each nixpkgs bump.

**You:** Partially done — ISO ships templates under `/etc/orin-nano-super-template/` and the helper command; **not** done: changing `nixos-install`’s default generated config without running the script.

---

## Phase 4 — Examples under the desktop user

**Goal:** “Start Ollama / agent-layer / …” without hunting paths.

**Deliverables:**

- Document: clone repo to e.g. `~/jetpack-nixos` (or sync `examples/` only).
- Per example: optional `start.sh` next to `compose.yaml` (check Docker, create `ai-net` if needed, `docker compose up -d`).
- Optional NixOS/Home-Manager: copy or link `examples` into `$HOME` on first login (heavier; align with Phase 2/3 choices).

**You:** Done — shared `examples/lib/start-docker-example.sh` and per-example `docker/start.sh`; overview in `examples/README.md`.

---

## Out of scope (unless someone volunteers)

- Full **graphical** installer (Calamares-style) for NixOS on Jetson.
- **nixos-anywhere** as the *primary* story for non-IT users (great for admins, not the first milestone).

---

## Suggested order to actually do the work

1. Phase 0 (checklist doc) — **1 session**  
2. Phase 1 (templates) — **1–2 sessions**  
3. Phase 2 (guided script) — **2–3 sessions**  
4. Phase 4 (example `start.sh` + doc) — **parallel or after Phase 1**  
5. Phase 3 (ISO default config) — **when** you want minimum user steps and accept maintenance

If you only pick **one** engineering task: **Phase 1 + Phase 2** gives the closest thing to an “installer” without rewriting NixOS’s install flow.
