#!/bin/bash
# freedom-qos-toggle.sh — Toggle tenant QoS based on Freedom PPPoE status
# Runs via cron every 2 minutes. When Freedom is down, applies 5/2 Mbps
# QoS to tenant rooms (b,c,d) to protect xs4all bandwidth.
# When Freedom recovers, removes the QoS limits.
#
# Cron: */2 * * * * /app/claude-gateway/scripts/freedom-qos-toggle.sh

set -uo pipefail

REPO_DIR="/app/claude-gateway"
ENV_FILE="$REPO_DIR/.env"
STATE_FILE="/home/app-user/scripts/maintenance-state/freedom-qos.state"
LOG_TAG="[freedom-qos]"
ASA_IP="10.0.181.X"
ASA_USER="operator"
ASA_PASS=""

# Load env
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi
ASA_PASS="${CISCO_ASA_PASSWORD:?CISCO_ASA_PASSWORD not set - source .env or set env var}"

mkdir -p "$(dirname "$STATE_FILE")"

# Send SMS via Twilio
send_sms() {
    local msg="$1"
    local acct="${TWILIO_ACCOUNT_SID:-}"
    local key="${TWILIO_API_KEY_SID:-}"
    local secret="${TWILIO_API_KEY_SECRET:-}"
    local from="${TWILIO_FROM_NUMBER:-}"
    local to="${TWILIO_TO_NUMBER:-}"
    [ -z "$acct" ] || [ -z "$key" ] || [ -z "$to" ] && return 1
    curl -s -X POST "https://api.twilio.com/2010-04-01/Accounts/${acct}/Messages.json" \
        -u "${key}:${secret}" \
        -d "From=${from}" \
        -d "To=${to}" \
        -d "Body=${msg}" > /dev/null 2>&1
}

