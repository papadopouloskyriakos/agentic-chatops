# grpostiz01

**Site:** GR (Skagkia)

## Knowledge Base References

**gr:docker/CLAUDE.md**
- | grpostiz01 | postiz, temporal stack (6 containers), nginx, postgres | 10 | Social media |

**other:/app/n8n/social-media-autoposter/CLAUDE.md**
- - **Postiz** — self-hosted at postiz.example.net (backend **nlpostiz01** `10.0.181.X` on nlpve04 — migrated cross-site from grpostiz01 on 2026-06-24; Postgres `postiz-db-local` user `postiz-user`). **Image posts depend on an inbound Meta fetch:** Postiz embeds a public media URL `https://postiz.example.net/uploads/...` (built from `FRONTEND_URL`, injected by the `Postiz (Upload File)` → Create Post nodes as `image[].path`), and **Meta's servers (AS32934) fetch it inbound** → public DNS `postiz → 203.0.113.X` → `nl-fw01` (META_AS32934 permit → NPM:443). If FB/IG images stop attaching, check that path (firewall ACL hit, Cloudflare A record, `/uploads` serving 200).

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-24 | Device Down! Due to no ICMP response. | recurred 3x in 30d without durable fix | analysis-only pending root-cause | N/A |

## Related Memory Entries

- **alerting_dispositions_silences_20260624** (project): "2026-06-24 alerting policy + the 'silence forever the not-actionable' silences created (GR etcd cascade, NL AS64512CountLow/InfragraphPrecisionDrop), killers kept live. Plus the NL-etcd-unmonitored gap."
- **autoposter-silent-halt-search-widget-20260527** (project): "2026-05-27 RCA — RSS2Postiz workflow (n8n ID dCCyqbu2lrWTxAxh) stopped posting after 2026-05-17 because withelli.com added a client-side search widget whose JS-template `<img src=\"'+e.thumb+'\">` now appears before the article image; the brittle image-extractor regex returns an empty src → imageUrl=null → silently filter-zero at Filter Latest Item; no node errors so all executions still report status=success."
- **postiz_gr-fw01_firewall_rules_pending_migration_20260624** (project): 2026-06-24 — gr-fw01 (GR ASA) firewall rules around the migrated postiz still point at GR; the :80 Meta-webhook static-NAT is BROKEN, Cloudflare still pins postiz to GR. Pending migration to nl-fw01.
- **postiz_migration_gr_to_nl_20260624** (project): 2026-06-24 migrated grpostiz01 (privileged Docker LXC) cross-site to nlpostiz01 on nlpve04 to relieve gr-pve01 memory pressure (the chronic etcd-cascade root). Full DNS/NPM/e2e done.
- **Postiz self-hosted (postiz.example.net)** (reference): Where Postiz lives, how to reach it, the Postgres credentials and table layout for debugging post fan-out, and the 4 social-platform integration IDs used by the RSS autoposter workflow.

*Compiled: 2026-07-03 04:30 UTC*