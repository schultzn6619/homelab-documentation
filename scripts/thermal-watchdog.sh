#!/bin/bash
# /usr/local/bin/thermal-watchdog.sh
THRESHOLD=80
THRESHOLD_CLEAR=75
CRITICAL=85
RESUME_TEMP=65
THROTTLED=0

get_temp() {
  sensors | grep Tctl | grep -oP '\+\K[0-9]+(?=\.)'
}

while true; do
  TEMP=$(get_temp)
  if [ "$TEMP" -ge "$CRITICAL" ]; then
    echo "$(date): CRITICAL $TEMP°C - pausing immich jobs" >> /var/log/thermal-watchdog.log
    docker pause immich_machine_learning immich_server

    while [ "$(get_temp)" -ge "$RESUME_TEMP" ]; do
      sleep 5
    done

    echo "$(date): Cooled to $(get_temp)°C - resuming" >> /var/log/thermal-watchdog.log
    docker unpause immich_machine_learning immich_server
    THROTTLED=0
  elif [ "$TEMP" -ge "$THRESHOLD" ]; then
    if [ "$THROTTLED" -eq 0 ]; then
      echo "$(date): WARN $TEMP°C - throttling" >> /var/log/thermal-watchdog.log
      # throttle every python3 PID belonging to the ML container's process
      for pid in $(pgrep -f python3); do
        cpulimit -p "$pid" -l 150 -b
      done
      THROTTLED=1
    fi
  else
    if [ "$THROTTLED" -eq 1 ] && [ "$TEMP" -lt "$THRESHOLD_CLEAR" ]; then
      echo "$(date): Back under threshold at $TEMP°C - clearing throttle" >> /var/log/thermal-watchdog.log
      pkill -f cpulimit
      THROTTLED=0
    fi
  fi
  sleep 5
done