# Check Freedom PPPoE status via ASA
check_freedom() {
    local result
    result=$(python3 -c "
import pexpect, sys
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
if i == 0: print('ERROR'); sys.exit(1)
if i == 1:
    child.sendline('enable')
    j = child.expect(['[Pp]assword:', '#'])
    if j == 0: child.sendline('${ASA_PASS}'); child.expect('#')
child.sendline('show interface outside_freedom | include address')
child.expect('#', timeout=10)
output = child.before.decode()
child.sendline('exit')
child.close()
if 'unassigned' in output:
    print('DOWN')
else:
    print('UP')
" 2>/dev/null)
    echo "$result"
}

# Apply QoS policies
apply_qos() {
    python3 -c "
import pexpect
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
if i == 0: exit(1)
if i == 1:
    child.sendline('enable')
    j = child.expect(['[Pp]assword:', '#'])
    if j == 0: child.sendline('${ASA_PASS}'); child.expect('#')
child.sendline('conf t')
child.expect('#', timeout=5)
child.sendline('service-policy XS4ALL-ROOM-B-PM interface inside_room_b')
child.expect('#', timeout=5)
child.sendline('service-policy XS4ALL-ROOM-C-PM interface inside_room_c')
child.expect('#', timeout=5)
child.sendline('service-policy XS4ALL-ROOM-D-PM interface inside_room_d')
child.expect('#', timeout=5)
child.sendline('end')
child.expect('#', timeout=5)
child.sendline('exit')
child.close()
" 2>/dev/null
}

# Remove QoS policies
remove_qos() {
    python3 -c "
import pexpect
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
if i == 0: exit(1)
if i == 1:
    child.sendline('enable')
    j = child.expect(['[Pp]assword:', '#'])
    if j == 0: child.sendline('${ASA_PASS}'); child.expect('#')
child.sendline('conf t')
child.expect('#', timeout=5)
child.sendline('no service-policy XS4ALL-ROOM-B-PM interface inside_room_b')
child.expect('#', timeout=5)
child.sendline('no service-policy XS4ALL-ROOM-C-PM interface inside_room_c')
child.expect('#', timeout=5)
child.sendline('no service-policy XS4ALL-ROOM-D-PM interface inside_room_d')
child.expect('#', timeout=5)
child.sendline('end')
child.expect('#', timeout=5)
child.sendline('exit')
child.close()
" 2>/dev/null
}

# Log ONT health metrics (BNG latency + switch port errors) for trend detection
log_ont_health() {
    local metrics_file="/var/lib/node_exporter/textfile_collector/freedom_ont.prom"
    # Get BNG ping latency from ASA SLA monitor
    local sla_rtt
    sla_rtt=$(python3 -c "
import pexpect, sys
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
if i == 0: sys.exit(1)
if i == 1:
    child.sendline('enable')
    j = child.expect(['[Pp]assword:', '#'])
    if j == 0: child.sendline('${ASA_PASS}'); child.expect('#')
child.sendline('show sla monitor operational-state 1 | include Latest RTT')
child.expect('#', timeout=10)
output = child.before.decode()
child.sendline('exit')
child.close()
for line in output.splitlines():
    if 'Latest RTT' in line and ':' in line:
        val = line.split(':')[-1].strip()
        try: print(int(val))
        except: print('-1')
        break
" 2>/dev/null)
    # Get switch port CRC errors for Gi1/0/36
    local crc_errors
    crc_errors=$(python3 -c "
import pexpect, sys
child = pexpect.spawn(
    'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 '
    '-o Ciphers=aes128-ctr,aes256-ctr '
    '-o HostKeyAlgorithms=+ssh-rsa '
    '-o KexAlgorithms=diffie-hellman-group14-sha1 '
    '-o PubkeyAcceptedAlgorithms=+ssh-rsa '
    'operator@10.0.181.X',
    timeout=15
)
child.expect('[Pp]assword:')
child.sendline('${ASA_PASS}')
i = child.expect(['>', '#', '[Pp]assword:', pexpect.TIMEOUT], timeout=15)
if i not in [0,1]: sys.exit(1)
child.sendline('show interface Gi1/0/36 | include CRC|errors|drops')
child.expect('#', timeout=10)
output = child.before.decode()
child.sendline('exit')
child.close()
for line in output.splitlines():
    if 'input errors' in line:
        parts = line.strip().split()
        try: print(parts[0])
        except: print('0')
        break
" 2>/dev/null)
    # Write Prometheus metrics
    if [ -d "$(dirname "$metrics_file")" ]; then
        cat > "$metrics_file" <<PROM
# HELP freedom_bng_rtt_ms RTT to Freedom BNG gateway in milliseconds
# TYPE freedom_bng_rtt_ms gauge
freedom_bng_rtt_ms ${sla_rtt:--1}
# HELP freedom_ont_port_errors Total input errors on sw01 Gi1/0/36 (ONT port)
# TYPE freedom_ont_port_errors counter
freedom_ont_port_errors ${crc_errors:-0}
# HELP freedom_pppoe_up Freedom PPPoE session status (1=up, 0=down)
# TYPE freedom_pppoe_up gauge
freedom_pppoe_up $([ "$1" = "UP" ] && echo 1 || echo 0)
PROM
    fi
}

# Main logic
current_state=$(cat "$STATE_FILE" 2>/dev/null || echo "unknown")
freedom_status=$(check_freedom)

if [ -z "$freedom_status" ]; then
    # SSH to ASA failed — log it and try a fallback ping test
    logger "$LOG_TAG WARN: SSH to ASA failed, trying ping fallback"
    # Fallback: ping the Freedom BNG gateway (185.93.175.233) via outside_freedom source
    # If we can reach the BNG, Freedom is UP regardless of what the ASA SSH says
    if ping -c 2 -W 3 185.93.175.233 >/dev/null 2>&1; then
        freedom_status="UP"
        logger "$LOG_TAG Ping fallback: Freedom BNG reachable — marking UP"
    else
        logger "$LOG_TAG Ping fallback: Freedom BNG unreachable — status unknown, keeping current state"
    fi
fi

if [ "$freedom_status" = "DOWN" ] && [ "$current_state" != "qos-active" ]; then
    logger "$LOG_TAG Freedom DOWN — applying tenant QoS (5/2 Mbps per room)"
    apply_qos
    send_sms "[NL-INFRA] Freedom ISP DOWN. PPPoE lost on outside_freedom. xs4all carrying all S2S tunnels. Tenant QoS applied (5/2 Mbps/room). Physical fix: power-cycle ONT on sw01 Gi1/0/36."
    echo "qos-active" > "$STATE_FILE"
elif [ "$freedom_status" = "UP" ] && [ "$current_state" != "qos-inactive" ]; then
    logger "$LOG_TAG Freedom UP — removing tenant QoS limits"
    remove_qos
    send_sms "[NL-INFRA] Freedom ISP RECOVERED. PPPoE re-established. Tenant QoS limits removed. Full bandwidth restored."
    echo "qos-inactive" > "$STATE_FILE"
fi

# Always log ONT health metrics (runs every 2 min regardless of state)
log_ont_health "$freedom_status"
