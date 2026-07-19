# Requirements — governance (repeat-offender auto-demote)

REQ-301: While auto-demotion is enabled, the governance job shall demote a genuine repeat-offender pattern to analysis-only.
REQ-302: When a host and rule recur three or more times in thirty days, the governance job shall classify the pattern as a demote candidate.
REQ-303: If a pattern is an intentional known-transient, then the governance job shall exclude it from demotion.
REQ-304: The governance demotion shall expire automatically after thirty days.
REQ-305: The governance job shall report the fraction of recently ended sessions that carry a real local judgment, computed only from tables the judge process does not write.
REQ-306: If fewer than half of recently ended sessions carry a real local judgment over more than three eligible sessions, then the platform shall raise a judge-death warning.
