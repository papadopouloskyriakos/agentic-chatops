// Node-runnable smoke test for chaos.js's tunnelLabel() canonical-order fix.
// Does NOT need a browser. Run with: node visual-audit/tests/chaos-tunnel-label.unit.js
//
// Mirrors the in-IIFE state of chaos.js so we can exercise tunnelLabel() in
// isolation. The two pieces under test:
//
//   1. SITE_ORDER fallback: when neither direction is in TUNNEL_WAN, return
//      the deterministic NL-first canonical form (matches CHAOS_TUNNELS).
//   2. CHAOSABLE_TUNNELS allowlist: ASA-terminated pairs are listed, inter-VPS
//      swanctl pairs (CH↔NO-DMZ02 etc.) are not.
//
// Live data 2026-05-06 19:13 UTC: operator clicked NL↔NO-DMZ01 + CH↔NO-DMZ02,
// the OLD tunnelLabel reversed the first to "NO-DMZ01 ↔ NL" and the second to
// "NO-DMZ02 ↔ CH", neither of which is a CHAOS_TUNNELS key. tunnel_infos came
// out empty, the chaos run lasted 600s with zero red links painted. The fix
// has to make case 1 produce "NL ↔ NO-DMZ01" (matches CHAOS_TUNNELS) and case
// 2 produce "CH ↔ NO-DMZ02" + reject via the allowlist.

'use strict';

const TUNNEL_WAN = {
  'NL ↔ GR': 'freedom', 'NL ↔ NO': 'freedom', 'NL ↔ CH': 'freedom',
  'GR ↔ NO': 'inalan', 'GR ↔ CH': 'inalan', 'NO ↔ CH': 'vps',
  'GR ↔ NL': 'freedom', 'NO ↔ NL': 'freedom', 'CH ↔ NL': 'freedom',
  'NO ↔ GR': 'inalan', 'CH ↔ GR': 'inalan', 'CH ↔ NO': 'vps',
};
const SITE_ORDER = ['NL', 'GR', 'NO', 'CH', 'TX', 'NO-DMZ01', 'NO-DMZ02'];
const CHAOSABLE_TUNNELS = {
  'NL ↔ GR': 1, 'NL ↔ NO': 1, 'NL ↔ CH': 1, 'NL ↔ TX': 1,
  'NL ↔ NO-DMZ01': 1, 'NL ↔ NO-DMZ02': 1,
  'GR ↔ NO': 1, 'GR ↔ CH': 1, 'GR ↔ TX': 1,
  'GR ↔ NO-DMZ01': 1, 'GR ↔ NO-DMZ02': 1,
  'NO ↔ CH': 1,
};

function tunnelLabel(src, tgt) {
  const fwd = src + ' ↔ ' + tgt;
  if (TUNNEL_WAN[fwd]) return fwd;
  const rev = tgt + ' ↔ ' + src;
  if (TUNNEL_WAN[rev]) return rev;
  let srcIdx = SITE_ORDER.indexOf(src); if (srcIdx < 0) srcIdx = 999;
  let tgtIdx = SITE_ORDER.indexOf(tgt); if (tgtIdx < 0) tgtIdx = 999;
  return srcIdx <= tgtIdx ? fwd : rev;
}

const cases = [
  // Legacy 4-site pairs (TUNNEL_WAN listed both directions).
  ['NL', 'GR', 'NL ↔ GR'],
  ['GR', 'NL', 'GR ↔ NL'],   // legacy reverse-key path
  ['NO', 'CH', 'NO ↔ CH'],
  ['CH', 'NO', 'CH ↔ NO'],
  // New pairs (NOT in TUNNEL_WAN — must hit SITE_ORDER fallback).
  ['NL', 'TX', 'NL ↔ TX'],
  ['TX', 'NL', 'NL ↔ TX'],
  ['GR', 'TX', 'GR ↔ TX'],
  ['TX', 'GR', 'GR ↔ TX'],
  ['NL', 'NO-DMZ01', 'NL ↔ NO-DMZ01'],
  ['NO-DMZ01', 'NL', 'NL ↔ NO-DMZ01'],
  ['NL', 'NO-DMZ02', 'NL ↔ NO-DMZ02'],
  ['NO-DMZ02', 'NL', 'NL ↔ NO-DMZ02'],
  ['GR', 'NO-DMZ01', 'GR ↔ NO-DMZ01'],
  ['NO-DMZ01', 'GR', 'GR ↔ NO-DMZ01'],
  // Inter-VPS swanctl pairs (NOT chaosable — but tunnelLabel still needs to
  // produce a deterministic order so the allowlist lookup is stable).
  ['CH', 'NO-DMZ02', 'CH ↔ NO-DMZ02'],
  ['NO-DMZ02', 'CH', 'CH ↔ NO-DMZ02'],
];

let pass = 0; let fail = 0;
for (const [src, tgt, want] of cases) {
  const got = tunnelLabel(src, tgt);
  if (got === want) { pass++; }
  else { fail++; console.error(`  FAIL tunnelLabel(${src}, ${tgt}) -> "${got}" (expected "${want}")`); }
}
console.log(`tunnelLabel: ${pass}/${cases.length} pass, ${fail} fail`);

// Allowlist contract.
const allow = [
  ['NL ↔ NO-DMZ01', true],
  ['GR ↔ TX', true],
  ['NO ↔ CH', true],
  ['CH ↔ NO-DMZ02', false],
  ['NO-DMZ02 ↔ CH', false],
  ['NO-DMZ01 ↔ NO-DMZ02', false],
];
let aPass = 0; let aFail = 0;
for (const [label, want] of allow) {
  const got = !!CHAOSABLE_TUNNELS[label];
  if (got === want) { aPass++; }
  else { aFail++; console.error(`  FAIL CHAOSABLE_TUNNELS["${label}"] -> ${got} (expected ${want})`); }
}
console.log(`CHAOSABLE_TUNNELS: ${aPass}/${allow.length} pass, ${aFail} fail`);

if (fail || aFail) { process.exit(1); }
