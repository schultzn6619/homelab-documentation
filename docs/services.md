# Services

Per-service reference. Versions are what was running on 2026-10-13. Hostnames are prefixes of `example.duckdns.org`.

## Summary

| Service | Version | Managed by | Compose project (real path) | Data | Restart |
|---|---|---|---|---|---|
| Nginx Proxy Manager | 2.16.0 | Compose | `homelab-core` (`~/homelab-core`) | volumes `npm_data`, `npm_letsencrypt` | unless-stopped |
| Portainer CE | 2.45.2 | Compose | `homelab-core` | volume `portainer_data` | unless-stopped |
| Watchtower | 1.21.2 (`nickfedor/watchtower`) | Compose | `homelab-core` | none | unless-stopped |
| Immich | 3.1.0 | Compose | `immich` (`~/immich`) | `/mnt/storage/immich` | always |
| Nextcloud AIO | Nextcloud 34.0.4 | Compose + AIO | `nextcloud` (`~/nextcloud`) | `/mnt/storage/nextcloud`, AIO volumes | always |
| Vaultwarden | 1.37.4 | Compose | `vaultwarden` (`/mnt/storage/vaultwarden`) | `/mnt/storage/vaultwarden/data` | unless-stopped |
| Obsidian LiveSync (CouchDB + CLI) | CouchDB 3.5.3, LiveSync CLI `latest` | Compose | `obsidian-livesync` (`/mnt/storage/obsidian-livesync`) | `/mnt/storage/obsidian-livesync` | unless-stopped |
| n8n | 2.36.7 | Compose | `n8n` (`~/n8n`) | `/mnt/storage/n8n` | unless-stopped |
| IT-Tools | `latest` (image is 2 years old) | `docker run` | – | none | unless-stopped |
| SnapOtter | 2.2.0 | `docker run` | – | volume `SnapOtter-data` | **no** |
| Quartus webtop | local build | Compose | `quartus` (`/mnt/storage/quartus`) | `/mnt/storage/quartus` | unless-stopped, currently stopped |
| UniFi OS Server | 5.1.42 | systemd + rootless Podman | – | `uosserver` user's Podman storage | on-failure |

Sanitised copies of every Compose file are in [`compose/`](../compose).

## Core stack (`homelab-core`)

Defines the shared `proxy` network and the three infrastructure containers.

### Nginx Proxy Manager

