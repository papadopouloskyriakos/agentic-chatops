/**
 * Element-styled HTML renderer for Matrix messages.
 * Takes message objects and produces a complete HTML page for Playwright to screenshot.
 */
const fs = require('fs');
const path = require('path');

const TEMPLATE_PATH = path.join(__dirname, '..', 'templates', 'element-message.html');

const ROOM_DISPLAY_NAMES = {
  'infra-nl': '#infra-nl-prod',
  'infra-gr': '#infra-gr-prod',
  'chatops': '#chatops',
  'cubeos': '#cubeos',
  'meshsat': '#meshsat',
  'alerts': '#alerts',
};

function senderInfo(userId) {
  if (userId?.includes('claude')) {
    return { name: 'Claude', avatarClass: 'avatar-claude', senderClass: 'sender-claude', initial: 'C' };
  }
  if (userId?.includes('openclaw')) {
    return { name: 'OpenClaw', avatarClass: 'avatar-openclaw', senderClass: 'sender-openclaw', initial: 'O' };
  }
  return { name: 'User', avatarClass: 'avatar-user', senderClass: 'sender-user', initial: 'U' };
}

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

function formatDate(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleDateString('en-GB', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
}

/**
 * Render a single message as an HTML row.
 */
function renderMessage(msg, prevSender) {
  const info = senderInfo(msg.sender);
  const isContinuation = prevSender === msg.sender;
  const isNotice = msg.msgtype === 'm.notice';
  const time = formatTime(msg.timestamp);

  // Use formatted_body if available, otherwise escape plain text
  let bodyHtml;
  if (msg.formatted_body) {
    bodyHtml = msg.formatted_body;
  } else {
    bodyHtml = escapeHtml(msg.body).replace(/\n/g, '<br>');
  }

  const classes = [
    'msg-row',
    isContinuation ? 'continuation' : '',
    isNotice ? 'notice' : '',
  ].filter(Boolean).join(' ');

  return `
    <div class="${classes}">
      <div class="msg-avatar ${info.avatarClass}">${info.initial}</div>
      <div class="msg-content">
        <div class="msg-sender ${info.senderClass}">
          ${info.name}
          <span class="msg-time">${time}</span>
        </div>
        <div class="msg-body">${bodyHtml}</div>
      </div>
    </div>`;
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Render a full audit page with multiple messages.
 *
 * @param {Object} opts
 * @param {string} opts.title - Page title (e.g. "Matrix Audit: LibreNMS Alerts")
 * @param {string} opts.category - Category tag (e.g. "librenms-alert")
 * @param {string} opts.room - Room short name (e.g. "infra-nl")
 * @param {Array} opts.messages - Array of message objects
 * @param {Array} [opts.auditNotes] - Optional audit annotations to insert
 * @returns {string} Complete HTML page
 */
function renderAuditPage({ title, category, room, messages, auditNotes = [] }) {
  const template = fs.readFileSync(TEMPLATE_PATH, 'utf-8');

  // Render messages
  let messagesHtml = '';
  let prevSender = null;
  let prevDate = null;

  // Show in chronological order (API returns newest-first)
  const sorted = [...messages].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));

  for (const msg of sorted) {
    // Date separator
    const msgDate = formatDate(msg.timestamp);
    if (msgDate && msgDate !== prevDate) {
      messagesHtml += `<div class="date-separator">${msgDate}</div>`;
      prevSender = null; // Reset continuation after date change
      prevDate = msgDate;
    }

    messagesHtml += renderMessage(msg, prevSender);
    prevSender = msg.sender;
  }

  // Insert audit notes at the end
  for (const note of auditNotes) {
    messagesHtml += `<div class="audit-note">${escapeHtml(note)}</div>`;
  }

  const ts = sorted.length > 0 ? formatDate(sorted[0]?.timestamp) : 'N/A';
  const roomDisplay = ROOM_DISPLAY_NAMES[room] || `#${room}`;

  return template
    .replaceAll('{{TITLE}}', escapeHtml(title))
    .replaceAll('{{CATEGORY}}', escapeHtml(category))
    .replaceAll('{{ROOM}}', escapeHtml(room))
    .replaceAll('{{TIMESTAMP}}', escapeHtml(ts))
    .replaceAll('{{ROOM_DISPLAY}}', escapeHtml(roomDisplay))
    .replaceAll('{{MESSAGES}}', messagesHtml);
}

module.exports = { renderAuditPage, renderMessage, escapeHtml, ROOM_DISPLAY_NAMES };
