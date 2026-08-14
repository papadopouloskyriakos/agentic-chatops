Feature: Fail-closed prediction gate
  Covers REQ-101 REQ-102 REQ-104.

  Scenario: An unpredicted plan is denied
    Given a remediation plan with no committed prediction
    When the prediction gate evaluates the approval poll
    Then the poll is denied

  Scenario: A deviation blocks auto-resolution
    Given a completed action whose verdict is deviation
    When the prediction gate evaluates auto-resolution
    Then auto-resolution is refused
