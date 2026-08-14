# Requirements — interfaces (HTTP, event, and persistent surfaces)

REQ-501: The webhook surface shall accept stats and session-replay requests over HTTP.
REQ-502: When an alert receiver fires, the event surface shall publish a triage event to the routing layer.
REQ-503: The persistent surface shall store every risk decision in the session_risk_audit table.
REQ-504: If a session-replay request names an unknown session, then the webhook surface shall return a not-found response.
REQ-505: The persistent surface shall stamp every audit row with a schema_version.
REQ-506: The persistent surface shall store discovered scheduled-reboot schedules in the discovered_scheduled_reboots table, each stamped with a schema_version.
REQ-507: The persistent surface shall store dropped and re-checkable escalations in the escalation_queue table, each stamped with a schema_version.
REQ-508: The persistent surface shall record disk-pressure remediation actions (cleanup and LVM/qcow2 grow) in the disk_grow_log table, each stamped with a schema_version.

