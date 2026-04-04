#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: start-docker-example.sh /path/to/examples/<name>/docker" >&2
  exit 2
}

[[ "${1:-}" ]] || usage
DIR="$1"
[[ -d "$DIR" ]] || usage

cd "$DIR"

compose=""
if [[ -f compose.yaml ]]; then
  compose=compose.yaml
elif [[ -f compose.yml ]]; then
  compose=compose.yml
else
  echo "error: no compose.yaml or compose.yml in $DIR" >&2
  exit 1
fi

if grep -qF 'ai-net' "$compose" 2>/dev/null; then
  docker network create ai-net 2>/dev/null || true
fi

docker compose -f "$compose" up -d
echo "Started from $DIR ($compose)"
