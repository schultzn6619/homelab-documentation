# Services

Per-service reference. Versions are what was running on 2026-10-13. Hostnames are prefixes of `example.duckdns.org`.

## Summary

| Service | Version | Managed by | Compose project (real path) | Data | Restart |
|---|---|---|---|---|---|
| Nginx Proxy Manager | 2.16.0 (pinned) | Compose | `homelab-core` (`~/homelab/homelab-core`) | volumes `npm_data`, `npm_letsencrypt` | unless-stopped |
| Portainer CE | 2.45.3 (pinned) | Compose | `homelab-core` | volume `portainer_data` | unless-stopped |
| Immich | 3.1.0 | Compose | `immich` (`~/immich`) | `/mnt/storage/immich` | always |
| Nextcloud AIO | Nextcloud 34.0.4 | Compose + AIO | `nextcloud` (`~/nextcloud`) | `/mnt/storage/nextcloud`, AIO volumes | always |
| Vaultwarden | 1.37.5 (pinned) | Compose | `vaultwarden` (`/mnt/storage/vaultwarden`) | `/mnt/storage/vaultwarden/data` | unless-stopped |
| Obsidian LiveSync (CouchDB + CLI) | CouchDB 3.5.3, LiveSync CLI 1.0.43 (both pinned) | Compose | `obsidian-livesync` (`/mnt/storage/obsidian-livesync`) | `/mnt/storage/obsidian-livesync` | unless-stopped |
| n8n | 2.36.7 | Compose | `n8n` (`~/n8n`) | `/mnt/storage/n8n` | unless-stopped |
| Navidrome | 0.64.2 (pinned) | Compose | `music` (`~/homelab/music`) | `/mnt/storage/music/navidrome`, library `/mnt/storage/music/library` | unless-stopped |
| slskd (Soulseek client) | 0.26.2 (pinned) | Compose | `music` | `/mnt/storage/music/slskd` | unless-stopped |
| IT-Tools | `2024.10.22-7ca5933` (pinned; upstream unchanged since 2024) | Compose | `utilities` (`~/homelab/utilities`) | none | unless-stopped |
| SnapOtter | 2.2.0 (pinned) | Compose | `utilities` | volume `SnapOtter-data` | unless-stopped |
| UniFi OS Server | 5.1.42 | systemd + rootless Podman | – | `uosserver` user's Podman storage | on-failure |

Sanitised copies of every Compose file are in [`compose/`](../compose).

## Core stack (`homelab-core`)

Defines the shared `proxy` network and the three infrastructure containers.

### Nginx Proxy Manager

