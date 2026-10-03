Feature: Risk-tiered autonomy bands
  Covers REQ-001 REQ-002 REQ-004 REQ-006 REQ-008.

  Scenario: A low-risk reversible session auto-resolves
    Given a session whose risk inputs parse cleanly
    And the action is reversible with a committed prediction
    When the risk classifier runs
    Then the band is AUTO

  Scenario: An irreversible session pauses for a human
    Given a session whose action is irreversible
    When the risk classifier runs
    Then the band is POLL_PAUSE
    And an SMS is required

  Scenario: Unparseable inputs fail closed
    Given a session whose risk inputs cannot be parsed
    When the risk classifier runs
    Then the band is POLL_PAUSE

  Scenario: The silent-cognition guard emits its result-stage flag (REQ-008)
    Given a session whose risk inputs parse cleanly
    And the silent-cognition guard sentinel is active
    When the risk classifier runs
    Then the classifier emits a silent_cognition_guard flag
