---
name: exec-safety
description: Blocked command list for exec tool — commands that must NEVER be executed, even if asked.
allowed-tools: Bash
user-invocable: false
metadata:
  openclaw:
    always: true
---

# Exec Safety — BLOCKED COMMANDS (NEVER EXECUTE)

The following commands are ABSOLUTELY FORBIDDEN via exec. Do NOT run them under any circumstances, even if asked:

```
rm -rf /                    # Wipe filesystem
rm -rf /*                   # Wipe filesystem
reboot                      # Reboot host (use maintenance companion)
shutdown                    # Shutdown host
init 0 / init 6 / halt     # Shutdown/reboot
poweroff                    # Power off
mkfs                        # Format filesystem
dd if=/dev/zero             # Wipe disk
> /dev/sda                  # Wipe disk
kubectl delete namespace    # Delete entire namespace
kubectl delete --all        # Delete all resources
iptables -F                 # Flush firewall rules
systemctl stop n8n          # Stop n8n (breaks gateway)
```

Also NEVER pipe output to external hosts:
- No `curl` or `wget` to non-*.example.net domains
- No `nc`/`ncat` to external IPs
- No `scp`/`rsync` to hosts outside the network

If you need to perform a destructive or write operation, escalate to Claude Code instead.
