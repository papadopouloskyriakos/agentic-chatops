#!/bin/bash
# write-model-metrics.sh — Per-model LLM token/cost Prometheus metrics
# Runs as cron every 5 minutes on nl-claude01 as app-user
DB=/app/cubeos/claude-context/gateway.db
OUT=/var/lib/node_exporter/textfile_collector/model_metrics.prom
TMPOUT="${OUT}.tmp"

[ -f "$DB" ] || exit 0

> "$TMPOUT"

# ============================================================================
# Per-model token totals (30d)
# ============================================================================
echo "# HELP llm_input_tokens_total Input tokens by model and tier (30d)" >> "$TMPOUT"
echo "# TYPE llm_input_tokens_total gauge" >> "$TMPOUT"
echo "# HELP llm_output_tokens_total Output tokens by model and tier (30d)" >> "$TMPOUT"
echo "# TYPE llm_output_tokens_total gauge" >> "$TMPOUT"
echo "# HELP llm_cost_total Cost in USD by model and tier (30d)" >> "$TMPOUT"
echo "# TYPE llm_cost_total gauge" >> "$TMPOUT"
echo "# HELP llm_requests_total Request count by model and tier (30d)" >> "$TMPOUT"
echo "# TYPE llm_requests_total gauge" >> "$TMPOUT"

sqlite3 "$DB" "SELECT tier, model, SUM(input_tokens), SUM(output_tokens), ROUND(SUM(cost_usd),4), COUNT(*)
FROM llm_usage WHERE recorded_at > datetime('now', '-30 days')
GROUP BY tier, model;" 2>/dev/null | \
while IFS='|' read -r tier model in_tok out_tok cost count; do
    [ -z "$model" ] && continue
    echo "llm_input_tokens_total{tier=\"$tier\",model=\"$model\"} $in_tok"
    echo "llm_output_tokens_total{tier=\"$tier\",model=\"$model\"} $out_tok"
    echo "llm_cost_total{tier=\"$tier\",model=\"$model\"} $cost"
    echo "llm_requests_total{tier=\"$tier\",model=\"$model\"} $count"
done >> "$TMPOUT"

# ============================================================================
# 7-day rolling cost by model
# ============================================================================
echo "# HELP llm_cost_7d Cost in USD by model (7d)" >> "$TMPOUT"
echo "# TYPE llm_cost_7d gauge" >> "$TMPOUT"

sqlite3 "$DB" "SELECT model, ROUND(SUM(cost_usd),4) FROM llm_usage
WHERE recorded_at > datetime('now', '-7 days')
GROUP BY model;" 2>/dev/null | \
while IFS='|' read -r model cost; do
    [ -z "$model" ] && continue
    echo "llm_cost_7d{model=\"$model\"} $cost"
done >> "$TMPOUT"

# ============================================================================
# Daily cost by tier (today, for budget tracking)
# ============================================================================
echo "# HELP llm_cost_today Cost in USD by tier today" >> "$TMPOUT"
echo "# TYPE llm_cost_today gauge" >> "$TMPOUT"

sqlite3 "$DB" "SELECT tier, ROUND(SUM(cost_usd),4) FROM llm_usage
WHERE recorded_at > datetime('now', 'start of day')
GROUP BY tier;" 2>/dev/null | \
while IFS='|' read -r tier cost; do
    echo "llm_cost_today{tier=\"$tier\"} $cost"
done >> "$TMPOUT"

# Emit zero if no data today
HAS_TODAY=$(sqlite3 "$DB" "SELECT COUNT(*) FROM llm_usage WHERE recorded_at > datetime('now', 'start of day');" 2>/dev/null || echo 0)
if [ "$HAS_TODAY" = "0" ]; then
    echo "llm_cost_today{tier=\"1\"} 0" >> "$TMPOUT"
    echo "llm_cost_today{tier=\"2\"} 0" >> "$TMPOUT"
fi

# ============================================================================
# Cache hit ratio (Tier 2, 7d)
# ============================================================================
echo "# HELP llm_cache_hit_ratio Cache read tokens / total input tokens (7d, tier 2)" >> "$TMPOUT"
echo "# TYPE llm_cache_hit_ratio gauge" >> "$TMPOUT"

RATIO=$(sqlite3 "$DB" "SELECT
  CASE WHEN SUM(input_tokens + cache_read_tokens) > 0
    THEN ROUND(1.0 * SUM(cache_read_tokens) / SUM(input_tokens + cache_read_tokens), 4)
    ELSE 0 END
FROM llm_usage WHERE tier=2 AND recorded_at > datetime('now', '-7 days');" 2>/dev/null || echo 0)
echo "llm_cache_hit_ratio $RATIO" >> "$TMPOUT"

# ============================================================================
# Total cost all-time by tier
# ============================================================================
echo "# HELP llm_cost_alltime Total cost in USD by tier (all time)" >> "$TMPOUT"
echo "# TYPE llm_cost_alltime gauge" >> "$TMPOUT"

sqlite3 "$DB" "SELECT tier, ROUND(SUM(cost_usd),4) FROM llm_usage GROUP BY tier;" 2>/dev/null | \
while IFS='|' read -r tier cost; do
    echo "llm_cost_alltime{tier=\"$tier\"} $cost"
done >> "$TMPOUT"

# ============================================================================
# Average cost per request by model (30d)
# ============================================================================
echo "# HELP llm_avg_cost_per_request Average cost per request by model (30d)" >> "$TMPOUT"
echo "# TYPE llm_avg_cost_per_request gauge" >> "$TMPOUT"

sqlite3 "$DB" "SELECT model, ROUND(AVG(cost_usd),6) FROM llm_usage
WHERE recorded_at > datetime('now', '-30 days')
GROUP BY model;" 2>/dev/null | \
while IFS='|' read -r model avg_cost; do
    [ -z "$model" ] && continue
    echo "llm_avg_cost_per_request{model=\"$model\"} $avg_cost"
done >> "$TMPOUT"

# ============================================================================
# Token throughput (tokens per day, 7d average)
# ============================================================================
echo "# HELP llm_tokens_per_day_avg Average tokens per day by tier (7d)" >> "$TMPOUT"
echo "# TYPE llm_tokens_per_day_avg gauge" >> "$TMPOUT"

sqlite3 "$DB" "SELECT tier,
  ROUND(SUM(input_tokens + output_tokens) / 7.0, 0)
FROM llm_usage WHERE recorded_at > datetime('now', '-7 days')
GROUP BY tier;" 2>/dev/null | \
while IFS='|' read -r tier tpd; do
    echo "llm_tokens_per_day_avg{tier=\"$tier\"} $tpd"
done >> "$TMPOUT"

mv "$TMPOUT" "$OUT"
