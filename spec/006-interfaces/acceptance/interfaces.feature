Feature: Component interface contracts
  Covers REQ-501 REQ-503 REQ-504.

  Scenario: An unknown session-replay returns not-found
    Given a session-replay request naming an unknown session
    When the webhook surface handles the request
    Then a not-found response is returned

  Scenario: Every risk decision is persisted
    Given a completed risk classification
    When the decision is recorded
    Then a row exists in the session_risk_audit table
