# Requirements — prediction-gate (fail-closed infragraph plan_hash gate)

REQ-101: The prediction gate shall commit a plan_hash-keyed prediction before any approval poll.
REQ-102: If a remediation plan has no committed prediction, then the prediction gate shall deny the approval poll.
REQ-103: When a predicted action completes, the verifier shall write a mechanical verdict of match, partial, or deviation.
REQ-104: If a verdict is a deviation, then the prediction gate shall refuse to auto-resolve the session.
REQ-105: While the infragraph runs in analysis-only mode, the prediction gate shall record predictions without gating approvals.
