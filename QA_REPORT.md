# Claude Gateway — QA Report
**Date:** 2026-03-08
**Tester:** Operator (dominicus)
**Version:** post-Batch6 + hotfixes

## Summary
Full end-to-end QA pass covering all 9 command groups.
All sections PASS. 8 bugs found and fixed during QA.

## Results

| Section | Tests | Result |
|---------|-------|--------|
| 1. Help system | 6/6 | PASS |
| 2. No-session state | 11/11 | PASS |
| 3. System commands | 3/3 | PASS |
| 4. Issue commands | 6/6 | PASS |
| 5. Pipeline commands | 6/6 | PASS |
| 6. Session lifecycle (start/message/pause/resume/done) | all | PASS |
| 7. Multi-session + prefixed routing | all | PASS |
| 8. Legacy aliases (!status, !cancel, !done) | 4/4 | PASS |
| 9. Edge cases | all | PASS |

## Bugs Found and Fixed During QA

1. **!issue comment ARGREST word splitting** — RAW_ARGREST without quotes lost all text after first word. Fixed: wrapped template assignments in double quotes. (b909e39)
2. **!session resume not draining queue** — resume set paused=0 but never delivered queued messages. Fixed: added Drain Queue on Resume SSH node that combines all queued messages into one prompt and delivers immediately. (9b57bfe)
3. **Queue drain used wrong working directory** — claude -r called without cd to project dir, session not found. Fixed: added cd /app/cubeos && before claude invocation. (3f40aee)
4. **Global cooldown blocked unrelated sessions** — gateway.cooldown was a single global file; starting any new session within 2min of any !done was blocked silently. Fixed: per-issue cooldown files (gateway.cooldown.CUBEOS-4), TTL reduced from 120s to 30s. (ea11dbf)
5. **Cooldown hit was silent** — operator had no visibility into why session start failed. Fixed: posts "Session start for CUBEOS-4 blocked by cooldown (retry in Xs)" to Matrix. (ea11dbf)
6. **!session done <id> for non-current session failed** — Handle Session queried is_current=1 instead of issue_id for explicit-ID variants. Fixed: all explicit-ID commands (done/cancel/pause/resume) now query by issue_id. (81dbb9a)
7. **Session End deleted wrong session** — Clean Up Files node used is_current=1 for all DB ops; when ending a non-current session, the current session was deleted instead. Fixed: Session End uses the passed issue_id for all DB operations. (9bbb54a)
8. **Empty prefixed body hung Claude** — CUBEOS-4: (no body) passed through to Runner, which called claude -r <id> -p "" causing Claude to hang indefinitely holding the lock. Fixed: Detect Command rejects empty/whitespace-only body immediately with usage hint. (70c1744)

## Known Minor Issues (Non-Blocking)
- `!system processes` CPU column has extra spaces (`0.0   %` instead of `0.0%`)
- `!pipeline status <repo>` duration column shows `—` when pipeline `finished_at` is null

## DB State at QA Completion
- sessions: 0 rows
- queue: 0 rows
- session_log: 10 rows (historical)

## Commits During QA
- b909e39 — fix !issue comment ARGREST word splitting
- 9b57bfe — add Drain Queue on Resume
- 3f40aee — drain queue working directory fix
- ea11dbf — per-issue cooldown, Matrix notice, 30s TTL
- 81dbb9a — explicit issue-id queries by issue_id not is_current
- 9bbb54a — session end uses passed issue_id for all DB ops
- 70c1744 — reject empty prefixed message body
