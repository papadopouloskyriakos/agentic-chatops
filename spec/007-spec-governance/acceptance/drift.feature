Feature: Content-aware spec-code lockstep
  Covers REQ-701 REQ-702 REQ-703.

  Scenario: A governed file changing without its spec is flagged as drift
    Given a lockstep manifest recorded for a governed file
    When the governed file changes but its specification does not
    Then the lockstep guard reports spec drift

  Scenario: Re-stamping the manifest clears the drift
    Given a governed file changed without its specification
    When the operator re-stamps the manifest
    Then the lockstep guard passes

  Scenario: A cosmetic spec edit does not clear genuine drift
    Given a governed file changed without its specification
    When only a comment is added to the specification
    Then the lockstep guard still reports spec drift
