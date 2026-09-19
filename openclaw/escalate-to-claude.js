/**
 * OpenClaw Skill: Escalate to Claude Code
 *
 * Analyses incoming messages and decides whether to:
 * 1. Answer directly using local context (Tier 1)
 * 2. Escalate to Claude Code via n8n gateway (Tier 2)
 *
 * Escalation triggers: YouTrack issue IDs, implementation keywords,
 * long technical messages, explicit session requests.
 *
 * Stay-local triggers: questions, status checks, short commands,
 * explanatory requests.
 */

const ISSUE_ID_PATTERN = /\b(CUBEOS|MESHSAT)-\d+\b/;
const ESCALATION_KEYWORDS = /\b(implement|fix|build|create|refactor|migrate|deploy|patch|rewrite|update code|add feature|remove feature|write code)\b/i;
const STAY_LOCAL_KEYWORDS = /\b(what is|how does|explain|show me|describe|list|status|where is|when did|who|why does|tell me about)\b/i;

const N8N_WEBHOOK_BASE = 'https://n8n.example.net/webhook';

// Local mode file (synced by sync-mode-openclaw.sh)
const MODE_FILE = '/root/.openclaw/workspace/gateway.mode';

// Remote paths on claude01 (accessed via SSH)
const CLAUDE01_HOST = 'app-user@nl-claude01';
const REMOTE_DB = '/app/cubeos/claude-context/gateway.db';

/**
 * Read a local file, return contents or empty string.
 */
function readFileSync(path) {
  try {
    const { execSync } = require('child_process');
    return execSync(`cat "${path}" 2>/dev/null`, { encoding: 'utf8' }).trim();
  } catch {
    return '';
  }
}

/**
 * Read current gateway mode from local mode file.
 */
function getCurrentMode() {
  return readFileSync(MODE_FILE) || 'oc-cc';
}

/**
 * Check if there is an active Claude Code session via SSH to claude01.
 */
function getActiveSession() {
  try {
    const { execSync } = require('child_process');
    const result = execSync(
      `ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 ${CLAUDE01_HOST} 'sqlite3 "${REMOTE_DB}" "SELECT json_object(\\\"issueId\\\", issue_id, \\\"sessionId\\\", session_id) FROM sessions WHERE is_current=1 LIMIT 1" 2>/dev/null'`,
      { encoding: 'utf8', timeout: 5000 }
    ).trim();
    return result ? JSON.parse(result) : null;
  } catch {
    return null;
  }
}

/**
 * Determine if a message should be escalated to Claude Code.
 *
 * Returns: { escalate: boolean, reason?: string, issueId?: string }
 */
function analyseMessage(message) {
  const text = message.trim();

  // Explicit escalation requests
  if (/\b(start session|claude code|escalate)\b/i.test(text)) {
    return { escalate: true, reason: 'explicit escalation request' };
  }

  // Stay-local signals (check before escalation keywords)
  if (STAY_LOCAL_KEYWORDS.test(text) && text.length < 200) {
    return { escalate: false };
  }

  // Single-word or very short messages — stay local
  if (text.split(/\s+/).length <= 3 && !ISSUE_ID_PATTERN.test(text)) {
    return { escalate: false };
  }

  // YouTrack issue ID detected
  const issueMatch = text.match(ISSUE_ID_PATTERN);
  if (issueMatch) {
    const issueId = issueMatch[0];
    // Only escalate if there are also action words
    if (ESCALATION_KEYWORDS.test(text) || /\b(start|begin|work on|pick up)\b/i.test(text)) {
      return { escalate: true, reason: `YouTrack issue ${issueId} with implementation intent`, issueId };
    }
    // Issue ID alone without action words — answer locally (e.g. "what's CUBEOS-48 about?")
    return { escalate: false };
  }

  // Implementation keywords without issue ID
  if (ESCALATION_KEYWORDS.test(text)) {
    return { escalate: true, reason: 'implementation work detected (no issue ID)' };
  }

  // Long technical message (>200 chars with code-like content)
  if (text.length > 200 && /[{}\[\]();=<>\/]/.test(text)) {
    return { escalate: true, reason: 'long technical message' };
  }

  // Default: stay local
  return { escalate: false };
}

/**
 * Main skill handler. Called by OpenClaw for each incoming message.
 *
 * @param {Object} context - OpenClaw context
 * @param {string} context.message - The user's message
 * @param {string} context.roomId - Matrix room ID
 * @param {string} context.sender - Matrix user ID
 * @returns {Object} Response object
 */
async function handle(context) {
  const { message, roomId, sender } = context;
  const mode = getCurrentMode();

  // In cc-* modes, OpenClaw should not handle messages (n8n bridge handles them)
  if (mode.startsWith('cc')) {
    return { skip: true, reason: 'cc-mode active, n8n bridge handles messages' };
  }

  // Analyse the message
  const analysis = analyseMessage(message);

  if (!analysis.escalate) {
    // Stay local — return null to let OpenClaw's normal response pipeline handle it
    return null;
  }

  // Escalation path
  const activeSession = getActiveSession();

  if (analysis.issueId) {
    // We have an issue ID — instruct user to start session
    const sessionNote = activeSession
      ? `\n(Note: session already active for ${activeSession.issueId})`
      : '';
    return {
      respond: true,
      message: `\u2191 Escalating to Claude Code \u2014 ${analysis.reason}.${sessionNote}\nRun: \`!issue start ${analysis.issueId}\``
    };
  }

  // No issue ID — suggest creating one
  return {
    respond: true,
    message: `\u2191 This looks like implementation work. Start a YouTrack issue first:\n\`!issue start <ISSUE-ID>\`\n\nOr ask me to explain/analyse and I'll handle it locally.`
  };
}

module.exports = { handle, analyseMessage, getCurrentMode, getActiveSession };
