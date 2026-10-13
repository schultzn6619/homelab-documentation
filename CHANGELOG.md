# Changelog

A dated record of changes made to the server. Each entry corresponds to one commit in this repository: the commit updates the documentation and configuration copies to match what was changed on the host, and the entry says what was done, why, and how it was verified.

Newest first. Finding numbers refer to [`docs/findings.md`](docs/findings.md).

## 2026-10-13

### Fixed the nightly backup (finding 1)

**Problem.** `homelab-backup.service` had failed every night since 2026-09-22. The script ran `mongodump` in a Docker container, `unifi-db`, that stopped existing when UniFi moved to UniFi OS Server. Because of `set -e`, that one error aborted the run before anything was written to restic, so no service had been backed up for three weeks.

**Changed.** [`/usr/local/bin/homelab-backup.sh`](scripts/homelab-backup.sh) was rewritten around the same design:

- Removed the `mongodump` block. UniFi is now covered by copying the controller's own scheduled backup files (`.unf`) out of the UniFi OS Server volume.
- Each source runs as an independent step. A failure is logged and recorded, the remaining steps still run, and the script exits non-zero at the end so systemd marks the unit failed.
- Retention pruning is skipped after any failed step, so an incomplete run cannot push a good snapshot out of the last three.
- Staging is emptied at the start as well as the end, in case an earlier run died midway.
- A failed `pg_dump` no longer leaves an empty dump file behind.
- `umask 077` and mode 700 on the staging directory: database dumps were previously world-readable while they sat in staging.
- The script no longer contains a database password.

**Verified.**

- `systemctl start homelab-backup.service` finished with `Result=success`; all eight steps logged `ok`.
- `restic snapshots` shows a new snapshot dated 2026-10-13 (356 MiB) alongside the two newest older ones.
- `restic ls latest` contains both database dumps, the Nextcloud data directory, Vaultwarden, Trilium, and the UniFi backup file.
- `restic check` reports no errors.
- `systemctl --failed` no longer lists the backup unit. The timer next fires at 00:00.

**Still open.** The repository is still on the boot disk, the Immich photo library is still not included, SQLite files are still copied live, and nothing alerts if the job fails again (findings 2 and 3). The only UniFi backup file present is dated 2026-10-01, which points to a monthly schedule, so that copy can be weeks old; raise the frequency in the UniFi UI if that matters.

### Second audit pass with root access

Read-only. Added the live firewall rules, SMART data for all three disks, memory layout, and restic snapshot list to the docs, and opened findings 17 (firewall rule drift) and 18 (data disk past its rated load cycles).

### Initial audit and documentation

Full review of the live host. Replaced the README and added the architecture, host, networking, services, storage, hardening, and operations documents, sanitised copies of the Compose files, scripts, and system configuration, and findings 1 to 16.
