# Storage and backups

## Disk layout

```mermaid
flowchart LR
    subgraph NVMe["Sabrent NVMe 238 GB"]
        EFI["/boot/efi (vfat, 1 GB)"]
        Root["/ (ext4, 237 GB)"]
    end
    subgraph Tier["bcache0 (3.6 TB, ext4) at /mnt/storage"]
        SSD["Kingston SATA SSD 112 GB<br/>cache device"]
        HDD["Seagate HDD 3.6 TB<br/>backing device"]
        SSD --- HDD
    end
```

| Mount | Device | FS | Size | Used | Holds |
|---|---|---|---|---|---|
| `/` | NVMe partition 2 | ext4 | 233 GB | 93 GB (42%) | OS, Docker images and named volumes, backup repo, 8 GB swap file |
| `/boot/efi` | NVMe partition 1 | vfat | 1.1 GB | 6 MB | EFI system partition |
| `/mnt/storage` | `bcache0` | ext4 | 3.6 TB | 18 GB (1%) | Application data |

`/mnt/storage` is mounted by UUID with `defaults,nofail`, so the host still boots if the data volume is missing. Containers that bind-mount paths under it would then start against an empty directory on the root disk; check `findmnt /mnt/storage` after any storage incident before starting stacks.

There is no RAID. Each tier is a single disk.

## bcache

| Setting | Value |
|---|---|
| Backing device | 3.6 TB HDD (whole disk) |
| Cache device | 112 GB SATA SSD (whole disk) |
| Cache mode | `writeback` |
| `writeback_percent` | 10 |
| `sequential_cutoff` | 4 MB (larger sequential I/O bypasses the cache) |
| Bucket size | 512 KiB |
| State at audit | `dirty`, 444 KiB waiting to be written back |
| Cache hit ratio (lifetime) | 90% |
| Cache space available | 95% |

**What writeback means here.** Writes are acknowledged once they are on the SSD and flushed to the HDD afterwards. If the SSD fails while dirty data is outstanding, the filesystem on the HDD is missing those writes and may be inconsistent. With a single cache SSD and a single backing disk, this tier optimises for speed and capacity, not durability. Backups are the durability layer.

Useful checks:

```bash
cat /sys/block/bcache0/bcache/state            # clean | dirty | inconsistent
cat /sys/block/bcache0/bcache/dirty_data
cat /sys/block/bcache0/bcache/cache_mode
cat /sys/block/bcache0/bcache/stats_total/cache_hit_ratio
```

Before removing or replacing the SSD, switch to `writethrough` and wait for `dirty_data` to reach zero:

```bash
echo writethrough | sudo tee /sys/block/bcache0/bcache/cache_mode
watch cat /sys/block/bcache0/bcache/dirty_data
```

## Where data lives

| Data | Location | Disk |
|---|---|---|
| Immich photos, videos, thumbnails | `/mnt/storage/immich/library` (17 GB) | bcache |
| Immich PostgreSQL | `/mnt/storage/immich/postgres` | bcache |
| Nextcloud user files | `/mnt/storage/nextcloud` | bcache |
| Nextcloud app code, PostgreSQL, Redis | volumes `nextcloud_aio_*` | NVMe |
| Vaultwarden SQLite, attachments, keys | `/mnt/storage/vaultwarden/data` | bcache |
| Trilium SQLite and its own rotating backups | `/mnt/storage/trilium/trilium-data` | bcache |
| n8n SQLite, encryption key, workflows | `/mnt/storage/n8n` | bcache |
| Quartus build context, desktop home, projects | `/mnt/storage/quartus` | bcache |
| Nginx Proxy Manager config and certificates | volumes `homelab-core_npm_data`, `homelab-core_npm_letsencrypt` | NVMe |
| Portainer state | volume `homelab-core_portainer_data` | NVMe |
| SnapOtter state | volume `SnapOtter-data` | NVMe |
| Immich ML model cache | volume `immich_model-cache` | NVMe |
| UniFi configuration and database | `uosserver` user's Podman storage | NVMe |
| Compose files and `.env` files | `~/homelab-core`, `~/immich`, `~/n8n`, `~/nextcloud`, and beside the data for Trilium, Vaultwarden, Quartus | both |
| restic repository | `/var/backups/restic-repo` | NVMe |

