#!/bin/bash
# compute-quality-score.sh — Multi-dimensional session quality scoring
# Called from Session End workflow after session_log INSERT
# Usage: compute-quality-score.sh <issue_id>
#
# Computes 5 dimension scores (0-100) and a weighted composite:
#   1. confidence_score (25%) — based on confidence value
#   2. cost_efficiency (15%) — relative to project median
#   3. response_completeness (25%) — presence of required fields
#   4. feedback_score (20%) — thumbs up/down outcome
#   5. resolution_speed (15%) — relative to project median duration

set -uo pipefail

ISSUE_ID="${1:?Usage: compute-quality-score.sh <issue_id>}"
DB="/home/claude-runner/gitlab/products/cubeos/claude-context/gateway.db"

[ -f "$DB" ] || exit 0

# Ensure table exists
sqlite3 "$DB" "
CREATE TABLE IF NOT EXISTS session_quality (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id TEXT NOT NULL,
  session_id TEXT DEFAULT '',
  confidence_score INTEGER DEFAULT -1,
  cost_efficiency INTEGER DEFAULT -1,
  response_completeness INTEGER DEFAULT -1,
  feedback_score INTEGER DEFAULT -1,
  resolution_speed INTEGER DEFAULT -1,
  quality_score INTEGER DEFAULT -1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sq_issue ON session_quality(issue_id);
CREATE INDEX IF NOT EXISTS idx_sq_created ON session_quality(created_at);
" 2>/dev/null

# Get session data
SESSION=$(sqlite3 "$DB" "SELECT confidence, cost_usd, duration_seconds, resolution_type, prompt_variant, session_id
  FROM session_log WHERE issue_id='$ISSUE_ID' ORDER BY id DESC LIMIT 1;" 2>/dev/null)

[ -z "$SESSION" ] && exit 0

IFS='|' read -r CONF COST DUR RES_TYPE VARIANT SID <<< "$SESSION"

# Determine project type
PREFIX=$(echo "$ISSUE_ID" | cut -d- -f1)
case "$PREFIX" in
  IFRNLLEI01PRD) PROJECT="infra-nl" ;;
  IFRGRSKG01PRD) PROJECT="infra-gr" ;;
  *) PROJECT="dev" ;;
esac

# ── 1. Confidence Score (0-100, weight 25%) ──
CONF_SCORE=-1
if [ -n "$CONF" ] && [ "$CONF" != "-1" ]; then
  CONF_SCORE=$(python3 -c "
c = float('$CONF')
if c >= 0.8: print(100)
elif c >= 0.6: print(75)
elif c >= 0.4: print(50)
elif c >= 0.2: print(25)
else: print(10)
" 2>/dev/null || echo -1)
else
  CONF_SCORE=0  # Missing confidence = worst score
fi

# ── 2. Cost Efficiency (0-100, weight 15%) ──
COST_SCORE=-1
if [ -n "$COST" ] && [ "$COST" != "0" ]; then
  MEDIAN_COST=$(sqlite3 "$DB" "
    SELECT COALESCE(cost_usd, 0) FROM session_log
    WHERE cost_usd > 0 AND started_at > datetime('now', '-30 days')
      AND issue_id LIKE '${PREFIX}-%'
    ORDER BY cost_usd LIMIT 1 OFFSET (
      SELECT COUNT(*)/2 FROM session_log
      WHERE cost_usd > 0 AND started_at > datetime('now', '-30 days')
        AND issue_id LIKE '${PREFIX}-%'
    );" 2>/dev/null || echo 0)

  if [ -n "$MEDIAN_COST" ] && [ "$MEDIAN_COST" != "0" ]; then
    COST_SCORE=$(python3 -c "
cost, median = float('$COST'), float('$MEDIAN_COST')
ratio = cost / median if median > 0 else 1
if ratio <= 1.0: print(100)
elif ratio <= 2.0: print(int(100 - (ratio - 1) * 50))
elif ratio <= 4.0: print(int(50 - (ratio - 2) * 25))
else: print(0)
" 2>/dev/null || echo 50)
  else
    COST_SCORE=50  # No baseline = neutral
  fi
fi

# ── 3. Response Completeness (0-100, weight 25%) ──
COMP_SCORE=100
# Check if confidence was present (no retry needed)
[ "$CONF" = "-1" ] || [ -z "$CONF" ] && COMP_SCORE=$((COMP_SCORE - 30))
# Check resolution_type
[ "$RES_TYPE" = "unknown" ] && COMP_SCORE=$((COMP_SCORE - 20))

# ── 4. Feedback Score (0-100, weight 20%) ──
FEED_SCORE=-1
FEEDBACK=$(sqlite3 "$DB" "SELECT feedback_type FROM session_feedback WHERE issue_id='$ISSUE_ID' ORDER BY created_at DESC LIMIT 1;" 2>/dev/null)
case "$FEEDBACK" in
  thumbs_up) FEED_SCORE=100 ;;
  thumbs_down) FEED_SCORE=0 ;;
  *) FEED_SCORE=-1 ;;  # No feedback = skip this dimension
