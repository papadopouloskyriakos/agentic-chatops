# gropenarchiver01

**Site:** GR (Skagkia)

## Knowledge Base References

**gr:docker/CLAUDE.md**
- | gropenarchiver01 | open-archiver, meilisearch, postgres, tika, valkey | 5 | Archiving |

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-23 | Device Down! Due to no ICMP response. | recurred 4x in 30d without durable fix | analysis-only pending root-cause | N/A |

## Related Memory Entries

- **alerting_dispositions_silences_20260624** (project): "2026-06-24 alerting policy + the 'silence forever the not-actionable' silences created (GR etcd cascade, NL AS64512CountLow/InfragraphPrecisionDrop), killers kept live. Plus the NL-etcd-unmonitored gap."
- **freeipa_admin_keytab_access_20260623** (reference): The agentic system has STANDING passwordless FreeIPA admin access via the svc-claude-gateway keytab — run any ipa op with scripts/ipa.sh; never ask the operator for IPA creds again
- **gr_grk8s-ctrl01_etcd_gr-pve01_saturation_rca_20260623** (project): "2026-06-23 RCA of the GR etcd disk-I/O cascade behind the 91-SMS storm — root cause is chronic gr-pve01 host saturation + a thermally-throttling (SMART-clean, NOT failing) rpool mirror disk nvme2n1, NOT a ctrl01-specific fault. See VERIFIED UPDATE 2026-06-24 — the disk is overheating, not degraded; fix=cooling not replacement."
- **grskg_mass_flap_20260511** (project): "GR site mass flap 02:08-02:14 UTC 2026-05-11 — 16 devices ICMP-down. RC CONFIRMED: gr-nms01 chronically over-budget poll cycles (518s vs 300s) + IO starvation (PSI io.full avg300=7.32%) + 6 concurrent zombie poller-wrapper.py + cororings device 9 pushed past cliff by nlpve04 6th-node add 2026-05-10."
- **postiz_migration_gr_to_nl_20260624** (project): 2026-06-24 migrated grpostiz01 (privileged Docker LXC) cross-site to nlpostiz01 on nlpve04 to relieve gr-pve01 memory pressure (the chronic etcd-cascade root). Full DNS/NPM/e2e done.

*Compiled: 2026-07-03 04:30 UTC*