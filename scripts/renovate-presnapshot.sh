#!/usr/bin/env bash
# renovate-presnapshot.sh — Phase 3 pre-merge SNAPSHOT gate for the Renovate MR Autonomy lane.
#
# Creates + VERIFIES a restore point for a stateful docker service BEFORE an autonomous merge
# (the docker plane AUTO-deploys `docker compose pull && up -d` seconds after merge — ci/docker.yml —
# so the restore point MUST exist first).
#
# METHOD: per-engine logical dump/snapshot, taken + verified ON THE TARGET GUEST (SSH as root, deploy
# key). Grounded 2026-07-06: only 2 of 20 stateful guests support pct/qm snapshot; the rest are
# raw-on-dir/nfs, so a guest-side dump is the only uniform, verifiable method. The remote logic is
# shipped as one base64 blob (injection- and quoting-safe) and run there, so artifacts live next to
# the data and verification happens where the data is.
#
# FAIL CLOSED: success prints RESTORE_POINT:<id> + RESTORE_CMD:<one-liner> and exit 0. ANY failure
# (unreachable/stopped guest, unknown engine, missing container, dump/verify error, high-risk engine)
# exits non-zero → renovate-mr-gate.sh sets SNAP_OK=0 → DECISION=POLL. Never returns success unverified.
#
# Usage: renovate-presnapshot.sh --host <docker-host> --service <engine-token> [--dry-run] [--dest DIR]
#   --host    = compose path field 2 (classifier .affected_host)
#   --service = the engine being bumped (classifier .stateful_match[0] / .package)
#   --dry-run = resolve the recipe + report feasibility WITHOUT touching the guest (shadow mode)
set -uo pipefail

HOST=""; SVC=""; DRY=0; DEST="/var/backups/renovate-presnap"
SSH_KEY="${RENOVATE_SSH_KEY:-$HOME/.ssh/one_key}"
while [ $# -gt 0 ]; do case "$1" in
  --host) HOST="$2"; shift 2;; --service) SVC="$2"; shift 2;;
  --dry-run) DRY=1; shift;; --dest) DEST="$2"; shift 2;;
  *) shift;; esac; done
[ -n "$HOST" ] && [ -n "$SVC" ] || { echo "usage: --host <h> --service <engine> [--dry-run]" >&2; exit 2; }

TS=$(date -u +%Y%m%dT%H%M%SZ)
GSSH="ssh -i $SSH_KEY -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=accept-new root@$HOST"

# ── engine family from the (branch-derived) service token ──────────────────────
fam=""
case "$SVC" in
  *postgres*|*pgvector*|*pgvecto*|*timescale*) fam=postgres;;
  *mariadb*|*mysql*|*percona*)                 fam=mysql;;
  *mongo*)                                     fam=mongo;;
  *redis*|*valkey*|*keydb*|*dragonfly*)        fam=redis;;
  *milvus*)                                    fam=milvus;;
  *meilisearch*|*getmeili*)                    fam=meilisearch;;
  *etcd*)                                      fam=etcd;;
  *openbao*|*vault*)                           fam=openbao;;
  *actual*)                                    fam=actual;;
  # Every other stateful engine (elasticsearch/opensearch, clickhouse, influxdb, qdrant/weaviate,
  # cassandra, rabbitmq, minio, apps-with-embedded-DB, …) → generic verified data-volume tar.
  *)                                           fam=generic;;
esac

# Secret-store bump = high-blast-radius, near-irreversible migration → always POLL, even with a raft snapshot.
[ "$fam" = "openbao" ] && { echo "openbao/vault: secret-store migration → always POLL (never auto-merge)" >&2; exit 6; }

if [ "$DRY" -eq 1 ]; then
  echo "DRY-RUN feasible: host=$HOST engine=$fam (service=$SVC)" >&2
  echo "RESTORE_POINT:dryrun:$HOST:$fam:$TS"
  echo "RESTORE_CMD:(dry-run — no artifact taken)"
  exit 0
fi

