#!/usr/bin/env bash
# install-wiki-stack.sh — idempotent bootstrap of the teacher-agent wiki
# hosting stack on nl-claude01.
#
# Installs:
#   1. /home/app-user/.wiki-venv  (mkdocs-material Python venv)
#   2. /etc/caddy/Caddyfile            (wiki-specific config, from scripts/setup/)
#   3. /etc/tmpfiles.d/claude-gateway.conf (lockfile dir; lives here anyway
#      but we include it in one place for the teacher-agent VM rebuild case)
#   4. First wiki build (so Caddy has something to serve)
#   5. Enable + reload Caddy
#
# After running: nginx-proxy-manager just needs the wiki.example.net
# host pointed at http://nl-claude01:8080. Both Internet DNS + internal
# DNS lookups land on Caddy.
#
# Usage:
#   sudo scripts/setup/install-wiki-stack.sh
#
# Safe to re-run — every step is idempotent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WIKI_VENV="/home/app-user/.wiki-venv"
CADDYFILE_SRC="$REPO_ROOT/scripts/setup/Caddyfile-wiki"
CADDYFILE_DST="/etc/caddy/Caddyfile"
TMPFILES_SRC="$REPO_ROOT/scripts/setup/tmpfiles-claude-gateway.conf"
TMPFILES_DST="/etc/tmpfiles.d/claude-gateway.conf"

log() { printf "\033[1;34m[wiki-stack]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[wiki-stack]\033[0m %s\n" "$*" >&2; }
err() { printf "\033[1;31m[wiki-stack]\033[0m %s\n" "$*" >&2; exit 1; }

[ "$EUID" = "0" ] || err "run with sudo — this script writes to /etc and manages systemd"

# ── 1. Python venv + mkdocs ───────────────────────────────────────────────
if [ ! -x "$WIKI_VENV/bin/mkdocs" ]; then
  log "installing mkdocs-material into $WIKI_VENV"
  sudo -u app-user python3 -m venv "$WIKI_VENV"
  sudo -u app-user "$WIKI_VENV/bin/pip" install --upgrade pip >/dev/null
  sudo -u app-user "$WIKI_VENV/bin/pip" install mkdocs-material >/dev/null
fi
"$WIKI_VENV/bin/mkdocs" --version

# ── 2. Caddy package + config ─────────────────────────────────────────────
if ! command -v caddy >/dev/null; then
  log "installing caddy from Cloudsmith repo"
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl >/dev/null
  curl -fsSL 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main" \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -q >/dev/null
  apt-get install -y caddy
fi
caddy version

log "installing Caddyfile"
[ -f "$CADDYFILE_SRC" ] || err "missing $CADDYFILE_SRC (repo not checked out?)"
[ -f "$CADDYFILE_DST" ] && cp -a "$CADDYFILE_DST" "$CADDYFILE_DST.bak.$(date +%Y%m%d-%H%M%S)"
install -m 644 -o root -g root "$CADDYFILE_SRC" "$CADDYFILE_DST"
caddy validate --config "$CADDYFILE_DST" >/dev/null

# ── 3. tmpfiles.d lockfile directory ──────────────────────────────────────
log "installing tmpfiles.d lockfile dir"
[ -f "$TMPFILES_SRC" ] || err "missing $TMPFILES_SRC"
install -m 644 -o root -g root "$TMPFILES_SRC" "$TMPFILES_DST"
systemd-tmpfiles --create "$TMPFILES_DST" >/dev/null

# ── 4. First wiki build ───────────────────────────────────────────────────
log "running first wiki build"
sudo -u app-user bash "$REPO_ROOT/scripts/build-wiki-site.sh" >/dev/null

# ── 5. Enable + reload caddy ──────────────────────────────────────────────
log "enabling caddy service"
systemctl enable caddy >/dev/null
systemctl restart caddy
sleep 2
systemctl is-active caddy | grep -q active || err "caddy didn't come back up; see journalctl -u caddy"

log "installed — now point nginx-proxy-manager at http://$(hostname):8080"
log "  pages built: $(find "$REPO_ROOT/wiki-site/site" -name index.html 2>/dev/null | wc -l)"
log "  curl http://localhost:8080/ → $(curl -sI http://localhost:8080/ | head -1 | tr -d '\r')"
