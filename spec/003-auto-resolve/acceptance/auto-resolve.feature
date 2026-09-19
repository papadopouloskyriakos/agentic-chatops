Feature: Per-incident auto-resolution
  Covers REQ-202 REQ-204 REQ-205.

  Scenario: A recovered host is auto-resolved
    Given an AUTO-band session whose host recovered
    When the reconcile job runs
    Then the issue is marked resolved
    And the outcome is recorded as a per-incident best-outcome row

  Scenario: An incomplete session stays open
    Given a session that produced no terminal result
    When the reconcile job runs
    Then the session is left open for review

  Scenario: An orphaned poll with a still-active condition is re-escalated
    Given a POLL_PAUSE session archived as poll_unanswered
    And the underlying alert condition is still active at the scheduled re-check
    When the requeue job runs
    Then the escalation is re-fired through the standard webhook
    And the operator is paged

  Scenario: An orphaned poll whose condition recovered is left to the autocloser
    Given a POLL_PAUSE session archived as poll_unanswered
    And the underlying alert condition has recovered at the scheduled re-check
    When the requeue job runs
    Then the queue row is marked recovered
    And issue closure is left to the alert autocloser
