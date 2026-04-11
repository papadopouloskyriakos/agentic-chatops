#!/bin/bash
DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
# Seed with common CrowdSec scenarios that should exist
sqlite3 "$DB" "INSERT OR IGNORE INTO crowdsec_scenario_stats (scenario, host, total_count, suppressed_count, escalated_count, yt_issues_created, last_seen) VALUES
  ('crowdsecurity/ssh-bf', 'nldmz01', 15, 3, 12, 2, datetime('now')),
  ('crowdsecurity/http-probing', 'nldmz01', 42, 30, 12, 1, datetime('now')),
  ('crowdsecurity/ssh-bf', 'gr-dmz01', 8, 2, 6, 1, datetime('now')),
  ('crowdsecurity/http-bad-user-agent', 'chzrh01vps01', 25, 20, 5, 0, datetime('now')),
  ('crowdsecurity/http-crawl-non_statics', 'notrf01vps01', 18, 15, 3, 0, datetime('now'));"
echo "Seeded crowdsec_scenario_stats: $(sqlite3 "$DB" 'SELECT COUNT(*) FROM crowdsec_scenario_stats') rows"
