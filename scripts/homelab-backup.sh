#!/usr/bin/env bash
# /usr/local/bin/homelab-backup.sh
set -uo pipefail
umask 077   # dumps and copies in staging are root-only

export RESTIC_REPOSITORY="/var/backups/restic-repo"
export RESTIC_PASSWORD_FILE="/root/.restic-password"

STAGING="/var/backups/staging"   # staging also on the SSD now
UNIFI_BACKUPS="/home/uosserver/.local/share/containers/storage/volumes/uosserver_var_lib_unifi/_data/backup/autobackup"
FAILED=()

# Run one step; on failure record it and carry on, so one broken source
# cannot cancel the backup of everything else.
step() {
  local name="$1"; shift
  if "$@"; then
    echo "ok: $name"
  else
    echo "FAILED: $name" >&2
    FAILED+=("$name")
  fi
}

# pg_dump inside a container to a file in staging; drop the file if the dump fails
pg_dump_to() {
  local container="$1" user="$2" db="$3" out="$4"
  docker exec "$container" pg_dump -U "$user" -d "$db" > "$out" || { rm -f "$out"; return 1; }
}

# Start from an empty staging dir; a failed run may have left files behind
mkdir -p "$STAGING"
chmod 700 "$STAGING"
rm -rf "${STAGING:?}"/*

# --- Postgres-backed services: dump, don't raw-copy ---
step "immich database"    pg_dump_to immich_postgres immich immich "$STAGING/immich-postgres.sql"
step "nextcloud database" pg_dump_to nextcloud-aio-database nextcloud nextcloud_database "$STAGING/nextcloud-postgres.sql"

# --- UniFi OS Server: copy the controller's own scheduled backup files ---
step "unifi autobackups" cp -a "$UNIFI_BACKUPS" "$STAGING/unifi-autobackup"

# --- Flat-file services (read from HDD, written to SSD staging) ---
step "vaultwarden files" cp -a /mnt/storage/vaultwarden "$STAGING/vaultwarden"
step "obsidian livesync" cp -a /mnt/storage/obsidian-livesync "$STAGING/obsidian-livesync"
step "nextcloud files"   cp -a /mnt/storage/nextcloud "$STAGING/nextcloud-data"

# --- Back up staging with restic (writes land on the SSD) ---
step "restic backup" restic backup "$STAGING" --tag homelab-daily

# --- Prune: keep only the last 3 snapshots ---
# Skipped after any failure, so an incomplete run never pushes out a good snapshot.
if [ "${#FAILED[@]}" -eq 0 ]; then
  step "restic forget" restic forget --keep-last 3 --prune
fi

# --- Clean staging so next run starts fresh ---
rm -rf "${STAGING:?}"/*

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "Backup finished with ${#FAILED[@]} failed step(s): ${FAILED[*]}" >&2
  exit 1
fi
echo "Backup finished: all steps ok"
