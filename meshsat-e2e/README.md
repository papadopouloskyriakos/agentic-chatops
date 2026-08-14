# MeshSat E2E Tests

Playwright-based end-to-end test suite for the MeshSat dashboard.

## Requirements
- Node.js 18+
- Playwright
- Access to nl-mule01-wireless LAN

## Run
```bash
cd meshsat-e2e && npm install && npx playwright install chromium --with-deps
npx playwright test
```

## Target
http://nl-mule01-wireless:6050 (no auth)

## Tests

### `tests/meshsat.spec.js`
54 tests across 5 categories:

**Navigation (13 tests)**
- Dashboard loads with correct title
- All 11 nav links present and clickable
- Each page loads without JS errors or network failures

**Frontend Integrity (11 tests)**
- Key widgets visible on dashboard (Iridium, Mesh, Cellular, Queue, Activity)
- No garbage text ([object Object], isolated "undefined"/"null")
- Page headings visible on all views

**Responsive (3 tests)**
- Dashboard, Comms, Interfaces at mobile viewport (390x844)

**Backend API (21 tests)**
- Health endpoint, status, gateways, nodes, messages
- Cellular: status, SMS, data status
- Iridium: queue, scheduler
- Interfaces, access-rules, object-groups, deliveries
- Transport channels, config, audit, locations, zigbee, presets

**Error Detection (6 tests)**
- No console.error() on dashboard, messages, bridge, interfaces, settings
- No broken asset requests (404s)

### `tests/functional.spec.js`
66 tests across 10 categories:

**Dashboard Widgets (8 tests)**
- Iridium, Mesh, Cellular widget content verification
- Signal bars display, signal graph with real data
- Message queue, activity log, location widgets

**Messages View (8 tests)**
- All 5 tabs (Mesh, SBD, SMS, Broadcasts, Webhooks)
- SMS quick-send form, message history, contacts quick-dial

**Peers View (4 tests)**
- Node list, filter buttons (All/Active/Stale), SMS contacts tab

**Bridge View (5 tests)**
- Gateway status cards, bridge tabs, deliveries, queue compose

**Interfaces View (5 tests)**
- Interface cards, Access Rules, Devices tab (USB detection)

**Passes View (6 tests)**
- Constellation tabs, time window, elevation controls, SVG chart

**Map View (3 tests)**
- Map page with layers panel, tile loading, theme toggle

**Settings View (5 tests)**
- Iridium, Cellular, MQTT, Export/Import settings tabs

**Audit View (4 tests)**
- Audit log, verify chain button, signer info toggle

**Data Consistency (5 tests)**
- API ↔ widget cross-checks (gateways, nodes, cellular, scheduler, interfaces)

**Real-time Updates (2 tests)**
- SSE events endpoint, activity log updates

**Error Handling (4 tests)**
- Invalid endpoints, validation errors, console error sweep, rapid tab switching

**Backend API Functional (5 tests)**
- Transport channels structure, config, signal history, message stats, locations

### SMS Send Tests (in meshsat.spec.js)
2 tests — sends real SMS (excluded from default run):
- UI-driven SMS send via dashboard
- Direct API SMS send

Run SMS tests explicitly:
```bash
npx playwright test --grep "SMS Send"
```

## Discovery Script
`discover.js` crawls all pages and records API endpoints. Run with:
```bash
node discover.js
```