## Health monitoring

- `smartd` scans all three disks (`DEVICESCAN`) and mails `root` on problems. No mail transport is configured on the host, so those messages are only visible in the journal.
- `fstrim.timer` trims weekly; `e2scrub_all.timer` checks ext4 metadata weekly.
- The kernel log for the current boot shows no I/O, ext4, or bcache errors.

## Backups

### Design

[`scripts/homelab-backup.sh`](../scripts/homelab-backup.sh) runs from `homelab-backup.timer` every night at 00:00 as root.

```mermaid
flowchart LR
    A[pg_dump Immich] --> S["/var/backups/staging<br/>(NVMe)"]
    B[pg_dump Nextcloud] --> S
    C[mongodump UniFi] --> S
    D["cp -a Vaultwarden,<br/>Trilium, Nextcloud data"] --> S
    S --> R["restic backup<br/>/var/backups/restic-repo<br/>(NVMe)"]
    R --> F["restic forget<br/>--keep-last 3 --prune"]
    F --> X[empty staging]
```

| Step | Detail |
|---|---|
| Database dumps | `pg_dump` inside `immich_postgres` and `nextcloud-aio-database`; `mongodump` inside a container named `unifi-db` |
| File copies | `/mnt/storage/vaultwarden`, `/mnt/storage/trilium`, `/mnt/storage/nextcloud` copied to staging |
| Repository | restic 0.18, local repo on the NVMe, password in `/root/.restic-password` |
| Retention | last 3 snapshots |
| Failure handling | `set -euo pipefail`: the first failing command aborts the run |

### Current state

**The job has failed every night since 2026-09-22.** The last successful run and the newest snapshot are from 2026-09-21. Details and the fix are in [finding 1](findings.md#1-nightly-backups-have-been-failing-since-2026-09-22).

### Coverage

| Data | In the backup? |
|---|---|
| Immich database | Yes (dump) |
| Immich photos and videos | **No** |
| Nextcloud database | Yes (dump) |
| Nextcloud user files | Yes (copy) |
| Vaultwarden | Yes (file copy of a live SQLite database) |
| Trilium | Yes (file copy, includes Trilium's own backup files) |
| UniFi | Intended, but targets a container that no longer exists |
| n8n | **No** |
| Nginx Proxy Manager, Portainer | **No** |
| Compose files, `.env` files, scripts, systemd units | **No** (sanitised copies are in this repo; secrets are not) |

Every copy is on the same machine as the data, and the repository shares a disk with the operating system. There is no off-site or off-host copy. See [finding 2](findings.md#2-backups-do-not-protect-against-losing-the-machine).

### Other backups that exist

- Immich writes its own scheduled database dumps to `/mnt/storage/immich/library/backups`.
- Trilium keeps daily, weekly, and monthly copies of its database in `trilium-data/backup`.
- Both live on the same bcache volume as the data they protect.

### Restore

These procedures follow from the backup layout. They have not been exercised as a full restore test.

```bash
# As root
export RESTIC_REPOSITORY=/var/backups/restic-repo
export RESTIC_PASSWORD_FILE=/root/.restic-password

restic snapshots
restic restore latest --target /tmp/restore
# files appear under /tmp/restore/var/backups/staging/
```

| Service | Procedure |
|---|---|
| Immich database | Stop `immich_server` and `immich_machine_learning`; `docker exec -i immich_postgres psql -U immich -d immich < immich-postgres.sql` into an empty database; start the stack. Follow Immich's restore documentation for the exact drop and create steps for the running version |
| Nextcloud database | Stop the containers from the AIO interface; restore `nextcloud-postgres.sql` into `nextcloud-aio-database`; copy `nextcloud-data` back to `/mnt/storage/nextcloud` preserving ownership (`www-data`); start containers and run `occ maintenance:data-fingerprint` |
| Vaultwarden | Stop the container; replace `/mnt/storage/vaultwarden/data` with the restored copy; start |
| Trilium | Stop the container; replace `trilium-data`; start |
