#!/bin/bash
# Hermetic test for scripts/renovate-presnapshot.sh — exercises engine→recipe dispatch, the
# high-risk/unknown fail-closed exits, and arg validation. All via --dry-run or pre-SSH exits,
# so NO network / no docker / no live guest is touched.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PS="$DIR/renovate-presnapshot.sh"
PASS=0; FAIL=0

# name  service  expected_exit  expect_restore_point(1|0)
chk(){
  local name="$1" svc="$2" exp="$3" wantrp="$4" out rc rp
  out=$(bash "$PS" --host nlexample01 --service "$svc" --dry-run 2>/dev/null); rc=$?
  rp=$(echo "$out" | grep -c '^RESTORE_POINT:' || true)
  if [ "$rc" -eq "$exp" ] && { [ "$wantrp" -eq 0 ] || [ "$rp" -ge 1 ]; }; then
    PASS=$((PASS+1)); printf 'PASS  %-34s exit=%s rp=%s\n' "$name" "$rc" "$rp"
  else FAIL=$((FAIL+1)); printf 'FAIL  %-34s got exit=%s rp=%s want exit=%s\n' "$name" "$rc" "$rp" "$exp"; fi; }

# dumpable engines → dry-run feasible → exit 0 + a RESTORE_POINT
chk "postgres → dump"        postgres         0 1
chk "pgvecto-rs → dump"      pgvecto-rs       0 1
chk "mariadb → dump"         mariadb          0 1
chk "mysql → dump"           mysql            0 1
chk "mongo → dump"           mongo            0 1
chk "redis → dump"           docker.io-redis  0 1
chk "actualbudget → tar"     actualbudget     0 1
chk "milvus → etcd+minio"    milvusdb-milvus  0 1
chk "meilisearch → data tar" getmeili-meilisearch 0 1
chk "etcd → etcdctl snapshot" quay-coreos-etcd 0 1
# generic data-volume-tar fallback → every OTHER stateful engine is now snapshot-able
chk "elasticsearch → generic" elasticsearch   0 1
chk "clickhouse → generic"   clickhouse       0 1
chk "influxdb → generic"     influxdb         0 1
chk "qdrant → generic"       qdrant           0 1
chk "minio → generic"        minio-minio      0 1
chk "youtrack app → generic" jetbrains-youtrack 0 1
# always-POLL (deliberate — secret-store migration is near-irreversible)
chk "openbao → always POLL"  openbao          6 0

# arg validation → exit 2
rc=0; bash "$PS" --host x 2>/dev/null || rc=$?
[ "$rc" -eq 2 ] && { PASS=$((PASS+1)); echo "PASS  missing --service → exit 2"; } || { FAIL=$((FAIL+1)); echo "FAIL  missing --service (got $rc)"; }

# invariant: a dumpable engine NEVER succeeds without emitting a RESTORE_POINT (no silent pass)
out=$(bash "$PS" --host h --service postgres --dry-run 2>/dev/null)
echo "$out" | grep -q '^RESTORE_POINT:' && { PASS=$((PASS+1)); echo "PASS  success always emits RESTORE_POINT"; } || { FAIL=$((FAIL+1)); echo "FAIL  no RESTORE_POINT on success"; }

echo; echo "$((PASS+FAIL)) checks, $FAIL failure(s)"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
