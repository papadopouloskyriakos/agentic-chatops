# Runbook — Preference-iterating prompt patcher

**YT:** [IFRNLLEI01PRD-645](https://youtrack.example.net/issue/IFRNLLEI01PRD-645)
**Status:** Live on `nl-claude01` since 2026-04-20.

## What it is

Replaces the single-shot `prompt-improver.py` flow with an **N-candidate A/B
trial framework** for auto-generated prompt patches. When a (surface,
dimension) pair's 30-day score drops below threshold, the system generates
3 candidate instruction variants (concise / detailed / examples), assigns
each future matching session to one arm (candidates + a no-patch control),
runs a one-sided Welch t-test after every arm reaches 15 samples, and
promotes the winner to `config/prompt-patches.json` only if it beats the
control by ≥ 0.05 points with p < 0.1. Prompt-level policy iteration — no
model weights are ever fine-tuned.

## Architecture

```
┌────────────────────────────┐       ┌──────────────────────────────────┐
│ prompt-patch-trial.py      │       │ Runner: Query Knowledge SSH node │
│ --analyze | --start        │       │ emits PROMPT_PATCHES + new       │
│ (manual or cron)           │       │ PROMPT_TRIAL_INSTRUCTIONS lines  │
└───────────────┬────────────┘       └─────────────────┬────────────────┘
                │                                      │
                │ start_trial()                        │ prompt-trial-assign.py
                │ 3 candidates                         │ --issue X --surface S
                ▼                                      ▼
       ┌───────────────────────┐              ┌─────────────────────────┐
       │ prompt_patch_trial    │◀─── record ──│ assign_and_record() via │
       │ (status='active',     │              │ deterministic hash      │
       │  candidates_json[])   │              └─────────────────────────┘
       └──────────┬────────────┘                        │
                  │                                     ▼
                  │                         ┌───────────────────────────┐
                  │                         │ session_trial_assignment  │
                  │                         │ (issue_id, trial_id,      │
                  │                         │  variant_idx)             │
                  │                         └───────────────────────────┘
                  │
                  │                         ┌───────────────────────────┐
                  │                         │ session_judgment          │
                  │                         │ (per-dim scores)          │
                  │                         └──────────────┬────────────┘
                  ▼                                        │
       ┌──────────────────────┐                            │
       │ finalize-prompt-     │◀── join, Welch t-test ─────┘
       │ trials.py            │
       │ (daily cron 03:17)   │                 ┌───────────────────────┐
       └──────────┬───────────┘                 │ config/               │
                  │                             │ prompt-patches.json   │
                  └── if winner ──────────────▶│ (existing reader path)│
                                               └───────────────────────┘
```

## Enable / disable

```bash
# Start trials (one-off, manual) — requires the feature flag:
PROMPT_TRIAL_ENABLED=1 scripts/prompt-patch-trial.py --start

# Preview without writing anything:
scripts/prompt-patch-trial.py --analyze
scripts/prompt-patch-trial.py --start --dry-run
```

The Runner's Query Knowledge node always calls `prompt-trial-assign.py` —
if no trials are active, the helper emits `[]` and Build Prompt falls
through to the legacy `PROMPT_PATCHES` path. There is nothing to "turn on"
inside the n8n workflow; the flag only gates trial creation.

## Observe

```bash
# List active trials.
cd scripts && python3 -m lib.prompt_patch_trial list

# Detail for one trial (includes per-arm score means + counts):
cd scripts && python3 -m lib.prompt_patch_trial get --id 7

# Prometheus metrics (emitted every 10 min):
curl -s http://nl-claude01:9100/metrics | grep prompt_trial
```

Grafana: the `ChatOps Platform Performance` dashboard gained a new panel
"Prompt patch trials" with `prompt_trials_active`, `prompt_trials_completed_total`,
`prompt_trials_aborted_total`, `prompt_trial_winner_lift` stacked.

## Finalize (manual)

```bash
# Dry-run finalizer on every active trial (no DB writes):
scripts/finalize-prompt-trials.py --dry-run --json

# Real run (also sweeps timed-out trials first):
scripts/finalize-prompt-trials.py

# Finalize one trial by id:
cd scripts && python3 -m lib.prompt_patch_trial finalize --id 7
```

The cron entry on `nl-claude01` runs `finalize-prompt-trials.py` daily at
03:17 UTC. Output goes to `/tmp/prompt-trial-finalize.log`.

## Rollback a winner

If a promoted patch turns out to make things worse:

```bash
# 1. Find the patches file entry.
jq '.[] | select(.source and (.source | startswith("trial:")))' \
  config/prompt-patches.json

# 2. Mark it inactive. Safest via Python — preserves ordering:
python3 -c "
import json, sys, datetime
p = json.load(open('config/prompt-patches.json'))
for entry in p:
    if entry.get('source', '').startswith('trial:TRIAL_ID:'):
        entry['active'] = False
        entry['deactivated_at'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        entry['deactivated_reason'] = 'operator rollback'
json.dump(p, open('config/prompt-patches.json','w'), indent=2)
"

# 3. Kick off a new trial for the same dim to let the system try again.
#    (Or leave the dim unpatched — the control arm was fine.)
PROMPT_TRIAL_ENABLED=1 scripts/prompt-patch-trial.py --start
```

Rollback does **not** auto-restart the same candidates — the candidate pool
is hand-authored in `scripts/prompt-patch-trial.py`, so edit it first if
you want different variants.

## Abort an active trial

When you want to kill a trial mid-run (e.g. the dimension scores recovered
organically):

```bash
sqlite3 ~/gitlab/products/cubeos/claude-context/gateway.db "
  UPDATE prompt_patch_trial
  SET status = 'aborted_no_winner',
      finalized_at = datetime('now'),
      note = COALESCE(note, '') || ' [manual abort by operator]'
  WHERE id = TRIAL_ID AND status = 'active'
"
```

Sessions already assigned to this trial keep their `session_trial_assignment`
rows for audit but no longer influence anything — the finalizer skips non-
active trials.

## Troubleshooting

**"PROMPT_TRIAL_ENABLED is not set to '1'; refusing to start trials"**
Expected when `--start` is run without the flag. Flip the env and re-run,
or use `--dry-run` to preview without the flag.

**"active trial already exists for ('build-prompt', 'actionability'): ..."**
Partial unique index is doing its job — finish or abort the existing trial
first (`abort an active trial`, above).

**Arm counts skewed (one arm has many more samples than others)**
Should be near-uniform for N≥40 samples. If you see a persistent skew,
likely the issue-hash distribution is clustered (e.g. alerts all have the
same numeric suffix). Verify with:
```bash
cd scripts && python3 -c "
from prompt_patch_trial import assign_variant
from collections import Counter
c = Counter(assign_variant(f'ISS-{i:05d}', TRIAL_ID, 3) for i in range(400))
print(dict(c))
"
```

**Trial stuck in `still_active` forever**
Every arm must reach `min_samples_per_arm` (default 15). If the dimension
simply doesn't get 60+ judged sessions in the trial window (14 days), the
timeout sweeper marks it `aborted_timeout`. Override with
`PROMPT_TRIAL_MIN_SAMPLES=5` for a faster but noisier run.

**Finalizer says `reason: unknown dimension 'foo'`**
The `collect_arm_scores` function only knows the 6 judge dimensions listed
in `_JUDGMENT_DIM_COLS` in the library. Adding a new dim means also adding
a column to `session_judgment` and to that dict.

## Related

- Memory: [`preference_iterating_prompt_patcher.md`](../../.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory/preference_iterating_prompt_patcher.md).
- Parent adoption batch runbook: [OpenAI Agents SDK adoption](../../.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory/openai_sdk_adoption_batch.md).
- QA suite: [`scripts/qa/suites/test-645-prompt-trials.sh`](../../scripts/qa/suites/test-645-prompt-trials.sh) — 16 tests, last full-suite run 271/273 PASS (99.27%).