esac

# ── 5. Resolution Speed (0-100, weight 15%) ──
SPEED_SCORE=-1
if [ -n "$DUR" ] && [ "$DUR" != "0" ]; then
  MEDIAN_DUR=$(sqlite3 "$DB" "
    SELECT COALESCE(duration_seconds, 0) FROM session_log
    WHERE duration_seconds > 0 AND started_at > datetime('now', '-30 days')
      AND issue_id LIKE '${PREFIX}-%'
    ORDER BY duration_seconds LIMIT 1 OFFSET (
      SELECT COUNT(*)/2 FROM session_log
      WHERE duration_seconds > 0 AND started_at > datetime('now', '-30 days')
        AND issue_id LIKE '${PREFIX}-%'
    );" 2>/dev/null || echo 0)

  if [ -n "$MEDIAN_DUR" ] && [ "$MEDIAN_DUR" != "0" ]; then
    SPEED_SCORE=$(python3 -c "
dur, median = float('$DUR'), float('$MEDIAN_DUR')
ratio = dur / median if median > 0 else 1
if ratio <= 1.0: print(100)
elif ratio <= 2.0: print(int(100 - (ratio - 1) * 50))
elif ratio <= 4.0: print(int(50 - (ratio - 2) * 25))
else: print(0)
" 2>/dev/null || echo 50)
  else
    SPEED_SCORE=50
  fi
fi

# ── Composite Score (weighted average of available dimensions) ──
QUALITY=$(python3 -c "
scores = {
    'confidence': ($CONF_SCORE, 0.25),
    'cost': ($COST_SCORE, 0.15),
    'completeness': ($COMP_SCORE, 0.25),
    'feedback': ($FEED_SCORE, 0.20),
    'speed': ($SPEED_SCORE, 0.15),
}
available = {k: (s, w) for k, (s, w) in scores.items() if s >= 0}
if not available:
    print(-1)
else:
    total_weight = sum(w for _, w in available.values())
    composite = sum(s * (w / total_weight) for s, w in available.values())
    print(int(round(composite)))
" 2>/dev/null || echo -1)

# ── Store ──
sqlite3 "$DB" "INSERT INTO session_quality (issue_id, session_id, confidence_score, cost_efficiency, response_completeness, feedback_score, resolution_speed, quality_score)
  VALUES ('$ISSUE_ID', '$SID', $CONF_SCORE, $COST_SCORE, $COMP_SCORE, $FEED_SCORE, $SPEED_SCORE, $QUALITY);" 2>/dev/null

echo "QUALITY:$ISSUE_ID:$QUALITY (conf=$CONF_SCORE cost=$COST_SCORE comp=$COMP_SCORE feed=$FEED_SCORE speed=$SPEED_SCORE)"
