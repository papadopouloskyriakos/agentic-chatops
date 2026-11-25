/**
 * YouTrack-styled HTML renderer for issue descriptions and comments.
 * Fetches data via API and renders in a YouTrack-like visual style.
 */
const fs = require('fs');
const path = require('path');

const TEMPLATE_PATH = path.join(__dirname, '..', 'templates', 'youtrack-issue.html');

/**
 * Very basic markdown-to-HTML for YouTrack comments.
 * YouTrack renders GitHub-style markdown.
 */
function markdownToHtml(text) {
  if (!text) return '';

  let html = text;

  // Escape HTML entities first
  html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // Unescape literal \\n to actual newlines
  html = html.replace(/\\n/g, '\n');

  // Code blocks (``` ... ```)
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre><code class="lang-${lang || 'text'}">${code.trim()}</code></pre>`;
  });

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Tables (pipe-delimited)
  html = html.replace(/((?:\|[^\n]+\|\n?)+)/g, (tableBlock) => {
    const rows = tableBlock.trim().split('\n').filter(r => r.trim());
    if (rows.length < 2) return tableBlock;

    // Check if second row is separator
    const isSep = /^\|[\s:|-]+\|$/.test(rows[1]?.trim());
    let result = '<table>';

    for (let i = 0; i < rows.length; i++) {
      if (isSep && i === 1) continue; // Skip separator row
      const cells = rows[i].split('|').filter((_, idx, arr) => idx > 0 && idx < arr.length - 1);
      const tag = (isSep && i === 0) ? 'th' : 'td';
      const rowTag = (isSep && i === 0) ? 'thead' : (i === 2 || (!isSep && i === 0) ? 'tbody' : '');
      let rowHtml = '<tr>' + cells.map(c => `<${tag}>${c.trim()}</${tag}>`).join('') + '</tr>';
      if (rowTag === 'thead') rowHtml = `<thead>${rowHtml}</thead><tbody>`;
      if (i === rows.length - 1 && isSep) rowHtml += '</tbody>';
      result += rowHtml;
    }
    return result + '</table>';
  });

  // Headings
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // Bold + italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // Unordered lists
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>[\s\S]*?<\/li>)/g, (match) => {
    if (!match.startsWith('<ul>')) return `<ul>${match}</ul>`;
    return match;
  });
  // Collapse adjacent </ul><ul>
  html = html.replace(/<\/ul>\s*<ul>/g, '');

  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');

  // Horizontal rules
  html = html.replace(/^---+$/gm, '<hr>');

  // Unicode arrows that YouTrack renders nicely
  html = html.replace(/→/g, '→').replace(/←/g, '←');

  // Paragraphs (double newlines)
  html = html.replace(/\n\n+/g, '</p><p>');
  // Single newlines to <br>
  html = html.replace(/\n/g, '<br>');

  // Wrap in <p> if not starting with a block element
  if (!/^<(h[1-6]|pre|table|ul|ol|hr|div)/.test(html)) {
    html = `<p>${html}</p>`;
  }

  return html;
}

/**
 * Render a YouTrack issue page with description and comments.
 */
function renderIssuePage({ issueId, summary, description, comments = [], auditNotes = [] }) {
  const template = fs.readFileSync(TEMPLATE_PATH, 'utf-8');

  const descHtml = markdownToHtml(description || '(no description)');

  let commentsHtml = '';
  for (const c of comments) {
    const date = c.created ? new Date(c.created).toLocaleString('en-GB', {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    }) : '';
    const author = c.author?.name || 'Unknown';
    const textHtml = markdownToHtml(c.text || '');

    commentsHtml += `
      <div class="yt-comment">
        <div class="yt-comment-header">
          <span class="yt-comment-avatar">${author[0]}</span>
          <span class="yt-comment-author">${escapeHtml(author)}</span>
          <span class="yt-comment-date">${escapeHtml(date)}</span>
        </div>
        <div class="yt-comment-body">${textHtml}</div>
      </div>`;
  }

  let notesHtml = '';
  for (const note of auditNotes) {
    notesHtml += `<div class="audit-note">${escapeHtml(note)}</div>`;
  }

  return template
    .replaceAll('{{ISSUE_ID}}', escapeHtml(issueId || ''))
    .replaceAll('{{SUMMARY}}', escapeHtml(summary || ''))
    .replaceAll('{{DESCRIPTION}}', descHtml)
    .replaceAll('{{COMMENTS}}', commentsHtml)
    .replaceAll('{{AUDIT_NOTES}}', notesHtml)
    .replaceAll('{{TIMESTAMP}}', new Date().toISOString());
}

function escapeHtml(str) {
  return (str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

module.exports = { renderIssuePage, markdownToHtml, escapeHtml };
