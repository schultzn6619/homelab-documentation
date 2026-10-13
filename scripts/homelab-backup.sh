#!/usr/bin/env bash
# /usr/local/bin/homelab-backup.sh
set -euo pipefail

export RESTIC_REPOSITORY="/var/backups/restic-repo"
export RESTIC_PASSWORD_FILE="/root/.restic-password"

STAGING="/var/backups/staging"   # staging also on the SSD now
mkdir -p "$STAGING"

# --- Postgres-backed services: dump, don't raw-copy ---
docker exec immich_postgres pg_dump -U immich -d immich > "$STAGING/immich-postgres.sql"
docker exec nextcloud-aio-database pg_dump -U nextcloud -d nextcloud_database > "$STAGING/nextcloud-postgres.sql"

# --- Mongo-backed service ---
docker exec unifi-db mongodump \
  --username=unifi \
  --password="${UNIFI_DB_PASSWORD}" \
  --authenticationDatabase=admin \
  --archive="/tmp/unifi-mongo.archive"
docker cp unifi-db:/tmp/unifi-mongo.archive "$STAGING/unifi-mongo.archive"

# --- Flat-file services (read from HDD, written to SSD staging) ---
cp -a /mnt/storage/vaultwarden "$STAGING/vaultwarden"
cp -a /mnt/storage/trilium "$STAGING/trilium"
cp -a /mnt/storage/nextcloud "$STAGING/nextcloud-data"

# --- Back up staging with restic (writes land on the SSD) ---
restic backup "$STAGING" --tag homelab-daily

# --- Prune: keep only the last 3 snapshots ---
restic forget --keep-last 3 --prune

# --- Clean staging so next run starts fresh ---
rm -rf "${STAGING:?}"/*
