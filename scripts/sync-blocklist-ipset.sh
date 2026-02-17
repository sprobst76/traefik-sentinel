#!/bin/bash
# Sync Traefik Sentinel blocklist to ipset
#
# Setup:
#   1. Install ipset: apt install ipset
#   2. Create sets:
#      ipset create blocklist_ips hash:ip family inet hashsize 4096 maxelem 65536
#      ipset create blocklist_nets hash:net family inet hashsize 1024 maxelem 65536
#   3. Add iptables rules:
#      iptables -I INPUT -m set --match-set blocklist_ips src -j DROP
#      iptables -I INPUT -m set --match-set blocklist_nets src -j DROP
#   4. Add to cron:
#      * * * * * /path/to/sync-blocklist-ipset.sh
#
# Configuration
SENTINEL_URL="${SENTINEL_URL:-http://localhost:13923}"
BLOCKLIST_FILE="/tmp/blocklist.json"

# Fetch blocklist from Traefik Sentinel
curl -sf "${SENTINEL_URL}/api/blocklist" -o "$BLOCKLIST_FILE" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Error: Could not fetch blocklist from ${SENTINEL_URL}"
    exit 1
fi

# Ensure ipsets exist
ipset list blocklist_ips >/dev/null 2>&1 || ipset create blocklist_ips hash:ip family inet hashsize 4096 maxelem 65536
ipset list blocklist_nets >/dev/null 2>&1 || ipset create blocklist_nets hash:net family inet hashsize 1024 maxelem 65536

# Create temporary sets for atomic swap
ipset create blocklist_ips_tmp hash:ip family inet hashsize 4096 maxelem 65536 2>/dev/null
ipset create blocklist_nets_tmp hash:net family inet hashsize 1024 maxelem 65536 2>/dev/null

# Clear temporary sets
ipset flush blocklist_ips_tmp
ipset flush blocklist_nets_tmp

# Parse JSON and add IPs to sets
python3 -c "
import json
import sys

try:
    with open('$BLOCKLIST_FILE', 'r') as f:
        data = json.load(f)

    for entry in data:
        ip = entry.get('ip', '')
        is_cidr = entry.get('is_cidr', False) or '/' in ip

        if is_cidr:
            print(f'NET:{ip}')
        else:
            print(f'IP:{ip}')
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
" | while read line; do
    type="${line%%:*}"
    addr="${line#*:}"

    if [ "$type" = "IP" ]; then
        ipset add blocklist_ips_tmp "$addr" 2>/dev/null
    elif [ "$type" = "NET" ]; then
        ipset add blocklist_nets_tmp "$addr" 2>/dev/null
    fi
done

# Atomic swap
ipset swap blocklist_ips blocklist_ips_tmp
ipset swap blocklist_nets blocklist_nets_tmp

# Cleanup temporary sets
ipset destroy blocklist_ips_tmp 2>/dev/null
ipset destroy blocklist_nets_tmp 2>/dev/null

# Count entries
IP_COUNT=$(ipset list blocklist_ips 2>/dev/null | grep -c "^[0-9]")
NET_COUNT=$(ipset list blocklist_nets 2>/dev/null | grep -c "^[0-9]")

echo "Synced: ${IP_COUNT} IPs, ${NET_COUNT} CIDR ranges"

# Cleanup
rm -f "$BLOCKLIST_FILE"
