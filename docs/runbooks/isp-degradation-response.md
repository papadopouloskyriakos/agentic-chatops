# Runbook: ISP Degradation Response

**Runbook ID:** RB-ISP-001
**Last Updated:** 2026-04-14
**Exercise Program Reference:** docs/exercise-program.md
**Automation:** scripts/chaos_baseline.py isp-test (tc netem injection)

---

## 1. Overview

This runbook covers procedures for ISP degradation simulation exercises using Linux `tc netem` to inject latency and packet loss on WAN-facing interfaces. These exercises validate that BGP sessions remain stable under degraded conditions and that HTTP services degrade gracefully rather than failing completely.

Unlike tunnel failover exercises (which kill tunnels entirely), ISP degradation exercises simulate real-world ISP quality issues: increased latency, jitter, and packet loss. These conditions are more common than full outages and can cause subtle service degradation.

---

## 2. Trigger Conditions

This runbook is used when:
- Quarterly ISP degradation exercise (offset week after quarterly DMZ drill)
- Combined game day ISP component
- Ad-hoc validation after ISP changes or WAN failover events
- Post-incident analysis of ISP quality issues

---

## 3. Scenarios

### 3.1 Latency Injection -- 200ms

**Target:** WAN interface on nlasa01 (Freedom outside interface)
**Method:** `tc qdisc add dev <iface> root netem delay 200ms 20ms` (200ms +/- 20ms jitter)
**Impact:** Noticeable latency increase, BGP timers should hold, HTTP slower but functional

#### Pre-checks

1. Verify current baseline latency to VPS endpoints:
   ```
   ping -c 5 198.51.100.X
   ping -c 5 198.51.100.X
   ```
2. Verify BGP peer count >= 22
3. Verify HTTP response times are within normal range (< 500ms)
4. Verify SSH access to injection point

#### Injection

```
# On the injection host (not directly on ASA -- use a Linux host on the path):
sudo tc qdisc add dev <wan-iface> root netem delay 200ms 20ms
```

Injection duration: 120 seconds, then remove:
```
sudo tc qdisc del dev <wan-iface> root
```

#### Expected Behavior

1. **0-5s:** Latency increases to ~200ms on affected path
2. **5-30s:** BGP keepalives still arrive within hold timer (default 90s) -- sessions stay UP
3. **10-60s:** HTTP responses slow to ~700-900ms but return 200
4. **60-120s:** Steady degraded state, no session drops
5. **After removal:** Latency returns to baseline within 5 seconds

#### Validation

<!-- VALIDATE: bgp_established >= 20 within 10s -->
BGP sessions must remain established throughout the injection. No session should drop. Peer count stays >= 20 continuously.

<!-- VALIDATE: http_latency_p95 < 1000 within 30s -->
HTTP response time p95 must stay below 1000ms. Services are slower but functional.

---

### 3.2 Latency Injection -- 500ms

**Target:** WAN interface, Freedom path
**Method:** `tc qdisc add dev <iface> root netem delay 500ms 50ms`
**Impact:** Significant latency, BGP under stress but should hold, HTTP noticeably degraded

#### Pre-checks

Same as 3.1.

#### Injection

```
sudo tc qdisc add dev <wan-iface> root netem delay 500ms 50ms
```

Duration: 120 seconds.

#### Expected Behavior

1. **0-5s:** Latency jumps to ~500ms
2. **5-30s:** BGP keepalives delayed but still within hold timer -- sessions hold
3. **10-60s:** HTTP responses at ~1000-1500ms, some timeouts possible
4. **60-120s:** Steady degraded state
5. **After removal:** Immediate recovery

#### Validation

<!-- VALIDATE: bgp_established >= 20 within 10s -->
BGP sessions remain established. Hold timer (90s) is well above 500ms RTT.

<!-- VALIDATE: http_latency_p95 < 1000 within 30s -->
HTTP p95 may exceed 1000ms during injection but should recover within 30 seconds of removal.

---

### 3.3 Latency Injection -- 1000ms

**Target:** WAN interface, Freedom path
**Method:** `tc qdisc add dev <iface> root netem delay 1000ms 100ms`
**Impact:** Severe latency, BGP may flap if combined with loss, HTTP heavily degraded

#### Pre-checks

Same as 3.1. Additionally:
- Verify BGP hold timer is set to 90s (default) -- 1000ms RTT will not trigger timeout alone
- Confirm no other fault injection is active

#### Injection

```
sudo tc qdisc add dev <wan-iface> root netem delay 1000ms 100ms
```

Duration: 120 seconds.

#### Expected Behavior

1. **0-5s:** Latency at ~1000ms
2. **5-30s:** BGP keepalives heavily delayed but still within hold timer
3. **10-60s:** HTTP largely unusable (2-3s per request), timeouts likely
4. **60-120s:** BGP should remain established but fragile
5. **After removal:** Recovery within 10 seconds

#### Validation

<!-- VALIDATE: bgp_established >= 20 within 10s -->
BGP sessions should survive 1000ms latency alone (hold timer = 90s). If sessions drop, this indicates hold timer tuning is needed.

<!-- VALIDATE: http_latency_p95 < 1000 within 30s -->
After injection removal, HTTP p95 must return below 1000ms within 30 seconds.

---

### 3.4 Packet Loss Injection -- 5%

