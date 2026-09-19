# Runbook — Headless Intel AMT console (KVM) from nl-claude01

**Purpose:** get a *keyboard-and-screen* console on a PVE host that is off-network (emergency mode, wedged boot, broken networking) when you have no browser and no physical access.

**Applies to:** the three AMT hosts — `nlamt01` (10.0.181.X → nl-pve01), `nlamt02` (10.0.181.X → nl-pve03), `gramt01` (10.0.X.X → gr-pve01). Credentials: memory `amt_oob_access_all_sites_20260806` — never ask the operator.

Proven end-to-end on **gr-pve01, 2026-08-25** (repaired a boot-blocking fstab entry entirely through this path). See IFRGRSKG01PRD-312.

---

## 1. Which transport does this host have?

| Generation | KVM transport | Tool |
|---|---|---|
| AMT ≤ 15 | "KVM on standard port 5900" can be enabled → **real VNC** | any VNC client |
| **AMT 16+** (MS-01 / 12th-gen and newer) | **5900 feature REMOVED** — only Intel redirection on **16994 (plain) / 16995 (TLS)** | the bridge below, or MeshCommander/MeshCentral |

Check before assuming:

```bash
# from a host on the same LAN as the AMT NIC
for p in 16992 16993 16994 16995 5900; do timeout 3 bash -c "echo > /dev/tcp/<amt-ip>/$p" 2>/dev/null \
  && echo "$p OPEN" || echo "$p closed"; done
```

On AMT 16 a WS-Man `Put` of `IPS_KVMRedirectionSettingData.Is5900PortEnabled=true` returns **"The specified feature is not supported."** — that is the definitive tell. Do not keep trying to enable VNC.

> **TLS gotcha (all generations):** these AMT stacks need legacy renegotiation. OpenSSL 3 curl fails with `unsafe legacy renegotiation disabled` and exit code `000` *even though the port is open*. Export an `OPENSSL_CONF` containing `Options = UnsafeLegacyRenegotiation` and `CipherString = DEFAULT@SECLEVEL=0`.

---

## 2. Redirection → local VNC bridge (the AMT 16+ path)

`nomis/intel-amt` implements the redirection protocol (StartRedirectionSession → digest auth → `KVMR` → raw RFB passthrough). Bridge it to a local TCP port and use **any** VNC client.

```bash
git clone --depth 1 https://github.com/nomis/intel-amt.git
python3 -m venv venv && ./venv/bin/pip install requests pem appdirs vncdotool
```

Bridge (`amt-kvm-bridge.py` — full copy in the 2026-08-25 session scratchpad; ~50 lines):

```python
import amt.client, socket, ssl, os
def patched_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    ctx.options |= 0x4                      # OP_LEGACY_SERVER_CONNECT (constant absent in this python)
    ctx.set_ciphers('DEFAULT@SECLEVEL=0')
    return ctx
client = amt.client.Client(AMT_HOST, AMT_PASS, username=AMT_USER, protocol='https')
# listen on 127.0.0.1:5901; per connection:
kvm = amt.client.KVMClient(client, conn); kvm.context = patched_context()
with kvm: kvm.start(); kvm.loop()
```

Then drive it with plain CLI:

```bash
./venv/bin/vncdo -s 127.0.0.1::5901 capture screen.png
./venv/bin/vncdo -s 127.0.0.1::5901 type "systemctl default" key enter
```

### Two quirks that WILL bite you

1. **A fresh redirection session eats the first keystrokes.** Send a warm-up key and pause *before* typing, or your command arrives truncated (`tc/fstab` instead of `cat /etc/fstab` — silently wrong, not an error).
2. **The first framebuffer capture of a session is stale.** Capture twice and keep the second. An all-black capture usually means the console blanked — wake it with a key first.

Wrapper that handles both (`kvmcmd.sh "<command>" [out.png] [wait]`):

```bash
timeout 120 "$V" -s 127.0.0.1::5901 \
  key ctrl pause 3 \
  type "$CMD" key enter pause "${WAIT:-3}" \
  capture /tmp/.stale.png pause 1 capture "$OUT"
```

---

## 3. Fallback: MeshCentral web UI (10.0.181.X)

If the bridge is unavailable, MeshCentral speaks the same protocol. Headless, drive it with Playwright (env at `~/meshsat-e2e/node_modules/playwright`):

