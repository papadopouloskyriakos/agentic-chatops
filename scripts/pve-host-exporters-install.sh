#!/usr/bin/env bash
# =============================================================================
# pve-host-exporters-install.sh — idempotent installer + drift-check for the
# two Prometheus exporters that run natively on every live PVE host:
#
#   prometheus-pve-exporter  :9221  (PyPI, pinned, venv /opt/prometheus-pve-exporter,
#                                    API token prometheus@pve!pve-exporter, PVEAuditor)
#   prometheus-node-exporter :9100  (Debian package, PSI + zfs + textfile collectors)
#
# Both bind the host's inside_mgmt (VLAN 10 / 10.0.181.X/24 on NL,
# 10.0.X.X/24 on GR) address only. NL Prometheus scrapes them via the
# `pve-exporter` (/pve?cluster=1&node=0) + `pve-node-exporter` jobs in
# infrastructure/nl/production/k8s/namespaces/monitoring/scrape-estate.tf.
#
# Runs ON the PVE host as root (streamed over SSH, nothing to copy):
#
#   install:  ssh root@<host> "PVE_EXPORTER_TOKEN='$(cat ~/.config/gateway/pve-exporter.token)' bash -s -- install" \
#                 < scripts/pve-host-exporters-install.sh
#   check:    ssh root@<host> 'bash -s -- --check' < scripts/pve-host-exporters-install.sh
#
# `install` is safe to re-run (token only rewritten when PVE_EXPORTER_TOKEN is
# set). `--check` is read-only and exits 1 on any drift — the drift-check idiom
# of scripts/check-zfs-dio-disabled.sh.
#
# Deliberately NOT enabled pve-exporter collectors: config (walks every guest
# config = one pmxcfs read per guest, ~200 on this cluster), replication,
# subscription, qdevice (none in use). See docs/runbooks/pve-host-exporters.md.
# =============================================================================
set -euo pipefail

PVE_EXPORTER_VERSION="${PVE_EXPORTER_VERSION:-3.10.0}"
PVE_API_USER="${PVE_API_USER:-prometheus@pve}"
PVE_API_TOKEN_NAME="${PVE_API_TOKEN_NAME:-pve-exporter}"
VENV=/opt/prometheus-pve-exporter
CONF_DIR=/etc/prometheus
CONF="$CONF_DIR/pve.yml"
UNIT=/etc/systemd/system/prometheus-pve-exporter.service
NE_DEFAULT=/etc/default/prometheus-node-exporter
NE_TEXTFILE_DIR=/var/lib/prometheus/node-exporter
SVC_USER=pve-exporter

MODE="${1:-install}"
case "$MODE" in install|--check|check) ;; *) echo "usage: $0 [install|--check]" >&2; exit 2 ;; esac
[ "$MODE" = "check" ] && MODE=--check

log()  { printf '[%s] %s\n' "$(hostname)" "$*"; }
fail() { printf '[%s] FAIL: %s\n' "$(hostname)" "$*" >&2; FAILED=1; }
FAILED=0

# --- mgmt IP: the host's own /etc/hosts entry (PVE requires it) must be on an interface
BIND_IP="${BIND_IP:-$(getent ahostsv4 "$(hostname)" | awk 'NR==1{print $1}')}"
case "$BIND_IP" in 192.168.181.*|192.168.2.*) ;; *) echo "refusing to bind $BIND_IP — not an inside_mgmt address" >&2; exit 2 ;; esac
ip -4 -br addr | grep -q " $BIND_IP/" || { echo "$BIND_IP is not configured on any interface" >&2; exit 2; }

if [ "$MODE" = "install" ]; then
  [ "$(id -u)" = 0 ] || { echo "must run as root" >&2; exit 2; }
  export DEBIAN_FRONTEND=noninteractive

  # --- packages (no recommends: the node-exporter-collectors cron scripts are not wanted on PVE)
  apt-get update -qq >/dev/null 2>&1 || log "apt-get update reported errors (enterprise repo?) — continuing"
  apt-get install -y -qq --no-install-recommends python3-venv prometheus-node-exporter >/dev/null
  log "packages: python3-venv, prometheus-node-exporter $(dpkg-query -W -f='${Version}' prometheus-node-exporter)"

  # --- stray unit-less node_exporter (seen on nlpve04: /usr/local/bin/node_exporter, no unit)
  for pid in $(pgrep -f '^/usr/local/bin/node_exporter' || true); do
    log "killing stray unit-less node_exporter pid $pid ($(tr '\0' ' ' </proc/$pid/cmdline))"
    kill "$pid" || true
  done

  # --- service account
  id -u "$SVC_USER" >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$SVC_USER"

  # --- venv + pinned exporter
  [ -x "$VENV/bin/python3" ] || python3 -m venv "$VENV"
  have="$("$VENV/bin/pip" show prometheus-pve-exporter 2>/dev/null | awk '/^Version:/{print $2}' || true)"
  if [ "$have" != "$PVE_EXPORTER_VERSION" ]; then
    "$VENV/bin/pip" install -q --disable-pip-version-check "prometheus-pve-exporter==$PVE_EXPORTER_VERSION"
  fi
  log "prometheus-pve-exporter $("$VENV/bin/pip" show prometheus-pve-exporter | awk '/^Version:/{print $2}') in $VENV"

  # --- API token config (0640 root:pve-exporter; only (re)written when a token is supplied)
  install -d -m 0755 "$CONF_DIR"
  if [ -n "${PVE_EXPORTER_TOKEN:-}" ]; then
    umask 027
    cat > "$CONF" <<EOF
