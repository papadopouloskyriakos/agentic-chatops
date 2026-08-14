# Requirements — tier1-suppression (host-agnostic known-transient suppression)

REQ-401: The tier-1 suppression shall match known-transient patterns by host-agnostic rule.
REQ-402: When a blast-radius control issue is open, the tier-1 suppression shall activate the declared suppression rule.
REQ-403: While a suppression rule is active, the receiver shall post the alert as a notice without spawning a session.
REQ-404: The tier-1 suppression shall suppress a reboot-class alert as scheduled when the host has a live, un-expired, un-killed registered schedule whose strict time window contains the alert time.
REQ-405: If a scheduled-reboot match is not confirmed, then the tier-1 suppression shall fail open to standard escalation.
REQ-406: When the tier-1 suppression suppresses a scheduled reboot, the receiver shall launch a two-phase verify that reopens the alert if the boot reason was not a clean systemd-reboot.
REQ-407: If a reboot alert is severity-critical, then the tier-1 suppression shall not suppress it.

REQ-408: The tier-1 phase-1 open-issue dedup shall only match a prior triage-log entry whose age is within [0, window) minutes; an entry timestamped after the current time (negative age / clock skew / future-dated) shall be rejected and the alert shall fail open to escalation.
