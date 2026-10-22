#!/usr/bin/env bash
# Shared evaluation configuration — sourced by all eval scripts
# Ensures reproducibility across eval runs (OpenAI Evals Guide best practice)

# Reproducibility controls
export EVAL_TEMPERATURE=0
export EVAL_SEED=42
export EVAL_MAX_TOKENS=4096

# Eval set paths
export EVAL_SETS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/eval-sets" && pwd)"
export EVAL_DB="${HOME}/gitlab/products/cubeos/claude-context/gateway.db"

# Scoring thresholds
export JUDGE_MIN_TPR=0.70
export JUDGE_MIN_TNR=0.70
