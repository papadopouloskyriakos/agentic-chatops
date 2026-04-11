#!/bin/bash
# vti-freedom-recovery.sh — Auto-recover Freedom VTI tunnel to GR
#
# Problem: NL ASA has two VTI tunnels to the same GR peer IP (203.0.113.X).
# When IKE SAs reset, xs4all may establish first, blocking Freedom. Since
# xs4all ESP exits via Freedom (BCP38 drop), the data plane is dead and
# BGP can't establish. Freedom VTI (Tunnel4, LP 200) is the primary path.
#
# Fix: When Freedom WAN is UP but Tunnel4 is DOWN, bounce Tunnel1 (xs4all)
# to clear the blocking IKE SA and let Freedom re-negotiate.
#
# Cron: */3 * * * * /app/claude-gateway/scripts/vti-freedom-recovery.sh
#
# Safety:
#   - Only acts when Freedom WAN is UP (outside_freedom has an IP)
#   - Only acts when Tunnel4 is DOWN AND Tunnel1 is UP (the race condition)
#   - No-op when Freedom is DOWN (xs4all failover is working correctly)
#   - No-op when both tunnels are UP (everything healthy)
#   - Cooldown: won't bounce more than once per 10 minutes

set -uo pipefail

REPO_DIR="/app/claude-gateway"
ENV_FILE="$REPO_DIR/.env"
STATE_FILE="/home/app-user/scripts/maintenance-state/vti-freedom-recovery.state"
LOG="/home/app-user/scripts/maintenance-state/vti-freedom-recovery.log"
ASA_IP="10.0.181.X"
ASA_USER="operator"
ASA_PASS=""
COOLDOWN_SECONDS=600

# Load env
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi
ASA_PASS="${CISCO_ASA_PASSWORD:?CISCO_ASA_PASSWORD not set - source .env or set env var}"

mkdir -p "$(dirname "$STATE_FILE")"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [vti-freedom-recovery] $*" >> "$LOG"; }

# Cooldown check — don't bounce more than once per 10 minutes
if [ -f "$STATE_FILE" ]; then
    last_bounce=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    elapsed=$(( now - last_bounce ))
    if [ "$elapsed" -lt "$COOLDOWN_SECONDS" ]; then
        exit 0
    fi
fi

# Maintenance mode check
if [ -f "/home/app-user/gateway.maintenance" ]; then
    exit 0
fi

# Chaos engineering check — don't interfere with active chaos tests
if [ -f "$HOME/chaos-state/chaos-active.json" ]; then
    exit 0
fi

