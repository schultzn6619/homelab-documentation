#!/bin/sh
# Called by notify-failure@<unit>.service when any service fails (global OnFailure=).
# Posts the unit's status and recent log to Discord with a ping, at most once an
# hour per unit. Units in NOTIFY_IGNORE_UNITS (space separated) are skipped.
unit="$1"
for u in $NOTIFY_IGNORE_UNITS; do
    [ "$u" = "$unit" ] && { echo "Ignoring $unit"; exit 0; }
done
host=$(hostname)
result=$(systemctl show -p Result --value "$unit")
{
    systemctl status --no-pager --lines=0 "$unit" 2>&1 | head -n 8
    echo
    journalctl -u "$unit" -n 20 --no-pager -o short-iso 2>&1
} | /usr/bin/python3 -I /usr/local/bin/discord-notify.py --ping \
        --key "unit-$unit" --cooldown 3600 \
        "$unit failed on $host (result: $result)"
