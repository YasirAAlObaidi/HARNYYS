#!/usr/bin/env bash
# Developer setup on a Mac: Docker (through Colima), the dev Postgres and the Python environment.
# Safe to run again: every step checks first and skips what is already done.
#
#   scripts/setup-mac.sh
#
# Colima is a small Linux VM that runs Docker; it is free and has no desktop app. Change its size with
# COLIMA_CPU, COLIMA_MEMORY (GB) and COLIMA_DISK (GB). Leave memory free for a local model (Ollama, llama.cpp),
# which runs natively on the Mac because Docker on macOS cannot use the GPU (docs/decisions/0004).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COLIMA_CPU="${COLIMA_CPU:-4}"
COLIMA_MEMORY="${COLIMA_MEMORY:-6}"
COLIMA_DISK="${COLIMA_DISK:-60}"

step() { printf '\n==> %s\n' "$*"; }

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is needed first: https://brew.sh" >&2
  exit 1
fi

step "Installing Colima, the Docker CLI, Compose, Buildx and uv (skipped if present)"
for formula in colima docker docker-compose docker-buildx uv; do
  if brew list --formula "$formula" >/dev/null 2>&1; then
    echo "$formula: already installed"
  else
    brew install "$formula"
  fi
done

step "Telling Docker where Homebrew put the Compose and Buildx plugins (~/.docker/config.json)"
# Merges one setting into the file and keeps everything else in it.
python3 - "$(brew --prefix)/lib/docker/cli-plugins" <<'PY'
import json
import pathlib
import sys

plugin_dir = sys.argv[1]
path = pathlib.Path.home() / ".docker" / "config.json"
path.parent.mkdir(parents=True, exist_ok=True)
config = json.loads(path.read_text()) if path.exists() and path.read_text().strip() else {}
dirs = config.setdefault("cliPluginsExtraDirs", [])
if plugin_dir in dirs:
    print("already set")
else:
    dirs.append(plugin_dir)
    path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"added {plugin_dir}")
PY

step "Starting Colima (${COLIMA_CPU} CPUs, ${COLIMA_MEMORY} GB memory, ${COLIMA_DISK} GB disk)"
if colima status >/dev/null 2>&1; then
  echo "already running"
else
  colima start --cpu "$COLIMA_CPU" --memory "$COLIMA_MEMORY" --disk "$COLIMA_DISK"
fi
docker compose version
docker buildx version

step "Starting the dev Postgres on 127.0.0.1:55432 (deploy/compose.dev.yaml)"
docker compose -f "$REPO_DIR/deploy/compose.dev.yaml" up -d --wait

step "Installing the Python environment (apps/server)"
(cd "$REPO_DIR/apps/server" && uv sync)

cat <<EOF

Done. Check everything with:
  cd apps/server && uv run pytest -q && uv run lint-imports

After a reboot, start Docker again with:  colima start
(or have it start at login:  brew services start colima)
EOF