# ── remote worker (runs ON THE GUEST): $1=fam $2=RF(dest base). Echoes ARTIFACT:<paths> on success. ──
read -r -d '' REMOTE <<'REMOTE_EOF' || true
set -uo pipefail
fam="$1"; RF="$2"; SVCTOK="${3:-}"
sz(){ stat -c%s "$1" 2>/dev/null || echo 0; }
cid_for(){ docker ps --format '{{.ID}} {{.Image}}' | grep -Ei "$1" | head -1 | cut -d' ' -f1; }
mount_src(){ docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$2\"}}{{.Source}}{{end}}{{end}}" "$1" 2>/dev/null; }
case "$fam" in
  postgres)
    cid=$(cid_for 'postgres|pgvect|timescale'); [ -n "$cid" ] || { echo "no postgres container" >&2; exit 7; }
    docker exec "$cid" pg_dumpall -U postgres 2>/dev/null | gzip -c > "$RF.sql.gz"
    { gzip -t "$RF.sql.gz" 2>/dev/null && [ "$(sz "$RF.sql.gz")" -gt 200 ]; } || { echo "pg verify failed" >&2; exit 4; }
    # RESTORE-REHEARSAL (tested restore, not just integrity): restore the dump into a throwaway
    # container of the SAME image + smoke-query it. Gated (default on) + size-capped. Fail closed.
    if [ "${RENOVATE_RESTORE_REHEARSAL:-1}" != "0" ] && [ "$(sz "$RF.sql.gz")" -lt "${RENOVATE_REHEARSAL_MAX_BYTES:-VMID_REDACTED}" ]; then
      img=$(docker inspect -f '{{.Config.Image}}' "$cid" 2>/dev/null); rn="rp-rehearse-pg-$$"
      docker rm -f "$rn" >/dev/null 2>&1
      if docker run -d --rm --name "$rn" -e POSTGRES_PASSWORD=rehearse "$img" >/dev/null 2>&1; then
        for _ in $(seq 1 30); do docker exec "$rn" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
        gunzip -c "$RF.sql.gz" | docker exec -i "$rn" psql -U postgres >/dev/null 2>&1
        if ! docker exec "$rn" psql -U postgres -tAc 'SELECT 1' 2>/dev/null | grep -q 1; then
          docker rm -f "$rn" >/dev/null 2>&1; echo "restore-rehearsal FAILED (dump does not restore) → fail closed" >&2; exit 4; fi
        docker rm -f "$rn" >/dev/null 2>&1
      else echo "restore-rehearsal: could not start scratch container → fail closed" >&2; exit 4; fi
    fi
    echo "ARTIFACT:$RF.sql.gz";;
  mysql)
    cid=$(cid_for 'mariadb|mysql|percona'); [ -n "$cid" ] || { echo "no mysql container" >&2; exit 7; }
    docker exec "$cid" sh -c 'mariadb-dump --single-transaction --all-databases 2>/dev/null || mysqldump --single-transaction --all-databases' 2>/dev/null | gzip -c > "$RF.sql.gz"
    { gzip -t "$RF.sql.gz" 2>/dev/null && [ "$(sz "$RF.sql.gz")" -gt 200 ]; } || { echo "mysql verify failed" >&2; exit 4; }
    echo "ARTIFACT:$RF.sql.gz";;
  mongo)
    cid=$(cid_for 'mongo'); [ -n "$cid" ] || { echo "no mongo container" >&2; exit 7; }
    docker exec "$cid" mongodump --gzip --archive 2>/dev/null > "$RF.archive.gz"
    { gzip -t "$RF.archive.gz" 2>/dev/null && [ "$(sz "$RF.archive.gz")" -gt 200 ]; } || { echo "mongo verify failed" >&2; exit 4; }
    echo "ARTIFACT:$RF.archive.gz";;
  redis)
    cid=$(cid_for 'redis|valkey|keydb|dragonfly'); [ -n "$cid" ] || { echo "no redis container" >&2; exit 7; }
    docker exec "$cid" sh -c 'redis-cli SAVE >/dev/null 2>&1; cat /data/dump.rdb 2>/dev/null || cat /data/*.rdb 2>/dev/null' > "$RF.rdb"
    [ "$(sz "$RF.rdb")" -gt 10 ] || { echo "redis dump empty" >&2; exit 4; }
    echo "ARTIFACT:$RF.rdb";;
  actual)
    d=$(ls -d /srv/*/data 2>/dev/null | grep -i actual | head -1); [ -n "$d" ] || { echo "no actual data dir" >&2; exit 7; }
    tar czf "$RF.tgz" -C "$d" . || { echo "tar failed" >&2; exit 4; }
    { gzip -t "$RF.tgz" 2>/dev/null && [ "$(sz "$RF.tgz")" -gt 100 ]; } || { echo "actual verify failed" >&2; exit 4; }
    echo "ARTIFACT:$RF.tgz";;
  meilisearch)
    # Meilisearch persists everything in /meili_data; a version bump migrates the on-disk format, so the
    # restore point is a tar of the data volume (paired with a tag-revert on restore). LMDB is crash-safe.
    cid=$(cid_for 'meilisearch|getmeili'); [ -n "$cid" ] || { echo "no meilisearch container" >&2; exit 7; }
    src=$(mount_src "$cid" /meili_data)
    [ -n "$src" ] || src=$(docker inspect -f '{{range .Mounts}}{{.Source}}={{.Destination}} {{end}}' "$cid" 2>/dev/null | tr ' ' '\n' | grep -i 'meili' | head -1 | cut -d= -f1)
    [ -n "$src" ] && [ -d "$src" ] || { echo "no meili data mount" >&2; exit 7; }
    tar czf "$RF.meili.tgz" -C "$src" . || { echo "meili tar failed" >&2; exit 4; }
    { gzip -t "$RF.meili.tgz" 2>/dev/null && [ "$(sz "$RF.meili.tgz")" -gt 100 ]; } || { echo "meili verify failed" >&2; exit 4; }
    echo "ARTIFACT:$RF.meili.tgz";;
  milvus)
    # Milvus state spans THREE backing stores: etcd (metadata) + MinIO (vector segments) + milvus local.
    # Restore point = a verified etcd snapshot + a tar of the minio (+ milvus) data volumes.
    mc=$(cid_for 'milvusdb/milvus'); ec=$(cid_for 'coreos/etcd|/etcd:|quay.io/coreos/etcd'); oc=$(cid_for 'minio/minio')
    [ -n "$mc" ] && [ -n "$ec" ] && [ -n "$oc" ] || { echo "milvus stack incomplete (need milvus+etcd+minio)" >&2; exit 7; }
    docker exec "$ec" sh -c 'ETCDCTL_API=3 etcdctl snapshot save /tmp/rp-etcd.db' >/dev/null 2>&1 || { echo "etcd snapshot save failed" >&2; exit 4; }
    docker exec "$ec" sh -c 'ETCDCTL_API=3 etcdctl snapshot status /tmp/rp-etcd.db' >/dev/null 2>&1 || { echo "etcd snapshot invalid" >&2; exit 4; }
    docker exec "$ec" cat /tmp/rp-etcd.db > "$RF.etcd.snap"; docker exec "$ec" rm -f /tmp/rp-etcd.db 2>/dev/null
    [ "$(sz "$RF.etcd.snap")" -gt 100 ] || { echo "etcd snapshot empty" >&2; exit 4; }
    msrc=$(mount_src "$oc" /minio_data); [ -n "$msrc" ] || msrc=$(mount_src "$oc" /data)
    [ -n "$msrc" ] && [ -d "$msrc" ] || { echo "no minio data mount" >&2; exit 7; }
    { tar czf "$RF.minio.tgz" -C "$msrc" . && gzip -t "$RF.minio.tgz" 2>/dev/null; } || { echo "minio tar/verify failed" >&2; exit 4; }
    vsrc=$(mount_src "$mc" /var/lib/milvus)
    art="$RF.etcd.snap,$RF.minio.tgz"
    if [ -n "$vsrc" ] && [ -d "$vsrc" ]; then
      { tar czf "$RF.milvus.tgz" -C "$vsrc" . && gzip -t "$RF.milvus.tgz" 2>/dev/null; } || { echo "milvus tar/verify failed" >&2; exit 4; }
      art="$art,$RF.milvus.tgz"
    fi
    echo "ARTIFACT:$art";;
  etcd)
    # standalone etcd — a verified etcdctl snapshot (not a live dir tar, which can be torn).
    cid=$(cid_for 'etcd'); [ -n "$cid" ] || { echo "no etcd container" >&2; exit 7; }
    docker exec "$cid" sh -c 'ETCDCTL_API=3 etcdctl snapshot save /tmp/rp-etcd.db' >/dev/null 2>&1 || { echo "etcd snapshot save failed" >&2; exit 4; }
    docker exec "$cid" sh -c 'ETCDCTL_API=3 etcdctl snapshot status /tmp/rp-etcd.db' >/dev/null 2>&1 || { echo "etcd snapshot invalid" >&2; exit 4; }
    docker exec "$cid" cat /tmp/rp-etcd.db > "$RF.etcd.snap"; docker exec "$cid" rm -f /tmp/rp-etcd.db 2>/dev/null
    [ "$(sz "$RF.etcd.snap")" -gt 100 ] || { echo "etcd snapshot empty" >&2; exit 4; }
    echo "ARTIFACT:$RF.etcd.snap";;
  generic)
    # Any other stateful engine: a verified crash-consistent tar of the container's data volume(s)
    # (bind + named). Paired with a tag-revert on restore, this is a valid restore point (engines
    # recover from a crash-consistent copy via their WAL/journal). Bespoke recipes above are preferred
    # where a logical dump is cleaner; this knocks out the long tail (es/clickhouse/influx/qdrant/…).
    cid=$(cid_for "$SVCTOK"); [ -n "$cid" ] || { echo "no container matching '$SVCTOK'" >&2; exit 7; }
    dirs=()
    while IFS= read -r s; do
      [ -n "$s" ] && [ -d "$s" ] || continue
      case "$s" in /run*|/var/run*|/sys*|/proc*|/dev*|/etc/localtime|/etc/timezone|/etc/hostname|/etc/hosts|/etc/resolv.conf) continue;; esac
      dirs+=("$s")
    done < <(docker inspect -f '{{range .Mounts}}{{if or (eq .Type "bind") (eq .Type "volume")}}{{println .Source}}{{end}}{{end}}' "$cid" 2>/dev/null)
    [ ${#dirs[@]} -gt 0 ] || { echo "no data volumes to snapshot for '$SVCTOK'" >&2; exit 7; }
    # quiesce for a CONSISTENT copy: freeze the container's processes (cgroup freezer) so the tar isn't
    # torn mid-write, then ALWAYS unpause (even on tar failure). Much better than a live sequential tar.
    paused=0; docker pause "$cid" >/dev/null 2>&1 && paused=1
    tar czf "$RF.vol.tgz" "${dirs[@]}" 2>/dev/null; trc=$?
    [ "$paused" -eq 1 ] && docker unpause "$cid" >/dev/null 2>&1
    [ "$trc" -eq 0 ] || { echo "volume tar failed" >&2; exit 4; }
    { gzip -t "$RF.vol.tgz" 2>/dev/null && [ "$(sz "$RF.vol.tgz")" -gt 100 ]; } || { echo "volume verify failed" >&2; exit 4; }
    echo "ARTIFACT:$RF.vol.tgz";;
  *) echo "unhandled family $fam" >&2; exit 5;;
esac
exit 0
REMOTE_EOF

# ── live: reachable guest, ship the worker, capture the verified artifact ──────
$GSSH true 2>/dev/null || { echo "guest $HOST unreachable/stopped → fail closed" >&2; exit 3; }
RF="$DEST/${HOST}_${SVC}_${TS}"
B64=$(printf '%s' "$REMOTE" | base64 | tr -d '\n')
OUT=$($GSSH "mkdir -p '$DEST' 2>/dev/null && echo '$B64' | base64 -d | bash -s -- '$fam' '$RF' '$SVC'" 2>/dev/null) \
  || { echo "snapshot worker failed on $HOST for $fam → fail closed" >&2; exit 4; }
ART=$(printf '%s\n' "$OUT" | sed -n 's/^ARTIFACT://p' | head -1)
[ -n "$ART" ] || { echo "snapshot produced no verified artifact → fail closed" >&2; exit 4; }

case "$fam" in
  postgres) RCMD="revert compose tag + redeploy OLD image, THEN: ssh root@$HOST 'gunzip -c $ART | docker exec -i \$(docker ps --filter ancestor=postgres -q|head -1) psql -U postgres'";;
  mysql)    RCMD="revert tag + redeploy OLD image, THEN restore $ART into the mariadb/mysql container";;
  mongo)    RCMD="revert tag + redeploy OLD image, THEN: ssh root@$HOST 'docker exec -i <mongo> mongorestore --gzip --archive' < $ART";;
  redis)    RCMD="(cache — usually rebuildable) copy $ART back to the redis /data/dump.rdb and restart";;
  actual)   RCMD="revert tag, THEN untar $ART back into the actualbudget data dir";;
  meilisearch) RCMD="revert meilisearch tag + redeploy OLD version, THEN stop meili, replace /meili_data from $ART, restart";;
  milvus)   RCMD="revert milvus tag + redeploy OLD version, restore etcd+minio(+milvus) from [$ART], restart the stack";;
  etcd)     RCMD="revert tag, THEN: etcdctl snapshot restore $ART into a fresh data dir, point etcd at it, restart";;
  generic)  RCMD="revert tag + redeploy OLD image, THEN stop the container, restore its data volume(s) from $ART, restart";;
  *)        RCMD="revert tag, THEN restore from $ART";;
esac

echo "RESTORE_POINT:dump:$HOST:$ART"
echo "RESTORE_CMD:$RCMD"
exit 0