# prometheus-pve-exporter — managed by claude-gateway scripts/pve-host-exporters-install.sh
# Token: ${PVE_API_USER}!${PVE_API_TOKEN_NAME} (PVEAuditor at /, privsep). Rotate: pveum user token remove/add + re-run install.
default:
  user: ${PVE_API_USER}
  token_name: ${PVE_API_TOKEN_NAME}
  token_value: ${PVE_EXPORTER_TOKEN}
  verify_ssl: false
EOF
    chown root:"$SVC_USER" "$CONF"; chmod 0640 "$CONF"
    log "wrote $CONF"
  elif [ ! -s "$CONF" ]; then
    echo "no $CONF and PVE_EXPORTER_TOKEN not set — cannot install" >&2; exit 2
  fi

  # --- pve-exporter unit
  cat > "$UNIT" <<EOF
# managed by claude-gateway scripts/pve-host-exporters-install.sh
[Unit]
Description=Prometheus PVE exporter (${BIND_IP}:9221)
Documentation=https://github.com/prometheus-pve/prometheus-pve-exporter
After=network-online.target pve-cluster.service pvedaemon.service pveproxy.service
Wants=network-online.target

[Service]
User=${SVC_USER}
Group=${SVC_USER}
ExecStart=${VENV}/bin/pve_exporter --config.file ${CONF} --web.listen-address ${BIND_IP}:9221 \\
  --no-collector.config --no-collector.replication --no-collector.subscription --no-collector.qdevice
Restart=on-failure
RestartSec=10
MemoryMax=256M
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes

[Install]
WantedBy=multi-user.target
EOF

  # --- node_exporter args (Debian unit reads ARGS from /etc/default)
  install -d -m 0755 -o root -g root "$NE_TEXTFILE_DIR"
  cat > "$NE_DEFAULT" <<EOF
# managed by claude-gateway scripts/pve-host-exporters-install.sh
# PSI (pressure), zfs, filesystem, meminfo, loadavg collectors are on by default in 1.9.x.
ARGS="--web.listen-address=${BIND_IP}:9100 --collector.textfile.directory=${NE_TEXTFILE_DIR} --collector.systemd --collector.processes"
EOF

  systemctl daemon-reload
  systemctl enable --now prometheus-pve-exporter.service >/dev/null 2>&1
  systemctl restart prometheus-pve-exporter.service
  systemctl enable --now prometheus-node-exporter.service >/dev/null 2>&1
  systemctl restart prometheus-node-exporter.service
  sleep 3
fi

# =============================================================================
# verification (both modes)
# =============================================================================
for svc in prometheus-pve-exporter prometheus-node-exporter; do
  if systemctl is-active --quiet "$svc"; then log "$svc active"; else fail "$svc not active"; fi
  systemctl is-enabled --quiet "$svc" || fail "$svc not enabled"
done
[ "$("$VENV/bin/pip" show prometheus-pve-exporter 2>/dev/null | awk '/^Version:/{print $2}')" = "$PVE_EXPORTER_VERSION" ] || fail "pve-exporter version != $PVE_EXPORTER_VERSION"
[ "$(stat -c '%a %U:%G' "$CONF" 2>/dev/null)" = "640 root:$SVC_USER" ] || fail "$CONF perms/owner drift ($(stat -c '%a %U:%G' "$CONF" 2>/dev/null))"
ss -ltn 2>/dev/null | grep -q "$BIND_IP:9221 " || fail "nothing listening on $BIND_IP:9221"
ss -ltn 2>/dev/null | grep -q "$BIND_IP:9100 " || fail "nothing listening on $BIND_IP:9100"
if ss -ltn 2>/dev/null | grep -qE '(\*|0\.0\.0\.0|\[::\]):(9100|9221) '; then fail "an exporter is bound to all interfaces"; fi

# NOTE: in pve-exporter 3.x status/version/node/resources/backup-info are all
# "cluster collectors" (url param cluster=1); the "node collectors" (node=1) are
# only config/replication/subscription — all deliberately disabled here. So the
# scrape URL is /pve?cluster=1&node=0 and every host reports the whole cluster
# (rules dedup with max by (id); per-host scrape_duration = that host's API health).
cl_m="$(curl -sf -m 25 "http://$BIND_IP:9221/pve?cluster=1&node=0" || true)"
grep -q '^pve_node_info' <<<"$cl_m" || fail "pve-exporter returned no pve_node_info (token/ACL?)"
grep -q "name=\"$(hostname)\"" <<<"$cl_m" || fail "pve-exporter: no pve_node_info row for this node"
grep -q '^pve_version_info' <<<"$cl_m" || fail "pve-exporter: no pve_version_info"
cl_n="$(grep -c '^pve_up{' <<<"$cl_m" || true)"
[ "${cl_n:-0}" -ge 10 ] || fail "pve-exporter cluster collector returned only ${cl_n:-0} pve_up series"
grep -q '^pve_not_backed_up_total' <<<"$cl_m" || fail "pve-exporter: backup-info collector missing"
ne_m="$(curl -sf -m 10 "http://$BIND_IP:9100/metrics" || true)"
grep -q '^node_pressure_io_waiting_seconds_total' <<<"$ne_m" || fail "node_exporter: no PSI (node_pressure_*) series"
grep -q '^node_memory_MemAvailable_bytes' <<<"$ne_m" || fail "node_exporter: no node_memory_* series"

if [ "$FAILED" = 0 ]; then
  log "PASS — pve-exporter $PVE_EXPORTER_VERSION on $BIND_IP:9221 (cluster pve_up series: $cl_n), node_exporter on $BIND_IP:9100"
  exit 0
else
  log "DRIFT/FAILURE detected"
  exit 1
fi
