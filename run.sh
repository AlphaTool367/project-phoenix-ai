#!/usr/bin/env bash
# Project Phoenix AI — one-command launcher.
# Builds the dashboard once, then serves API + scheduler + dashboard on one port.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

log() { printf '[phoenix] %s\n' "$*"; }
die() { printf '[phoenix] ERROR: %s\n' "$*" >&2; exit 1; }

PYTHON_BIN="${PYTHON:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || PYTHON_BIN=python
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python 3 is required."
command -v node >/dev/null 2>&1 || die "Node.js 18+ is required to build the dashboard."
command -v npm >/dev/null 2>&1 || die "npm is required to build the dashboard."

# Install the system media toolchain when the host supports non-interactive sudo.
# On Windows/macOS the script prints the exact manual next step instead of
# pretending that an OS package was installed.
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  if [[ "${AUTO_INSTALL_SYSTEM_DEPS:-1}" != "0" ]] && command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    log "ffmpeg/ffprobe missing; installing the Linux media toolchain"
    if sudo -n apt-get update -qq && sudo -n DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg libchromaprint-tools; then
      log "ffmpeg toolchain installed"
    else
      log "WARNING: automatic ffmpeg install failed; install ffmpeg manually and rerun"
    fi
  else
    log "WARNING: ffmpeg/ffprobe missing; install ffmpeg before producing media"
  fi
fi

# Create an environment without reinstalling on every launch.
if [[ ! -d .venv ]]; then
  log "creating Python virtual environment"
  "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

REQ_HASH="$(sha256sum requirements.txt | awk '{print $1}')"
REQ_STAMP=".venv/.requirements.sha256"
if [[ ! -f "$REQ_STAMP" ]] || [[ "$(cat "$REQ_STAMP")" != "$REQ_HASH" ]]; then
  log "installing/updating Python dependencies"
  python -m pip install --disable-pip-version-check -q -r requirements.txt
  printf '%s\n' "$REQ_HASH" > "$REQ_STAMP"
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  log "created .env from .env.example; live API keys remain optional"
fi

# Report provider names only; never print credential values. A blank .env is
# valid for mock-safe local testing, but it must be obvious why the dashboard
# shows mock/not-configured instead of looking like a failed key lookup.
configured_providers=()
for provider_key in OPENROUTER_API_KEY GEMINI_API_KEY GROK_API_KEY PEXELS_API_KEY PIXABAY_API_KEY JAMENDO_CLIENT_ID; do
  if grep -Eq "^${provider_key}=[^[:space:]#][^[:space:]]*" .env; then
    configured_providers+=("${provider_key%_API_KEY}")
  fi
done
if [[ ${#configured_providers[@]} -eq 0 ]]; then
  log "WARNING: no non-empty provider API keys found in $ROOT_DIR/.env; AI/media services will show mock/not configured"
else
  log "provider credentials loaded: ${configured_providers[*]} (values hidden)"
fi

mkdir -p data/{backups,cartoons,uploads,media,output,music,thumbnails,logs,tokens} assets secrets
for runtime_dir in data/backups data/cartoons data/uploads data/media data/output data/music data/thumbnails data/logs data/tokens; do
  touch "$runtime_dir/.gitkeep"
done
if [[ ! -f secrets/client_secret.json ]]; then
  log "Google OAuth credentials not found at secrets/client_secret.json; YouTube connection will remain unavailable until the private JSON is added"
else
  log "Google OAuth credentials found: secrets/client_secret.json"
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  log "WARNING: media toolchain is incomplete; Cartoon/Story/Remix output may fail until ffmpeg and ffprobe are installed."
else
  log "media toolchain ready: $(ffmpeg -version 2>/dev/null | head -1)"
fi
if ! python -m pip show faster-whisper >/dev/null 2>&1; then
  log "WARNING: faster-whisper package is unavailable; Remix will show an actionable install error."
else
  log "speech-to-text tool ready: faster-whisper"
fi
if ! python -m pip show yt-dlp >/dev/null 2>&1; then
  log "WARNING: yt-dlp package is unavailable; Cartoon search/download will be disabled."
fi
if ! command -v fpcalc >/dev/null 2>&1; then
  log "WARNING: fpcalc is unavailable; AcoustID fingerprint checks need libchromaprint-tools plus ACOUSTID_API_KEY."
else
  log "copyright fingerprint tool ready: fpcalc"
fi

# Install exactly the lockfile dependencies when the lockfile changes.
if [[ -f frontend/package-lock.json ]]; then
  LOCK_HASH="$(sha256sum frontend/package-lock.json | awk '{print $1}')"
  LOCK_STAMP="frontend/node_modules/.package-lock.sha256"
  if [[ ! -d frontend/node_modules ]] || [[ ! -f "$LOCK_STAMP" ]] || [[ "$(cat "$LOCK_STAMP")" != "$LOCK_HASH" ]]; then
    log "installing dashboard dependencies from package-lock.json"
    (cd frontend && npm ci --no-audit --no-fund)
    printf '%s\n' "$LOCK_HASH" > "$LOCK_STAMP"
  fi
elif [[ ! -d frontend/node_modules ]]; then
  log "package-lock.json not found; installing dashboard dependencies with npm"
  (cd frontend && npm install --no-audit --no-fund)
fi

# Build the dashboard so FastAPI can serve it from the same port as the API.
if [[ ! -f frontend/dist/index.html ]] || find frontend/src frontend/index.html frontend/*.json frontend/*.js frontend/*.ts -type f -newer frontend/dist/index.html -print -quit | grep -q .; then
  log "building dashboard"
  npm --prefix frontend run build
fi

API_PORT="${API_PORT:-8000}"
if [[ -f .env ]]; then
  configured_port="$(awk -F= '$1 == "API_PORT" {gsub(/[[:space:]]/, "", $2); print $2; exit}' .env || true)"
  [[ -n "$configured_port" ]] && API_PORT="$configured_port"
fi

if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "http://127.0.0.1:${API_PORT}/api" >/dev/null 2>&1; then
  log "Phoenix is already running at http://127.0.0.1:${API_PORT}"
  exit 0
fi

log "starting API, scheduler and dashboard at http://127.0.0.1:${API_PORT}"
log "API docs: http://127.0.0.1:${API_PORT}/docs"
exec python backend/cli.py serve