- Image `jc21/nginx-proxy-manager:latest`, static address `172.18.0.10` on `proxy`.
- Publishes 80, 443, and the admin UI on 81, all bound to the LAN address only.
- Holds one wildcard certificate obtained with the DuckDNS DNS-01 plugin. The DuckDNS token lives inside the `npm_letsencrypt` volume.
- Proxy host definitions live in the `npm_data` volume (SQLite database plus generated nginx config). They are listed in [networking](networking.md#reverse-proxy-hosts) and are not otherwise version-controlled.

### Portainer

- Image `portainer/portainer-ce:latest`, UI on 9000 (LAN address and `ptnr.`).
- Mounts the Docker socket read-write.

### Watchtower

- Image `nickfedor/watchtower`, a maintained fork of the original project.
- Runs at 04:00 daily, label opt-in, rolling restarts, removes old images.

### Twingate connector (defined, not deployed)

The Compose file still declares a `twingate` service with a static address, from before the move to Tailscale. No such container exists. See [finding 5](findings.md#5-homelab-core-compose-file-has-drifted-from-what-is-deployed).

## Immich

Photo and video library with face and object search.

| Container | Image | Role |
|---|---|---|
| `immich_server` | `ghcr.io/immich-app/immich-server:release` | API, web UI, background jobs (port 2283) |
| `immich_machine_learning` | `ghcr.io/immich-app/immich-machine-learning:release` | CPU inference; model cache in volume `immich_model-cache` |
| `immich_postgres` | `ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0` (digest-pinned) | Database with vector extensions |
| `immich_redis` | `valkey/valkey:9` (digest-pinned) | Job queue |

- Library at `/mnt/storage/immich/library` (17 GB), database at `/mnt/storage/immich/postgres`. The database is tuned for spinning disk (`DB_STORAGE_TYPE: HDD`).
- Inference runs on the CPU; the installed GPU is not usable for it. This workload is what the thermal watchdog guards.
- All four containers are on the `proxy` network.
- Upgrades are manual: read the release notes, then `docker compose pull && docker compose up -d`.

## Nextcloud AIO

The Compose file only starts the AIO master container. The master then creates and manages the rest through the Docker socket.

| Container | Role |
|---|---|
| `nextcloud-aio-mastercontainer` | AIO admin interface (listens on 8080 inside the container; the published port mapping is wrong, see [finding 8](findings.md#8-nextcloud-aio-admin-interface-is-not-reachable)) |
| `nextcloud-aio-apache` | Web front end, port 11000, joined to `proxy` |
| `nextcloud-aio-nextcloud` | PHP application |
| `nextcloud-aio-database` | PostgreSQL |
| `nextcloud-aio-redis` | Cache and locking |
| `nextcloud-aio-notify-push` | Client push |
| `nextcloud-aio-imaginary` | Image previews |
| `nextcloud-aio-watchtower` | Runs on demand to update the master container |

- Runs in reverse-proxy mode: `APACHE_PORT=11000`, `APACHE_ADDITIONAL_NETWORK=proxy`, and `SKIP_DOMAIN_VALIDATION=true` because the domain is not publicly reachable.
- User files are on the data disk (`NEXTCLOUD_DATADIR=/mnt/storage/nextcloud`); application code and the database are in named volumes on the NVMe.
- Optional AIO containers (Collabora, Talk, ClamAV, Fulltextsearch, Whiteboard) are not enabled.
- Updates are done from the AIO interface. AIO's built-in Borg backup is not configured; the host backup script dumps the database instead.

## Vaultwarden

- Image `vaultwarden/server:latest`, SQLite database and attachments in `/mnt/storage/vaultwarden/data`.
- `SIGNUPS_ALLOWED=true` is still set from initial setup.
- Updated automatically by Watchtower.

## Trilium (removed)

- Removed on 2026-10-25 after the migration to Obsidian LiveSync: container and image deleted with `docker compose down` in `/mnt/storage/trilium`.
- The archived data in `/mnt/storage/trilium` was deleted later the same day and removed from the nightly backup. The notes themselves live on in the Obsidian vault.

## Obsidian LiveSync

Replaces Trilium as the notes system (migrated 2026-10-25). Notes are an Obsidian vault synced between devices by the [Self-hosted LiveSync](https://github.com/vrtmrz/obsidian-livesync) plugin, with CouchDB on this host as the sync server.

- `couchdb` (`couchdb:3`): the sync database `obsidiannotes`. Provisioned with LiveSync's `couchdb-init.sh` (single node, `require_valid_user`, CORS for `app://obsidian.md`, `capacitor://localhost`, `http://localhost`, raised request and document size limits). The provisioned settings persist in `couchdb-etc/docker.ini`. Admin credentials are in `.env`. No host port is published; it is reached on `proxy` as `couchdb:5984`.
- `livesync-cli` (`ghcr.io/vrtmrz/livesync-cli:latest`): a headless LiveSync client running `daemon`. It mirrors the vault as plain Markdown into `/mnt/storage/obsidian-livesync/vault`, so the server always holds a readable copy that the nightly backup picks up. Its local PouchDB and settings are in `cli-db/`.
- Vault contents are end-to-end encrypted, including file paths: CouchDB only holds ciphertext. The E2EE passphrase, Setup URI passphrase, and ID recovery code are in `secrets/livesync.env` (mode 600), and the generated Setup URIs in `secrets/gen-*.txt`. Losing the E2EE passphrase makes the CouchDB data unreadable, though the plain copy in `vault/` survives.
- Clients join with the Setup URI for `https://obsidian.example.duckdns.org`; the CLI uses one generated with the same ID recovery code that points at `http://couchdb:5984`.
- Both containers are updated automatically by Watchtower.

## n8n

- Image `n8nio/n8n:latest`, state (SQLite database, credentials encryption key, workflows) in `/mnt/storage/n8n`.
- Configured for `https://n8n.example.duckdns.org`.
- Not labelled for Watchtower, so it stays on the pulled image until updated by hand. Not included in the backup script.
- Bind-mounts the vault folder `/mnt/storage/obsidian-livesync/vault/Rocketbook Inbox` at `/home/node/.n8n-files/rocketbook`. n8n 2.x only lets file nodes use `~/.n8n-files`, and mounting just this folder keeps n8n out of the rest of the vault.

### Workflow "Rocketbook → Obsidian"

Source: [`compose/n8n/workflows/rocketbook-obsidian.json`](../compose/n8n/workflows/rocketbook-obsidian.json), generated by `build_rocketbook_workflow.py`. Active.

1. IMAP trigger on the `Rocketbook` mailbox (credential "IMAP account"); unread messages are processed and marked as read.
2. Each attachment is saved to `Rocketbook Inbox/scans/` as `YYYY-MM-DD HHmmss <title>.pdf` (or `.jpg`). Rocketbook's default subject, `RB <scan time>.pdf-<send time>`, becomes the scan time plus the title "Rocketbook scan"; any other subject (for example a Smart Title) is used as the title with the email's arrival time.
3. Text is extracted from each PDF (failures are tolerated, e.g. for images).
4. One note per email, `Rocketbook Inbox/YYYY-MM-DD HHmmss <title>.md`, with front matter (`created` = scan time, `received`, `source: rocketbook`, `email_subject`, tag `rocketbook`), an embed of each scan, and collapsed callouts holding the email text and the PDF text.
5. If the subject (a Rocketbook Smart Title such as `##DE L3a##`) or a `##...##` code in the scanned text names a class and lecture, the note also gets `class` and `lecture` properties. Codes: `DE` Digital Electronics, `LF` Linux Fundamentals, `NA` Network Admin 1, `STS` Science, Tech, and Society; the lecture is `L<n>` with an optional `a`/`b` (`L3a`, `Lec 3`, `lecture 3b`). The table is `CLASSES` in the "Build note" node.
6. `rocketbook-filer.path` notices the change in the inbox and runs [`rocketbook-filer.py`](../scripts/rocketbook-filer.py), which moves every inbox note with both properties, and its embedded scans, into `<class>/Lecture <n>/`, creating the lecture folder if needed. It only files into class folders that already exist; anything else stays in the inbox. Adding the two properties by hand on any device files a note the same way.
7. `livesync-cli` syncs the resulting files to every device.

n8n can still only write to `Rocketbook Inbox`; the moving happens in the filer because n8n's file node cannot create folders. The filer runs as the admin user (`rocketbook-filer.service`, [unit files](../system/)).

A copy with a manual trigger and three fake emails (a Smart Title code, a default subject, a code only in the text), "Rocketbook → Obsidian (test)", exercises steps 2 to 6 without mail: `docker exec -e N8N_RUNNERS_BROKER_PORT=5699 n8n n8n execute --id=rbTestPipeline01` (the alternate broker port avoids a clash with the running instance). It writes into `Lecture 9` of two classes and into the inbox; delete those test files and the two `Lecture 9` folders afterwards.

## IT-Tools and SnapOtter

Two utility containers started by hand with `docker run`, so there is no Compose file for them.

| | IT-Tools | SnapOtter |
|---|---|---|
| Image | `corentinth/it-tools:latest` | `snapotter/snapotter:latest` (12.3 GB) |
| What it is | Collection of developer utilities | File conversion, compression, OCR, transcription, and local AI tools |
| Network | default bridge | default bridge |
| Port | `0.0.0.0:8097 -> 80` | `0.0.0.0:1349 -> 1349` |
| State | none | volume `SnapOtter-data` |
| Restart policy | unless-stopped | none: will not start after a reboot |

Equivalent Compose definitions on the `proxy` network would remove both published ports. See [finding 6](findings.md#6-three-containers-publish-ports-on-every-interface).

## Quartus webtop

A locally built image that layers Intel Quartus 13.0sp1 (from `raetro/quartus`) onto the LinuxServer.io XFCE webtop image, giving a browser-accessible desktop for FPGA work on older device families.

- Build context and Compose file at `/mnt/storage/quartus`; [`Dockerfile`](../compose/quartus/Dockerfile) adds the 32-bit libraries and `libpng12` that Quartus 13 needs.
- Projects persist in `/mnt/storage/quartus/projects`.
- 1 GB of shared memory for the desktop session.
- The image is 14.1 GB. The container has been stopped since 2026-10-03.
- In the deployed file the desktop username and password are written inline; this repo's copy reads them from `.env`.

## UniFi OS Server

Ubiquiti's self-hosted controller package, version 5.1.42, running the UniFi Network application.

- Installed under `/var/lib/uosserver`, CLI at `/usr/local/bin/uosserver`.
- `uosserver.service` runs as the `uosserver` user and launches one rootless Podman container that carries its own systemd, nginx, MongoDB, and the UniFi applications.
- Ports are forwarded to the host by `pasta`; the full list is in [networking](networking.md#unifi-os-server-rootless-podman-forwarded-by-pasta).
- `uosserver-updater.service` (root) keeps it up to date.
- Data lives in Podman volumes mapped to `/var/lib/unifi` and `/var/lib/mongodb` inside the container.
- Because it listens on the host's own ports, UniFi devices can discover and adopt against the host address directly.

Not to be confused with the separate `mongod` service installed on the host, which is unused.

## Update policy

| Mechanism | Covers |
|---|---|
| Watchtower, 04:00 daily | `npm`, `portainer`, `vaultwarden`, `couchdb`, `livesync-cli` |
| Nextcloud AIO interface | All `nextcloud-aio-*` containers |
| UniFi OS Server updater | UniFi OS Server |
| `unattended-upgrades` | Ubuntu packages from the release and security pockets |
| Tailscale auto-update | Tailscale |
| Manual | `immich_*`, `n8n`, `it-tools`, `SnapOtter`, `quartus`, Docker Engine and other third-party APT packages |

Most images track `latest` or `release`, so a rebuild today would not necessarily reproduce what is running. Only the Immich database and cache images are pinned by digest.
