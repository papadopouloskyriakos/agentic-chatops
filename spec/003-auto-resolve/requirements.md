# Requirements — auto-resolve (Tier-2 reconcile and close-out)

REQ-201: The auto-resolve path shall close a session only after confirming the alert condition cleared.
REQ-202: When a session is classified AUTO and the host recovered, the runner shall reconcile the session and mark the issue resolved.
REQ-203: When a Tier-2 session ends, the close-out hook shall record a resolution_type in the session log.
REQ-204: If a session produced no terminal result, then the reconcile job shall leave the session open for review.
REQ-205: The auto-resolve path shall record every outcome as a per-incident best-outcome row.
REQ-206: When the reconcile job archives a session as poll_unanswered, the auto-resolve path shall schedule a delayed re-check of the underlying alert condition in the escalation queue.
REQ-207: If a re-checked condition is still active, then the requeue job shall re-escalate through the standard escalation webhook and page the operator; if the condition has recovered, the requeue job shall leave issue closure to the alert autocloser.
REQ-208: The requeue job shall stand down to a human after the per-issue unanswered-poll cap is reached, recording the stand-down on the issue.