# Gather ASA state: Freedom interface + Tunnel1 + Tunnel4 status
asa_state=$(python3 -c "
import pexpect, sys, json

try:
    child = pexpect.spawn(
        'ssh -o StrictHostKeyChecking=no -o HostKeyAlgorithms=+ssh-rsa '
        '-o PubkeyAcceptedAlgorithms=+ssh-rsa '
        '-o KexAlgorithms=+diffie-hellman-group14-sha1 '
        '${ASA_USER}@${ASA_IP}',
        timeout=15
    )
    child.expect('[Pp]assword:')
    child.sendline('${ASA_PASS}')
    i = child.expect(['[Pp]ermission denied', '>', '#'], timeout=10)
    if i == 0:
        print(json.dumps({'error': 'auth_failed'}))
        sys.exit(0)
    if i == 1:
        child.sendline('enable')
        j = child.expect(['[Pp]assword:', '#'])
        if j == 0: child.sendline('${ASA_PASS}'); child.expect('#')

    child.sendline('terminal pager 0')
    child.expect('#', timeout=5)

    # Check Freedom interface
    child.sendline('show interface outside_freedom | include address')
    child.expect('#', timeout=10)
    freedom_out = child.before.decode() if isinstance(child.before, bytes) else child.before
    freedom_up = 'unassigned' not in freedom_out and '45.138' in freedom_out

    # Check Tunnel1 and Tunnel4
    child.sendline('show interface ip brief | include Tunnel1 |Tunnel4 ')
    child.expect('#', timeout=10)
    tunnel_out = child.before.decode() if isinstance(child.before, bytes) else child.before

    tunnel1_up = False
    tunnel4_up = False
    for line in tunnel_out.split('\n'):
        parts = line.split()
        if len(parts) >= 5:
            if parts[0] == 'Tunnel1' and parts[4] == 'up':
                tunnel1_up = True
            elif parts[0] == 'Tunnel4' and parts[4] == 'up':
                tunnel4_up = True

    child.sendline('exit')
    child.close()

    print(json.dumps({
        'freedom_up': freedom_up,
        'tunnel1_up': tunnel1_up,
        'tunnel4_up': tunnel4_up,
    }))
except Exception as e:
    print(json.dumps({'error': str(e)}))
" 2>/dev/null)

if [ -z "$asa_state" ]; then
    log "ERROR: no response from ASA"
    exit 1
fi

error=$(echo "$asa_state" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',''))" 2>/dev/null)
if [ -n "$error" ]; then
    log "ERROR: $error"
    exit 1
fi

freedom_up=$(echo "$asa_state" | python3 -c "import sys,json; print(json.load(sys.stdin)['freedom_up'])" 2>/dev/null)
tunnel1_up=$(echo "$asa_state" | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnel1_up'])" 2>/dev/null)
tunnel4_up=$(echo "$asa_state" | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnel4_up'])" 2>/dev/null)

# Decision logic
if [ "$tunnel4_up" = "True" ]; then
    # Tunnel4 (Freedom→GR) is UP — everything healthy, nothing to do
    exit 0
fi

if [ "$freedom_up" != "True" ]; then
    # Freedom WAN is DOWN — xs4all failover is correct, don't interfere
    exit 0
fi

if [ "$tunnel1_up" != "True" ]; then
    # Both tunnels down while Freedom is up — different problem, log but don't act
    log "WARN: Freedom UP but both Tunnel1 and Tunnel4 DOWN — investigate manually"
    exit 0
fi

# === RACE CONDITION DETECTED ===
# Freedom is UP, Tunnel4 (Freedom→GR) is DOWN, Tunnel1 (xs4all→GR) is UP
# xs4all IKE SA is blocking Freedom from establishing
log "DETECTED: Freedom UP, Tunnel4 DOWN, Tunnel1 UP — bouncing Tunnel1 to clear IKE SA conflict"

bounce_result=$(python3 -c "
import pexpect, time, sys

try:
    child = pexpect.spawn(
        'ssh -o StrictHostKeyChecking=no -o HostKeyAlgorithms=+ssh-rsa '
        '-o PubkeyAcceptedAlgorithms=+ssh-rsa '
        '-o KexAlgorithms=+diffie-hellman-group14-sha1 '
        '${ASA_USER}@${ASA_IP}',
        timeout=30
    )
    child.expect('[Pp]assword:')
    child.sendline('${ASA_PASS}')
    i = child.expect(['[Pp]ermission denied', '>', '#'], timeout=10)
    if i == 0: print('auth_failed'); sys.exit(0)
    if i == 1:
        child.sendline('enable')
        j = child.expect(['[Pp]assword:', '#'])
        if j == 0: child.sendline('${ASA_PASS}'); child.expect('#')

    # Disable Tunnel1
    child.sendline('configure terminal')
    child.expect('#', timeout=5)
    child.sendline('interface Tunnel1')
    child.expect('#', timeout=5)
    child.sendline('shut' + 'down')
    child.expect('#', timeout=5)
    child.sendline('exit')
    child.expect('#', timeout=5)
    child.sendline('exit')
    child.expect('#', timeout=5)

    # Wait for Freedom IKE to negotiate
    time.sleep(20)

    # Re-enable Tunnel1
    child.sendline('configure terminal')
    child.expect('#', timeout=5)
    child.sendline('interface Tunnel1')
    child.expect('#', timeout=5)
    child.sendline('no shut' + 'down')
    child.expect('#', timeout=5)
    child.sendline('exit')
    child.expect('#', timeout=5)
    child.sendline('exit')
    child.expect('#', timeout=5)

    time.sleep(5)

    # Verify Tunnel4 came up
    child.sendline('show interface ip brief | include Tunnel4')
    child.expect('#', timeout=10)
    out = child.before.decode() if isinstance(child.before, bytes) else child.before
    child.sendline('exit')
    child.close()

    if 'up' in out.lower().split('tunnel4')[1] if 'Tunnel4' in out else '':
        print('OK')
    else:
        print('TUNNEL4_STILL_DOWN')
except Exception as e:
    print('ERROR:' + str(e))
" 2>/dev/null)

# Record bounce timestamp for cooldown
date +%s > "$STATE_FILE"

if [ "$bounce_result" = "OK" ]; then
    log "SUCCESS: Tunnel1 bounced, Tunnel4 (Freedom→GR) recovered"
elif [ "$bounce_result" = "TUNNEL4_STILL_DOWN" ]; then
    log "WARN: Tunnel1 bounced but Tunnel4 still DOWN — may need manual investigation"
else
    log "ERROR: bounce failed — $bounce_result"
fi
