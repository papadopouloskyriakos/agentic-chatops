---
name: codegraph-lookup
description: Query code graph database for function callers, callees, dependencies, and dead code in CubeOS and MeshSat repos.
allowed-tools: Bash
metadata:
  openclaw:
    always: true
---

# CodeGraph Lookup

Query the code graph database (Neo4j) for code relationships.

## WHEN to use
- "what calls function X?" / "who calls Y?"
- "what does function Z depend on?"
- "find dead code in module W"
- Code structure questions about CubeOS or MeshSat

## HOW to use

```bash
./skills/codegraph-lookup/codegraph-lookup.sh callers <function_name>
./skills/codegraph-lookup/codegraph-lookup.sh callees <function_name>
./skills/codegraph-lookup/codegraph-lookup.sh search <keyword>
./skills/codegraph-lookup/codegraph-lookup.sh deadcode [repo_name]
```

## RULES
1. Data can be up to 2h stale (reindex runs every 2h).
2. CGC parses Go and Python. Kotlin (MeshSat Android) has limited coverage.
3. If CGC returns 0 results, the code may exist but not be indexed yet — fall back to Grep.
