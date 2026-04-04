# Examples (Docker stacks)

Use these from a **normal user** after you have cloned this repository (for example into `~/jetpack-nixos`).

## Prerequisites

- Docker enabled on NixOS (`virtualisation.docker.enable = true`; your user should be in the `docker` group, or use `sudo`).
- For GPU in containers: `hardware.nvidia-container-toolkit.enable = true` (see the Orin Nano Super template under `templates/orin-nano-super/`).

## Start a stack

Each stack has a `docker/` directory. From the repo root:

```bash
chmod +x examples/ollama/docker/start.sh   # once, if your checkout has no exec bit
./examples/ollama/docker/start.sh
```

The shared helper `examples/lib/start-docker-example.sh` picks `compose.yaml` or `compose.yml`, creates the external `ai-net` network when the compose file references it, then runs `docker compose up -d`.

Read each example’s own `README.md` for `.env` files and ports.

## Layout

| Directory | Role |
|-----------|------|
| `lib/start-docker-example.sh` | Shared launcher |
| `*/docker/start.sh` | Thin wrapper for that example |