- **Login:** `page.fill` leaves `#loginButton` **disabled** — you must `keyboard.type()` then `Enter` (it enables on real key events).
- AMT-only nodes carry no `gotoDevice` onclick in the grid — click by text: `page.click('text=gramt01')`.
- Desktop tab ≈ `page.mouse.click(240, 78)`, then `#connectbutton1h` ("HW Connect"); canvas focus = click ~(800, 500).
- ⛔ **Never type passwords onto the canvas** — synthetic canvas keys mangle special characters (a correct password failed twice). Use the **Type dialog**: `#DeskType` → `page.fill('#d2typeText', pw)` → `#idx_dlgOkButton`. The dialog **auto-closes after OK — reopen `#DeskType` before every fill.**

---

## 4. Power operations (read-only status + cycle)

WS-Man over curl, no meshcmd needed. `CIM_AssociatedPowerManagementService` ignores `OptimizeEnumeration`, so **Enumerate then Pull**:

```
PowerState: 2 = On · 8 = Off-Soft · 5 = Cycle-Off-Soft
```

⚠ Off-opcodes are **not** universal: `nlamt02` refuses 5/6/8/9 (`rc=2`, Standard Manageability). `gramt01` accepts them (proven 2026-08-25). Probe before promising a remote cold-cycle. `rc=2` on an "On" op while the host is already on is ambiguous — verify via console/ping, never infer.

Cold-cycle playbook for a wedged host: **Off → wait 30 s (drain) → On**. A warm reset does not clear a wedged NVMe controller.

### ⚠ AMT goes DARK in S5 on the MS-01 — two consequences (confirmed 2026-08-27, gramt01)

Once `gr-pve01` reaches S5, AMT stops answering entirely (it reports `PowerState=2` while the host runs, then `NO-ANSWER`). Operator confirms this is expected on this hardware. Therefore:

1. **"AMT stops answering" is NOT a valid proof-of-cut** for a PDU drain — it is already silent before you cut. Rely on the PDU's own `State: OFF` plus an outlet **name-match guard**.
2. **There is no remote wake path from powered-off** — `RequestPowerStateChange PowerState=2` cannot reach a dark AMT. Return depends entirely on the board's *restore on AC power loss* BIOS setting, which is **not remotely readable**. On gr-pve01 it **is** enabled (proven: AMT back ~50 s after AC restore, host ping ~60 s, SSH ~110 s). **Confirm this per-host before cutting power**, or accept that a failure to resume means a physical visit.

⇒ For an AC drain aimed at reviving a wedged NVMe, follow [`pve-nvme-cold-drain-recovery.md`](pve-nvme-cold-drain-recovery.md) — S5 alone was **not** sufficient on this host; only full AC removal worked.

---

## 5. After you get the console — the classic trap

If the host booted into **emergency mode**, fixing the blocker and continuing (`systemctl default` / Ctrl-D) leaves it **half-initialised**: the cancelled sysinit jobs are never re-queued. `systemctl is-system-running` will happily report `running` with **0 failed units** while dbus, lxcfs, pve-lxc-syscalld and qmeventd are all dead — and every guest start then fails.

```bash
# detect in one command — compare against a healthy peer
systemctl list-units --type=service --state=running --no-legend | wc -l
```

17 vs 56 on the peer ⇒ **reboot** (`shutdown -r now`; ⛔ `systemctl reboot` fails with dbus down). Details: [[feedback_reboot_after_emergency_mode_boot]].

Post-emergency guest restore: `pve-guests.service` and `pve-manager.service` both carry `RefuseManualStart=true`. Use the API they call internally:

```bash
setsid nohup pvesh create /nodes/localhost/startall > /tmp/startall.log 2>&1 < /dev/null &
```

(A plain `nohup … &` over SSH dies with the session.)

---

## 6. Field notes — nlamt01, 2026-09-19

- The 08-25 bridge script hardcodes `AMT_HOST` and port 5901. Parametrise both. A stale 08-25 bridge process may still hold `127.0.0.1:5901`; pick another port rather than killing a process you didn't start.
- Logging in on the console with `vncdo type root` / `type '<AMT password>'` (it contains `@` and `!`) **worked** on nlamt01 through this bridge. The special-character mangling in §3 is specific to MeshCentral's canvas path.
- The `kvmcmd.sh` wrapper's `timeout 120` includes typing time plus the wait, so long commands lose their capture. For long jobs, redirect output to a file on the host, then capture separately.
- Finish with `exit` on the console (don't leave root logged in) and stop the bridge **by PID**. `pkill -f amt-kvm-bridge.py` from a shell whose command line contains that string kills the shell itself.

## 7. Hardening (proposed, not yet implemented)

Add a **SOL serial getty** (`console=ttyS…` on the AMT COM port in GRUB) plus an sshd-in-rescue override, so the next incident is reachable with a plain CLI terminal (`meshcmd amtterminal`) and no KVM at all.
