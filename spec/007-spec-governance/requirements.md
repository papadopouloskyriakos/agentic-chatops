# Requirements — spec-governance (content-aware lockstep)

REQ-701: The lockstep guard shall record a content hash for every governed safety-critical file.
REQ-702: If a governed file changes without its owning specification changing, then the lockstep guard shall report spec drift.
REQ-703: When an operator re-stamps the manifest, the lockstep guard shall accept the recorded content hashes.
REQ-704: While detecting drift, the lockstep guard shall compare only the semantic content of a specification.
