Feature: Repeat-offender auto-demotion
  Covers REQ-302 REQ-303 REQ-304.

  Scenario: A genuine repeat offender is demoted
    Given a host and rule that recurred four times in thirty days
    And the pattern is not an intentional known-transient
    When the governance job runs
    Then the pattern is classified as a demote candidate
    And the demotion expires after thirty days

  Scenario: A known-transient is excluded
    Given a pattern marked as an intentional known-transient
    When the governance job runs
    Then the pattern is excluded from demotion
