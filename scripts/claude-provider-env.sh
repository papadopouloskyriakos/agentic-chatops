#!/usr/bin/env bash
# claude-provider-env.sh — RETAINED but intentionally a NO-OP.
#
# History: this used to read ~/gateway.claude_provider and export the Z.ai env so the Runner's
# `claude -p` would route to Z.ai. As of 2026-06-28 the provider switch moved to ~/.claude/settings.json
# (managed by claude-provider.sh), which Claude Code reads as its base env for EVERY invocation —
# dispatched sessions AND auxiliary tools AND interactive, uniformly. That is the single source of
# truth now. The Runner still sources this file (harmless); it does nothing so settings.json wins.
# If you ever need per-session overrides again, put the logic here. Trailing `true` = never fails the
# dispatch command even if sourced from a context that checks exit status.
true
