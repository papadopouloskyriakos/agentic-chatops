Feature: Tier-1 known-transient suppression
  Covers REQ-402 REQ-403 REQ-404 REQ-405 REQ-406 REQ-407.

  Scenario: An open control issue activates suppression
    Given a blast-radius control issue that is open
    When a matching alert arrives
    Then the suppression rule activates
    And the alert is posted as a notice without spawning a session

  Scenario: An on-schedule reboot is suppressed; a two-phase verify follows
    Given a host with a live registered reboot schedule whose window contains the alert time
    When a reboot-class alert arrives with non-critical severity
    Then the alert is suppressed as a scheduled reboot without spawning a session
    And a two-phase verify checks the boot reason
    But the verify reopens the alert when the boot reason was not a clean systemd-reboot

  Scenario: An off-schedule or critical reboot is not suppressed
    Given a host with a live registered reboot schedule
    When a reboot arrives outside the schedule window, or with critical severity
    Then the tier-1 suppression fails open to standard escalation

  Scenario: A future-dated triage-log entry does not dedup an alert
    Given a prior triage-log entry timestamped after the current time
    When a matching alert is triaged
    Then the tier-1 suppression rejects the negative-age entry and fails open to escalation
