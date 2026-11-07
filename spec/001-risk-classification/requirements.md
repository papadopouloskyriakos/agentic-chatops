# Requirements — risk-classification (3-band autonomy-forward gate)

REQ-001: The risk classifier shall emit a band of AUTO, AUTO_NOTICE, or POLL_PAUSE for every session.
REQ-002: When a session is low-risk or reversible with a committed prediction, the risk classifier shall assign the AUTO band.
REQ-003: When a reversible mixed-risk action targets a P0 host or a wide blast radius, the risk classifier shall assign the AUTO_NOTICE band and require an SMS.
REQ-004: If a session is high-risk, irreversible, unpredicted, or a deviation, then the risk classifier shall assign the POLL_PAUSE band.
REQ-005: While the autonomy-forward sentinel is absent, the risk classifier shall produce byte-identical legacy output.
REQ-006: If the risk inputs cannot be parsed, then the risk classifier shall force the high-risk band.
REQ-007: When the autonomy-forward gate is active and a session's incident class has no learned prior, the risk classifier shall force the POLL_PAUSE band and append an ood:novel-incident signal.
REQ-008: When the silent-cognition guard sentinel is active, the risk classifier shall emit a silent_cognition_guard flag so that the Runner's result stage suppresses any [AUTO-RESOLVE] whose final reply ships no fenced post-state evidence block, at any confidence (extending the CONFIDENCE>=0.8 evidence-missing check); while the guard sentinel is absent, classifier output shall be byte-identical.
