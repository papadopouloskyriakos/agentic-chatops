# Eval Sets — 3-Set Model

Three evaluation sets following OpenAI best practices for LLM pipeline evaluation.
Split from the original `goldset-scenarios.json` (22 scenarios) into a regression/discovery/holdout model.

## Sets

### regression.json (22 scenarios)

**Purpose:** "Do not break" gate. Contains all original golden test scenarios (GS-01 to GS-10 positive + GS-N01 to GS-N12 negative controls). Every MR must pass these before merge.

**Run schedule:** Every MR (CI pipeline, `test` stage).

**Contents:** 10 positive controls (availability, kubernetes, network, storage, correlated, recovery, WAL, dev) + 12 negative controls (chat, off-topic, wrong prefix, injection, info query, stale, invalid severity, dedup, maintenance, ambiguous hostname, empty, malformed).

### discovery.json (20 scenarios)

**Purpose:** Find new failures. Synthetic edge cases covering categories not fully represented in regression. Used to discover prompt regressions and triage gaps before they hit production.

**Run schedule:** Weekly (cron, Sundays 04:00 UTC).

**Contents:** 3 availability + 3 kubernetes + 2 network + 2 storage + 2 certificate + 2 security + 2 correlated + 2 maintenance + 2 dev variants. All use realistic NL/GR hostnames.

### holdout.json (16 scenarios)

**Purpose:** Unbiased evaluation. These scenarios must NEVER be seen during prompt optimization, triage tuning, or few-shot example selection. They measure true generalization. Looking at holdout scenarios during optimization contaminates the set.

**Run schedule:** Monthly (1st of month, 04:00 UTC). Results reviewed manually.

**Contents:** 10 positive controls + 6 negative controls covering unique edge cases (Synology NAS, SeaweedFS, ClusterMesh, post-maintenance cooldown, XSS injection, decommissioned room, future timestamp, cross-site misroute, synthetic hostname).

## Promotion Rules

1. **Discovery failure found** -- When a discovery scenario reveals a bug, fix the underlying issue.
2. **After fix verified** -- Move the failing scenario from `discovery.json` into `regression.json` so it becomes a permanent gate. This prevents the same bug from reoccurring.
3. **Never promote from holdout** -- Holdout scenarios stay in holdout. If you need a similar test in regression, write a new variant.
4. **Regression growth** -- The regression set only grows. Never remove a scenario unless the feature it tests is fully decommissioned.

## How to Add New Scenarios

1. Pick the appropriate set:
   - **regression** -- For bugs you have fixed and want to gate on permanently.
   - **discovery** -- For new edge cases you want to test weekly.
   - **holdout** -- Only add here if you need unbiased evaluation of a new category. Keep it small.

2. Follow the JSON schema:
   ```json
   {
     "id": "XX-NN",
     "name": "Short descriptive name",
     "category": "availability|kubernetes|network|storage|certificate|security|correlated|maintenance|dev|negative-control",
     "site": "nl|gr",
     "payload": { ... },
     "expected": { ... }
   }
   ```

3. ID prefixes: `GS-` (regression original), `GS-N` (regression negative), `DS-` (discovery), `HS-` (holdout).

4. Use full site-prefixed hostnames (nl*, gr*). Never use short forms.

5. Validate JSON after editing:
   ```bash
   python3 -c "import json; json.load(open('scripts/eval-sets/discovery.json'))"
   ```

## Running

```bash
# Default: regression only (CI gate)
./scripts/golden-test-suite.sh

# Specific set
./scripts/golden-test-suite.sh --set discovery

# All sets (full evaluation)
./scripts/golden-test-suite.sh --set all

# Offline + specific set
./scripts/golden-test-suite.sh --offline --set holdout
```