**Target:** WAN interface, Freedom path
**Method:** `tc qdisc add dev <iface> root netem loss 5%`
**Impact:** Minor packet loss, TCP retransmits increase, BGP unaffected, HTTP slightly slower

#### Pre-checks

Same as 3.1.

#### Injection

```
sudo tc qdisc add dev <wan-iface> root netem loss 5%
```

Duration: 120 seconds.

#### Expected Behavior

1. **0-5s:** 5% of packets dropped
2. **5-30s:** TCP retransmits absorb the loss, BGP keepalives get through (95% chance per packet)
3. **10-60s:** HTTP latency increases slightly due to retransmits (~10-20% slower)
4. **60-120s:** Stable degraded state
5. **After removal:** Immediate recovery

#### Validation

<!-- VALIDATE: bgp_established >= 20 within 10s -->
BGP completely unaffected by 5% loss. All sessions remain established.

<!-- VALIDATE: http_latency_p95 < 1000 within 30s -->
HTTP p95 stays well under 1000ms. TCP retransmits handle the loss transparently.

---

### 3.5 Packet Loss Injection -- 10%

**Target:** WAN interface, Freedom path
**Method:** `tc qdisc add dev <iface> root netem loss 10%`
**Impact:** Moderate packet loss, noticeable retransmits, BGP should hold, HTTP degrades

#### Pre-checks

Same as 3.1.

#### Injection

```
sudo tc qdisc add dev <wan-iface> root netem loss 10%
```

Duration: 120 seconds.

#### Expected Behavior

1. **0-5s:** 10% packet loss begins
2. **5-30s:** BGP keepalives may miss occasionally but hold timer (90s) absorbs it
3. **10-60s:** HTTP response times increase 30-50% due to retransmits
4. **60-120s:** Stable but noticeably degraded
5. **After removal:** Recovery within 5 seconds

#### Validation

<!-- VALIDATE: bgp_established >= 20 within 10s -->
BGP sessions survive 10% loss. Keepalives are small packets with high retransmit priority.

<!-- VALIDATE: http_latency_p95 < 1000 within 30s -->
HTTP p95 remains under 1000ms during injection.

---

### 3.6 Packet Loss Injection -- 25%

**Target:** WAN interface, Freedom path
**Method:** `tc qdisc add dev <iface> root netem loss 25%`
**Impact:** Severe packet loss, BGP under significant stress, HTTP heavily degraded

#### Pre-checks

Same as 3.1. Additionally:
- Confirm backup ISP path (xs4all) is healthy -- if BGP flaps, traffic needs to failover
- Confirm no other fault injection active

#### Injection

```
sudo tc qdisc add dev <wan-iface> root netem loss 25%
```

Duration: 120 seconds.

#### Expected Behavior

1. **0-5s:** 25% packet loss begins
2. **5-30s:** BGP keepalives have 75% per-packet delivery rate -- multiple consecutive keepalives may be lost
3. **10-60s:** HTTP severely degraded, many requests timeout
4. **30-90s:** BGP may flap if 3+ consecutive keepalives are lost (probability ~1.5% per interval)
5. **After removal:** Full recovery within 30 seconds

This is a stress test. DEGRADED (1-2 BGP flaps that recover) is an acceptable outcome. FAIL only if sessions drop permanently or require manual intervention.

#### Validation

<!-- VALIDATE: bgp_established >= 20 within 10s -->
BGP sessions should remain established, though 1-2 brief flaps are acceptable at 25% loss.

<!-- VALIDATE: http_latency_p95 < 1000 within 30s -->
After removal, HTTP p95 must return below 1000ms within 30 seconds.

---

## 4. Emergency Abort Procedure

If ISP degradation injection causes unexpected issues:

1. **Immediate removal:**
   ```
   sudo tc qdisc del dev <wan-iface> root
   ```
2. **Verify removal:** `tc qdisc show dev <wan-iface>` should show only `pfifo_fast` or `fq_codel`
3. **If BGP sessions dropped:** Wait for auto-recovery (BGP reconnect timer). Do NOT clear BGP on VPS.
4. **If tc command fails:** Reboot the injection host as last resort (tc rules are not persistent)

**CRITICAL:** NEVER run `clear bgp *` or restart FRR on VPS hosts. BGP sessions will auto-recover once the degradation is removed.

---

## 5. Combined Degradation Scenarios

For combined game days, latency and loss may be injected simultaneously:

```
sudo tc qdisc add dev <wan-iface> root netem delay 200ms 20ms loss 5%
```

This simulates realistic ISP degradation where both latency and loss increase together. The same validation markers apply.

---

## 6. Post-Exercise Checklist

1. All `tc netem` rules removed: `tc qdisc show` shows no netem entries
2. BGP peer count back to >= 22
3. HTTP latency returned to baseline (< 500ms p95)
4. No lingering TCP retransmit backlog
5. Prometheus latency metrics normalizing
6. LibreNMS shows no alerts for WAN interfaces
7. VPN tunnel status all UP via `vpn-mesh-stats.py`

---

## 7. Appendix: ISP Path Reference

| ISP | Sites | WAN Interface | Baseline Latency | BGP Hold Timer |
|-----|-------|---------------|-------------------|----------------|
| Freedom | NL | outside_freedom | ~5ms to VPS | 90s |
| xs4all | NL | outside_xs4all | ~8ms to VPS | 90s |
| Inalan | GR | outside_inalan | ~35ms to VPS | 90s |
