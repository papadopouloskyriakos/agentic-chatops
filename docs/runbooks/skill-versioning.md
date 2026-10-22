# Skill-versioning convention (SKILL.md semver)

**Issue:** IFRNLLEI01PRD-712 followup — closes governance dim from 4/5 to 5/5.

Every `SKILL.md` under `.claude/{agents,skills,commands}/` carries a
`version: X.Y.Z` key in its YAML frontmatter. This document defines
*when* and *how* to bump it.

## Rules

| Change kind | Bump | Example |
|-------------|:----:|---------|
| Typo fix in body, formatting cleanup | **none** | fix a broken markdown link |
| Prose rewrite that preserves the skill's contract | **patch** (`X.Y.Z` → `X.Y.Z+1`) | reword a paragraph for clarity |
| New row in Shortcuts-to-Resist / Reference Files / Related Skills | **minor** (`X.Y.Z` → `X.Y+1.0`) | add a runbook link |
| New section, new argument, new allowed-tool | **minor** | add a `## Debugging Protocol` section |
| Expanded `description:` (backward-compatible) | **minor** | extend anti-guidance to name more sibling skills |
| Removed section, changed `description:` scope, changed `allowed-tools` | **MAJOR** (`X.Y.Z` → `X+1.0.0`) | narrow a skill to reject a previously-valid input |
| New `requires.bins[]` / `requires.env[]` entry | **MAJOR** | new runtime dependency |
| Skill renamed or deleted | **MAJOR** + update caller index | — |

"Contract" = `name`, `description`, `allowed-tools`, `requires.bins`,
`requires.env`, and any Output Format block in the body. If a caller
was relying on any of those, the change is breaking and needs a MAJOR
bump.

## Why bump at all?

Three live consumers read the version:

1. **`docs/skills-index.md`** auto-generator (`scripts/render-skill-index.py`)
   — every row shows the declared version, so a reviewer can see at
   a glance which skills have moved since the last release.
2. **Prometheus** exporter `scripts/write-skill-metrics.sh` emits
   `chatops_skill_version{skill,kind,version}`. The info-metric lets
   us alert on version churn if needed.
3. **Humans in Matrix / YT** — when a skill misbehaves, the version
   in the exporter or the index is the fastest way to pin the
   misbehaviour to a specific change.

## Bumping mechanics

1. Edit the skill body.
2. Edit the `version: X.Y.Z` key in the frontmatter *in the same
   commit*.
3. Include the reason in the commit message (`"bump /triage to 1.1.0
   — new row in Shortcuts to Resist"`).
4. Let `scripts/render-skill-index.py` re-render `docs/skills-index.md`
   as part of the same commit (the drift test `test-656-skill-index-fresh`
   will reject otherwise).
5. Run `scripts/audit-skill-versions.sh` to confirm no regression
   (no existing skill's version went backwards).

## Stale-skill detection

The advisory audit at `scripts/audit-skill-versions.sh` runs:

- For every SKILL.md, compute the git blob hash of the current body.
- Compare against the blob hash recorded the last time `version:` was bumped.
- If body changed without a version bump since the last bump, flag as
  `VERSION_STALE` (advisory — doesn't block merge, but surfaces in
  the holistic-health skill-prereqs section and in CI output).

This is intentionally soft: typo-fix-only commits *should* land
without a bump, and the audit's job is to surface omissions, not
enforce them mechanically.

## Exceptions

- `SKILL.md` files without a `version:` frontmatter key are silently
  ignored (e.g., commands without YAML frontmatter).
- Auto-generated files (e.g., `docs/skills-index.md`) are regenerated,
  not bumped — their version tracks the renderer's version, not any
  skill's.
- Initial version for a brand-new skill is `1.0.0`. Pre-release
  suffixes (`1.0.0-alpha.1`, `1.0.0-rc.1`) are supported by the audit
  script but discouraged for skills that ship to production.

## History

- 2026-04-23 (Phase C): all 17 SKILL.md carry `version: 1.0.0` as
  their shipped baseline.
- 2026-04-23 (Phase I / followup to -712): this document landed +
  `audit-skill-versions.sh` shipped. Governance dimension moves
  from 4/5 → 5/5.
