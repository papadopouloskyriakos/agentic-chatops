#!/bin/bash
# codegraph-lookup.sh — Query code graph database via SSH to claude-runner
# Usage: codegraph-lookup.sh <callers|callees|search|deadcode> <function_name|keyword|repo>
set -euo pipefail

COMMAND="${1:-}"
ARG="${2:-}"
if [ -z "$COMMAND" ] || [ -z "$ARG" ]; then
  echo "Usage: codegraph-lookup.sh <callers|callees|search|deadcode> <function_name|keyword|repo>"
  exit 1
fi

REMOTE="claude-runner@nl-claude01"
CGC_VENV="/home/claude-runner/.cgc-venv"

# Sanitize ARG (prevent injection)
ARG=$(echo "$ARG" | tr -d "'\"\`" | head -c 100)

case "$COMMAND" in
  callers)
    QUERY="MATCH (caller:Function)-[:CALLS]->(target:Function) WHERE target.name CONTAINS '${ARG}' RETURN caller.name, caller.path LIMIT 20"
    ;;
  callees)
    QUERY="MATCH (source:Function)-[:CALLS]->(callee:Function) WHERE source.name CONTAINS '${ARG}' RETURN callee.name, callee.path LIMIT 20"
    ;;
  search)
    QUERY="MATCH (f:Function) WHERE f.name CONTAINS '${ARG}' OR f.path CONTAINS '${ARG}' RETURN f.name, f.path, f.lang LIMIT 20"
    ;;
  deadcode)
    QUERY="MATCH (f:Function) WHERE NOT ()-[:CALLS]->(f) AND f.path CONTAINS '${ARG}' RETURN f.name, f.path LIMIT 20"
    ;;
  *)
    echo "Unknown command: $COMMAND. Use: callers, callees, search, deadcode"
    exit 1
    ;;
esac

RESULTS=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes \
  -i ~/.ssh/one_key "$REMOTE" \
  "source $CGC_VENV/bin/activate 2>/dev/null; python3 -c \"
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'cgcpassword123'))
with d.session() as s:
    for r in s.run('''$QUERY'''):
        print('|'.join(str(v) for v in r.values()))
d.close()
\" 2>/dev/null") || true

if [ -z "$RESULTS" ]; then
  echo "No results for '$COMMAND $ARG'. Data may be stale (reindex every 2h)."
  echo "Try: Grep/Glob in the repo for recent changes."
  exit 0
fi

echo "=== CodeGraph: $COMMAND '$ARG' ==="
echo ""
echo "$RESULTS"
echo ""
echo "Found $(echo "$RESULTS" | wc -l) result(s). Note: data can be up to 2h stale."