- Image `jc21/nginx-proxy-manager:2.16.0`, static address `172.18.0.10` on `proxy`.
- Publishes 80, 443, and the admin UI on 81, all bound to the LAN address only.
- Holds one wildcard certificate obtained with the DuckDNS DNS-01 plugin. The DuckDNS token lives inside the `npm_letsencrypt` volume.
- Proxy host definitions live in the `npm_data` volume (SQLite database plus generated nginx config). They are listed in [networking](networking.md#reverse-proxy-hosts) and are not otherwise version-controlled.

### Portainer

- Image `portainer/portainer-ce:2.45.3`, UI on 9000 (LAN address and `ptnr.`).
- Mounts the Docker socket read-write.

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
| `nextcloud-aio-apache` | Web front end on port 11000, joined to `proxy`, no host port |
| `nextcloud-aio-nextcloud` | PHP application |
| `nextcloud-aio-database` | PostgreSQL |
| `nextcloud-aio-redis` | Cache and locking |
| `nextcloud-aio-notify-push` | Client push |
| `nextcloud-aio-imaginary` | Image previews |
| `nextcloud-aio-watchtower` | Runs on demand to update the master container |

- Runs in reverse-proxy mode: `APACHE_PORT=11000`, `APACHE_ADDITIONAL_NETWORK=proxy`, `APACHE_IP_BINDING=@INTERNAL` (AIO publishes no host port for Apache), and `SKIP_DOMAIN_VALIDATION=true` because the domain is not publicly reachable.
- User files are on the data disk (`NEXTCLOUD_DATADIR=/mnt/storage/nextcloud`); application code and the database are in named volumes on the NVMe.
- Optional AIO containers (Collabora, Talk, ClamAV, Fulltextsearch, Whiteboard) are not enabled.
- Updates are done from the AIO interface. AIO's built-in Borg backup is not configured; the host backup script dumps the database instead.

## Vaultwarden

- Image `vaultwarden/server:1.37.5`, SQLite database and attachments in `/mnt/storage/vaultwarden/data`.
- `SIGNUPS_ALLOWED=true` is still set from initial setup.
- Pinned to a version tag and updated by hand (see [update policy](#update-policy)).

## Trilium (removed)

- Removed on 2026-10-25 after the migration to Obsidian LiveSync: container and image deleted with `docker compose down` in `/mnt/storage/trilium`.
- The archived data in `/mnt/storage/trilium` was deleted later the same day and removed from the nightly backup. The notes themselves live on in the Obsidian vault.

## Obsidian LiveSync

Replaces Trilium as the notes system (migrated 2026-10-25). Notes are an Obsidian vault synced between devices by the [Self-hosted LiveSync](https://github.com/vrtmrz/obsidian-livesync) plugin, with CouchDB on this host as the sync server.

- `couchdb` (`couchdb:3`): the sync database `obsidiannotes`. Provisioned with LiveSync's `couchdb-init.sh` (single node, `require_valid_user`, CORS for `app://obsidian.md`, `capacitor://localhost`, `http://localhost`, raised request and document size limits). The provisioned settings persist in `couchdb-etc/docker.ini`. Admin credentials are in `.env`. No host port is published; it is reached on `proxy` as `couchdb:5984`.
- `livesync-cli` (`ghcr.io/vrtmrz/livesync-cli:1.0.43-cli`, pinned): a headless LiveSync client running `daemon`. It mirrors the vault as plain Markdown into `/mnt/storage/obsidian-livesync/vault`, so the server always holds a readable copy that the nightly backup picks up. Its local PouchDB and settings are in `cli-db/`.
- Vault contents are end-to-end encrypted, including file paths: CouchDB only holds ciphertext. The E2EE passphrase, Setup URI passphrase, and ID recovery code are in `secrets/livesync.env` (mode 600), and the generated Setup URIs in `secrets/gen-*.txt`. Losing the E2EE passphrase makes the CouchDB data unreadable, though the plain copy in `vault/` survives.
- Clients join with the Setup URI for `https://obsidian.example.duckdns.org`; the CLI uses one generated with the same ID recovery code that points at `http://couchdb:5984`.
- Both images are pinned to version tags and updated by hand. `livesync-cli` was pinned first, because 1.0.44 broke the daemon (see the [changelog](../CHANGELOG.md#pinned-livesync-cli-after-a-broken-update)). Update it by hand: read the release notes, back up `cli-db/` and `vault/`, change the tag, `docker compose up -d livesync-cli`, then check the log reaches "LiveSync active".

## n8n

- Image `n8nio/n8n:latest`, state (SQLite database, credentials encryption key, workflows) in `/mnt/storage/n8n`.
- Configured for `https://n8n.example.duckdns.org`.
- Tracks `latest` but stays on the pulled image until updated by hand. Not included in the backup script.
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

## Music (Navidrome + slskd)

Self-hosted replacement for Spotify. Navidrome is the player (Subsonic API; iPhone client Amperfy), slskd downloads from the Soulseek network. [Compose file](../compose/music/docker-compose.yml).

- Library: `/mnt/storage/music/library`, mounted read-only into Navidrome, rescanned every 15 minutes. slskd writes finished downloads to `library/soulseek/`; partial files go to `/mnt/storage/music/incomplete` so Navidrome never sees them.
- slskd shares nothing (no shared directories configured). Some Soulseek users refuse uploads to peers that share nothing.
- The Soulseek peer port 50300/tcp is published on the host but not forwarded on the router, so peers can't connect in directly; searches and downloads still work.
- ListenBrainz scrobbling is enabled server-wide; each user links a token in Navidrome's personal settings.
- slskd's API is also published on `127.0.0.1:5030` for the Discover Weekly job.

### Discover Weekly job

[`discover-weekly.py`](../scripts/discover-weekly.py), installed as `/usr/local/bin/discover-weekly.py`, run by `discover-weekly.timer` every Monday at 08:00 ([unit files](../system/)) as the admin user, with the slskd login from the music `.env`.

1. **Cleanup.** Songs it fetched more than 28 days ago are deleted unless the Navidrome user starred them, rated them 4+, or played them at least twice (read from Navidrome's database, read-only). Kept songs stay where they are.
2. **Pick.** The newest ListenBrainz "Weekly Exploration" playlist if it hasn't expired, then ListenBrainz collaborative-filtering recommendations the user has never listened to. Skips songs already in the library or tried before, and takes at most 2 per artist.
3. **Download.** Searches slskd for each song and ranks results: the title and artist must appear in the path, the length must be within 10 s, remixes/instrumentals/sped-up versions are rejected, FLAC beats MP3 (MP3 must be ≥256 kbps), and free upload slots and short queues are preferred. A source that hasn't started after 10 minutes, or stalls for 5, is cancelled and the next one is tried. 2-hour limit.
4. **Playlist.** Finished files are moved to `library/discover/<Monday's date>/<Artist> - <Title>.<ext>` and listed in `library/discover/Discover Weekly.m3u`, which Navidrome imports as a synced "Discover Weekly" playlist owned by the first admin.

The week is named by its Monday, so a rerun in the same week only tops up to 25 songs. State (what was fetched, kept, removed, not found) is in `/mnt/storage/music/discover-state/state.json`. Logs: `journalctl -u discover-weekly`. Options: `--dry-run`, `--count N`, `--no-cleanup`.

- Pinned to a version tag and updated by hand (see [update policy](#update-policy)).

### Leaks organiser

[`leaks-organize.py`](../scripts/leaks-organize.py), installed as `/usr/local/bin/leaks-organize.py`, run every 15 minutes by `leaks-organize.timer` as the admin user ([unit files](../system/)). Needs `python3-mutagen` (apt).

1. **Sort.** A folder in `library/soulseek/` is moved to `library/leaks/<Artist>/` if its name or tags contain *unreleased*, *leak(s)*, *leaked*, *snippet(s)*, *OG file(s)* or *CDQ* (whole words, so "Luh Leakyz" doesn't count) and match exactly one of: Juice WRLD, Playboi Carti, Travis Scott, Yeat, Lil Uzi Vert. Folders touched in the last 5 minutes are skipped, and later files are merged into the same folder.
2. **Tag.** Every audio file under `library/leaks/<Artist>/` gets album artist = the artist, genre = Unreleased, and an album name built from its sub-folder names with quality labels like `[FLAC 16bit]` stripped and `(Unreleased)` appended. The artist is set unless the existing tag already names them. The title is rebuilt from the file name if it is empty or a placeholder like "Track 07". MusicBrainz album IDs are removed so leaks never merge with official albums. Files are only rewritten when something changes.

Options: `--dry-run`. Logs: `journalctl -u leaks-organize`. The Discover Weekly cleanup never touches `library/leaks/`.

## IT-Tools and SnapOtter

Two utility containers in the Compose project `utilities` ([Compose file](../compose/utilities/docker-compose.yml)), moved there from `docker run` on 2026-11-03. Neither publishes a port; NPM reaches them on `proxy`.

| | IT-Tools | SnapOtter |
|---|---|---|
| Image | `corentinth/it-tools:2024.10.22-7ca5933` | `snapotter/snapotter:2.2.0` (12.3 GB) |
| What it is | Collection of developer utilities | File conversion, compression, OCR, transcription, and local AI tools |
| Network | `proxy`, as `it-tools` | `proxy`, as `SnapOtter` with the alias `snapotter` |
| State | none | external volume `SnapOtter-data` (the data from the earlier container) |
| Restart policy | unless-stopped | unless-stopped |
| Health check | none | built into the image, `/api/v1/health` |

## UniFi OS Server

Ubiquiti's self-hosted controller package, version 5.1.42, running the UniFi Network application.

- Installed under `/var/lib/uosserver`, CLI at `/usr/local/bin/uosserver`.
- `uosserver.service` runs as the `uosserver` user and launches one rootless Podman container that carries its own systemd, nginx, MongoDB, and the UniFi applications.
- Ports are forwarded to the host by `pasta`; the full list is in [networking](networking.md#unifi-os-server-rootless-podman-forwarded-by-pasta).
- `uosserver-updater.service` (root) keeps it up to date.
- Data lives in Podman volumes mapped to `/var/lib/unifi` and `/var/lib/mongodb` inside the container.
- Because it listens on the host's own ports, UniFi devices can discover and adopt against the host address directly.

## Update policy

| Mechanism | Covers |
|---|---|
| Manual, pinned version tags, weekly update check | `npm`, `portainer`, `vaultwarden`, `couchdb`, `livesync-cli`, `navidrome`, `slskd`, `SnapOtter`, `it-tools` (its date-style tag is not checked) |
| Nextcloud AIO interface | All `nextcloud-aio-*` containers |
| UniFi OS Server updater | UniFi OS Server |
| `unattended-upgrades` | Ubuntu packages from the release and security pockets |
| Tailscale auto-update | Tailscale |
| Manual | `immich_*`, `n8n`, Docker Engine and other third-party APT packages |

There is no unattended image updater; Watchtower was removed on 2026-11-03. The services it used to update are pinned to the version tag they were running that day. Immich tracks `release`, n8n tracks `latest`, and the Immich database and cache images are pinned by digest.

### Image update check

[`image-update-check.py`](../scripts/image-update-check.py), installed as `/usr/local/bin/image-update-check.py`, is run by `image-update-check.timer` every Monday at 09:00 ([unit files](../system/)) as the admin user. It pulls nothing and changes nothing.

- It finds every running container whose image tag is a version number, so a newly pinned service is covered automatically. It then lists that repository's tags on Docker Hub or GHCR and keeps newer tags of the same form. `2.45.3` is compared only with plain `x.y.z` tags, and `1.0.43-cli` only with `x.y.z-cli`, so variants such as `-alpine`, per-architecture and `pr-123` tags are ignored.
- When something is newer, it posts a list to a Discord channel through a webhook. Each entry gives the current tag, the newest tag, a note when the major version changes, and a release-notes link. If nothing is newer it stays quiet. If a lookup fails, it posts the error.
- The webhook comes from `/etc/discord-notify.env` (see [alerts](#alerts)). `/etc/image-update-check.env` (root, mode 600; [example](../system/image-update-check.env.example)) holds `IGNORE_TAGS`, which lists releases known to be bad as `container:tag` and currently holds `livesync-cli:1.0.44-cli`.
- Run by hand: `sudo systemctl start image-update-check`, or `python3 -I /usr/local/bin/image-update-check.py --dry-run` to print the report instead of posting it. `--test` posts a test message. Logs: `journalctl -u image-update-check`.

## Alerts

Problems are posted to a Discord channel through a webhook, with a mention of the admin's Discord account. The same webhook carries the weekly [image update check](#image-update-check), without a mention. Settings are in `/etc/discord-notify.env` (root, mode 600; [example](../system/discord-notify.env.example)): `DISCORD_WEBHOOK_URL`, `DISCORD_PING_USER_ID`, `NOTIFY_IGNORE_UNITS` (units that should never alert; empty), and the certificate check address and hostname. [`discord-notify.py`](../scripts/discord-notify.py) sends the messages and can be used by hand: `discord-notify.py [--ping] "title" "body"`.

| Source | What triggers it | How |
|---|---|---|
| Any systemd service | The unit fails | A global drop-in, [`service.d/10-notify-failure.conf`](../system/service.d/10-notify-failure.conf), adds `OnFailure=notify-failure@%n.service` to every service. [`notify-failure@.service`](../system/notify-failure@.service) runs [`notify-unit-failure.sh`](../scripts/notify-unit-failure.sh), which posts the unit's status and last 20 log lines. A [second drop-in](../system/notify-failure@.service.d/10-no-recursion.conf) stops the alert unit from triggering itself. Each unit alerts at most once an hour |
| [`homelab-health-check.py`](../scripts/homelab-health-check.py), every 5 minutes ([timer](../system/homelab-health-check.timer)) | A container restart-looping, unhealthy while running, or restarted 3+ times between checks; no successful `homelab-backup` run for 26 hours, or a failed last run; under 10% free on `/` or `/mnt/storage`; the NPM certificate invalid or within 14 days of expiry | Posts each new problem once, with the container's last log lines where relevant, and posts again without a mention when it clears. State is in `/var/lib/homelab-alerts/health-state.json` |
| `smartd` | A SMART warning on any disk | `smartd-runner` runs every script in `/etc/smartmontools/run.d/`; [`20-discord-notify`](../system/smartd-discord-notify) posts the warning, at most once a day per device and warning type. The existing mail to `root` still goes nowhere |

To test: `sudo systemd-run --unit=alert-test /bin/false` should produce an alert within seconds (then `sudo systemctl reset-failed alert-test`). `python3 -I /usr/local/bin/homelab-health-check.py --dry-run` prints what the health check currently sees.
