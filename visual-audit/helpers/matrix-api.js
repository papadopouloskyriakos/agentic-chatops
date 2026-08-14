/**
 * Matrix CS API helper — fetches and categorizes bot messages from rooms.
 */
const https = require('https');

const HOMESERVER = 'https://matrix.example.net';
const BOT_USER = '@claude:matrix.example.net';

const ROOMS = {
  'infra-nl': '!AOMuEtXGyzGFLgObKN:matrix.example.net',
  'infra-gr': '!NKosBPujbWMevzHaaM:matrix.example.net',
  'chatops':  '!PVkZvHgyrtBVEbgpRt:matrix.example.net',
  'cubeos':   '!iXTnQsFJahUquYPDdG:matrix.example.net',
  'meshsat':  '!miZJJDwFQZDkuMcBqL:matrix.example.net',
  'alerts':   '!xeNxtpScJWCmaFjeCL:matrix.example.net',
};

const agent = new https.Agent({ rejectUnauthorized: false });

async function fetchJson(url, token) {
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
    agent,
    // Node 20 fetch doesn't support agent directly, use dispatcher workaround
  });
  if (!res.ok) throw new Error(`Matrix API ${res.status}: ${await res.text()}`);
  return res.json();
}

/**
 * Fetch recent messages from a room, filtered to bot sender.
 */
async function fetchRoomMessages(token, roomId, limit = 50) {
  const encoded = encodeURIComponent(roomId);
  const filter = encodeURIComponent(JSON.stringify({ types: ['m.room.message'] }));
  const url = `${HOMESERVER}/_matrix/client/v3/rooms/${encoded}/messages?dir=b&limit=${limit}&filter=${filter}`;

  // Use https module directly since fetch in Node 20 doesn't easily skip TLS
  return new Promise((resolve, reject) => {
    const req = https.get(url, { rejectUnauthorized: false, headers: { Authorization: `Bearer ${token}` } }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          const messages = (json.chunk || [])
            .filter(m => m.sender === BOT_USER)
            .map(m => ({
              eventId: m.event_id,
              sender: m.sender,
              timestamp: m.origin_server_ts,
              msgtype: m.content?.msgtype,
              body: m.content?.body || '',
              format: m.content?.format,
              formatted_body: m.content?.formatted_body || '',
              pollStart: m.content?.['org.matrix.msc3381.poll.start'],
            }));
          resolve(messages);
        } catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
  });
}

/**
 * Categorize a message by its content patterns.
 */
function categorize(msg) {
  const { body, msgtype, pollStart } = msg;
  if (pollStart) return 'poll';
  if (/\[LibreNMS\]/.test(body)) return 'librenms-alert';
  if (/\[Prometheus\]/.test(body)) return 'prometheus-alert';
  if (/\[CrowdSec\]/.test(body)) return 'crowdsec-alert';
  if (/\[Security\]/.test(body)) return 'security-finding';
  if (/\[Synology\]/.test(body)) return 'synology-alert';
  if (/WAL.*heal/i.test(body)) return 'wal-healer';
  if (/Working\.\.\. \(\d+m/.test(body)) return 'progress';
  if (/Starting session for/.test(body)) return 'session-start';
  if (/Claude is busy/.test(body)) return 'busy-notice';
  if (/Claude.*\(\d+m\d+s\):/.test(body)) return 'session-result';
  if (/@openclaw.*exec tool/.test(body)) return 'triage-delegation';
  if (/use the exec tool/.test(body)) return 'triage-delegation';
  if (msgtype === 'm.notice') return 'notice';
  return 'other';
}

/**
 * Fetch and categorize messages from all rooms.
 * Returns: { roomName: { category: [messages] } }
 */
async function fetchAllRooms(token) {
  const result = {};
  for (const [name, roomId] of Object.entries(ROOMS)) {
    try {
      const messages = await fetchRoomMessages(token, roomId, 50);
      const categorized = {};
      for (const msg of messages) {
        const cat = categorize(msg);
        if (!categorized[cat]) categorized[cat] = [];
        categorized[cat].push(msg);
      }
      result[name] = categorized;
    } catch (err) {
      console.error(`Failed to fetch ${name}: ${err.message}`);
      result[name] = {};
    }
  }
  return result;
}

module.exports = { fetchRoomMessages, fetchAllRooms, categorize, ROOMS, BOT_USER };
