# Changelog

A dated record of changes made to the server. Each entry corresponds to one commit in this repository: the commit updates the documentation and configuration copies to match what was changed on the host, and the entry says what was done, why, and how it was verified.

Newest first. Finding numbers refer to [`docs/findings.md`](docs/findings.md).

## 2026-11-03

### Cleared the units that failed at boot (finding 12)

**Problem.** The audit found two units failing at every boot. `systemd-networkd-wait-online` timed out after 120 seconds, and `openipmi` failed because the board has no BMC.

**Changed.**

- `systemd-networkd-wait-online` needed no change. The journal shows it timed out only on the boot that ended 2026-10-13. On every boot since, it has finished within a second, because netplan's generated override (`/run/systemd/generator.late/.../10-netplan.conf`) waits for `eno1` only. `wait-for-internet.service` is kept, because `network-online.target` still does not guarantee working DNS.
- Purged `openipmi`, `ipmitool` and `libopenipmi0t64`. Nothing depended on them, and `/dev/ipmi*` does not exist.
- Emptied `NOTIFY_IGNORE_UNITS` in `/etc/discord-notify.env`, so a failure of either unit would now alert like any other.

**Verified.** `systemctl --failed` is empty and no IPMI unit files remain. On the current boot, `systemd-networkd-wait-online` took 60 ms.

### Discord alerts for failures (finding 3)

**Problem.** Nothing alerted on failure. The backup once failed silently for three weeks, and `livesync-cli` restart-looped for 40 hours without anyone noticing.

**Changed.** Alerts now go to the Discord webhook that the image update check uses, with a mention of the admin. Details are in [services](docs/services.md#alerts).

- Moved the webhook to `/etc/discord-notify.env` (root, mode 600), which all three jobs share. Added [`discord-notify.py`](scripts/discord-notify.py) to send the messages.
- **Failed units.** A global drop-in, [`service.d/10-notify-failure.conf`](system/service.d/10-notify-failure.conf), adds `OnFailure=notify-failure@%n.service` to every service. The [alert unit](system/notify-failure@.service) posts the unit's status and log, at most once an hour per unit. It skips `openipmi` and `systemd-networkd-wait-online`, which fail at every boot (finding 12).
- **Health check every 5 minutes.** [`homelab-health-check.py`](scripts/homelab-health-check.py) and [its timer](system/homelab-health-check.timer) cover:
  - containers that are restart-looping or unhealthy
  - the backup failing, or not succeeding for 26 hours
  - less than 10% free space on `/` or `/mnt/storage`
  - the NPM certificate being invalid or within 14 days of expiry

  It posts each problem once, and again when the problem clears.
- **SMART warnings.** Added [`20-discord-notify`](system/smartd-discord-notify) to `/etc/smartmontools/run.d/`.

**Verified.**

- A deliberately failing transient unit (`systemd-run ... exit 3`) produced a Discord alert within seconds.
- A throwaway container with `--restart always` that exits 1 was reported as restart-looping on the next check. Removing it produced a "Resolved" post.
- With thresholds forced past their limits (certificate 400 days, disk 99.5%, backup age 0.01 h), each check reported a problem. With normal thresholds all checks pass.
- Stopped containers that keep an old "unhealthy" status are not reported.
- The image update check still runs with the webhook moved.

- After `DISCORD_PING_USER_ID` was set, a second deliberately failing unit posted an alert that mentions the admin.

### Weekly update check for the pinned images

**Problem.** With every image pinned and Watchtower removed, nothing would show when NPM, Vaultwarden or the other pinned services had a new release, security fixes included.

**Changed.** Added [`image-update-check.py`](scripts/image-update-check.py) and [`image-update-check.timer`](system/image-update-check.timer), which runs every Monday at 09:00. It compares each running container's pinned version tag with newer tags of the same form in its registry and posts any newer releases to a Discord webhook. It never pulls or changes anything. The webhook and an ignore list (`livesync-cli:1.0.44-cli`) are in `/etc/image-update-check.env`, which only root can read. Details are in [services](docs/services.md#image-update-check).

**Verified.**

- A dry run found all seven pinned containers.
- It reported `livesync-cli` 1.0.44 as the only newer release, and nothing once that tag was ignored. That is correct: the other six were checked earlier today and are on their newest releases.
- Test cases picked the right tags. `3.5.2` matched `3.5.2.1`, `3.5.3` and `4.0.0` but not `3.5.3-nouveau`. `1.0.43-cli` skipped `-sha-` builds. `2.45.3` skipped `-alpine` and per-architecture tags.
- A run through systemd succeeded.

- With the webhook in place, a `--test` message and a sample report (run without the ignore list, so it listed `livesync-cli` 1.0.44) both reached the Discord channel. The real service run then posted nothing, as expected.

### Removed Watchtower

**Problem.** After every image it updated was pinned, Watchtower had nothing to update, but it still mounted the Docker socket read-write.

**Changed.** Stopped and removed the `watchtower` container, deleted its service from the `homelab-core` [Compose file](compose/homelab-core/docker-compose.yml), and removed the `nickfedor/watchtower` image and the `homelab-core_default` network, which only Watchtower used. The `watchtower.enable=false` labels are left on the other services; they do nothing now. Nextcloud AIO's own `nextcloud-aio-watchtower` is separate and unchanged.

**Verified.** `docker compose config` accepts the edited file, no `watchtower` container or image remains, and NPM and Portainer kept running.

### Pinned every Watchtower-managed image (finding 14)

**Problem.** Watchtower updated six containers every night at 04:00 from `latest`-style tags, with no record of the previous version to roll back to. Among them were the reverse proxy and the password manager. Earlier the same day, an update of that kind broke `livesync-cli` for about 40 hours.

**Changed.** Pinned each image to the version tag it was already running, after checking that the tag's registry digest matched the running image, so no version changed. Set each one's Watchtower label to `false`.

| Container | Was | Now |
|---|---|---|
| `npm` | `jc21/nginx-proxy-manager:latest` | `2.16.0` |
| `portainer` | `portainer/portainer-ce:latest` | `2.45.3` |
| `vaultwarden` | `vaultwarden/server:latest` | `1.37.5` |
| `couchdb` | `couchdb:3` | `3.5.3` |
| `navidrome` | `deluan/navidrome:latest` | `0.64.2` |
| `slskd` | `slskd/slskd:latest` | `0.26.2` |

The [Compose copies](compose/) match. Watchtower still runs but has nothing to update. The update procedure is in [operations](docs/operations.md).

**Problem found while doing it.** Recreating `npm` and `portainer` together made Portainer take NPM's static address `172.18.0.10`, so NPM failed to start ("Address already in use"). It was fixed by stopping Portainer, starting NPM and starting Portainer again. The reverse proxy was down for about a minute. The recovery steps are now in [operations](docs/operations.md).

**Verified.** All six containers run on their pinned tags, and Vaultwarden and slskd report healthy. Every proxy host answers through NPM with its usual status: 200 for most, a login redirect from `cloud.` and `music.`, and 401 from CouchDB. `tools.` does not answer because SnapOtter has been stopped since before this change (finding 13). A LiveSync round trip after the CouchDB restart succeeded.

**Still open.** NPM's fixed address can still be taken whenever several containers on `proxy` are recreated at the same time.

### Pinned livesync-cli after a broken update

**Problem.** At 04:01 on 2026-11-02, Watchtower updated `livesync-cli` from 1.0.43 to 1.0.44. The new version refuses to start `daemon` when it finds state files written by older versions ("[Legacy state] ... database and Vault owner is unknown"). Docker restarted the container in a loop more than 200 times, and the server's copy of the vault stopped syncing for about 40 hours. The vault folder did not change while the daemon was down, so no edits were left unsynced on the server.

1.0.44 only clears that check after a successful `fetch --force` or `rebuild --force`. `fetch --force` rebuilds the local copy from CouchDB, which is the authoritative copy, so it was the safe direction. It failed three times in a row, each time on a different, random set of files (377, 5 and 22), even though the vault and database copies were identical.

**Changed.**

- Backed up `cli-db/` and `vault/` before touching anything, and confirmed after the fetch attempts that `vault/` still matched the backup exactly.
- Restored `cli-db/` from that backup.
- Pinned the image to `ghcr.io/vrtmrz/livesync-cli:1.0.43-cli` and set its Watchtower label to `false`. The [Compose copy](compose/obsidian-livesync/docker-compose.yml) matches what is deployed. CouchDB is still updated by Watchtower.

**Verified.** The daemon starts, its initial replication completes, it reports "LiveSync active", and it has not restarted. A test file created in `vault/` reached CouchDB within a minute, and deleting it was synced as a deletion.

**Still open.** Move to a newer release once one has fixed the fetch failures. This is a concrete case of finding 14: unattended `latest` updates with no previous version recorded to roll back to.

### Cleaned up leftovers from retired setups (finding 11)

**Problem.** Packages, APT sources, Docker objects and firewall rules from earlier setups were still on the host. They included an unused MongoDB server listening on loopback, held back from upgrades.

**Changed.**

- Stopped and disabled `mongod`, released its hold, and purged `mongodb-org-server`, `mongodb-org-shell`, `mongodb-mongosh-shared-openssl3` and `openjdk-17-jre-headless`. Before that, a check showed only the built-in `admin`, `config` and `local` databases. Deleted `/var/lib/mongodb` and `/var/log/mongodb`.
- Removed the MongoDB 7.0 and Ubiquiti APT sources and their keyrings.
- Removed two Docker networks and four volumes that no container used. The two volumes with data were archived to a root-only folder first.
- Removed five images that no container or Compose file uses, including `containrrr/watchtower`. Images used by stopped containers or by a deployed Compose file were kept.
- Deleted the four UFW rules for ports nothing listens on (1900/udp and three rules for a retired service port). This partly fixes finding 17.

**Verified.** `apt-get update` is clean and no MongoDB packages or units remain. `docker system df` shows 0.1 GB of reclaimable images and no reclaimable volumes. `ufw status` lists 16 rules. Running containers and failed units are the same as before the cleanup.

**Still open.** `ipmitool` is left for finding 12. In finding 17, SSH is still open to anywhere and the rules for Docker-published ports still have no effect.

### Pruned the Docker build cache

**Problem.** Old image builds, mostly from the Quartus image, had left 20.9 GB of build cache, none of it used by a current build (finding 11).

**Changed.** Ran `docker builder prune -f`, which removed 66 of 75 cache entries and freed 20.7 GB.

**Verified.** `docker system df` now shows 202 MB of build cache.

### Removed the Quartus webtop

**Problem.** The Quartus FPGA desktop had been stopped since 2026-10-03 and was no longer needed. It still used 40.5 GB of images, and its deployed Compose file held a password written inline (finding 9).

**Changed.**

- Ran `docker compose down --rmi local` for the stack, which removed the container and the locally built 14.1 GB image.
- Removed the `raetro/quartus:13.0sp1` and `raetro/quartus:17.1` images (26.4 GB).
- Deleted `/mnt/storage/quartus`. The projects folder held only one empty folder.
- Its NPM proxy host had already been deleted, so nothing needed changing there.

**Verified.** `docker ps -a`, `docker images` and `docker network ls` show nothing left for Quartus, and the directory is gone.

### Lil Uzi Vert added to the leaks organiser

**Changed.** Added Lil Uzi Vert (matched by "lil uzi", "lil uzi vert" or "uzi") to [`leaks-organize.py`](scripts/leaks-organize.py), reinstalled it, and created `library/leaks/Lil Uzi Vert/`.

**Verified.** A dry run against the current downloads moved nothing, and a run through systemd succeeded.

### Folder and auto-tagging for unreleased music

**Problem.** Leaked or unreleased songs downloaded through slskd land next to official albums, usually with messy or missing tags. In Navidrome that shows up as "Unknown Artist", scattered one-song albums, or songs merged into official albums.

**Changed.**

- Installed `python3-mutagen`.
- Created `library/leaks/{Juice WRLD,Playboi Carti,Travis Scott,Yeat}`.
- Added [`leaks-organize.py`](scripts/leaks-organize.py) and [`leaks-organize.timer`](system/leaks-organize.timer), which runs every 15 minutes. It moves leak folders out of `library/soulseek/` by artist and normalises their tags. Details are in [`docs/services.md`](docs/services.md#leaks-organiser).

**Verified.**

- A dry run against the current downloads moved nothing. "Luh Leakyz Vol. 1" and the official albums were correctly ignored.
- A test folder `Carti Unreleased 2019 [FLAC 16bit]` holding a copied FLAC with its title set to "Track 07" was moved to `leaks/Playboi Carti/`. It was tagged album "Carti Unreleased 2019", title "Kid Cudi", genre Unreleased. Navidrome showed it as its own album, while the official "Whole Lotta Red" kept 24 songs. A second run changed nothing. The test file was then deleted.
- The timer's first run through systemd succeeded.

### Removed restic snapshots left over from the old hostname

**Problem.** The host's name changed from `nath-serv` to `singularity`. restic groups snapshots by host, so `forget --keep-last 3` never pruned the three `nath-serv` snapshots (2026-10-23, 2026-10-24, 2026-10-25).

**Changed.** Ran `restic forget 57654b60 fdb06452 d0cfca0d --prune`.

**Verified.** `restic check` found no errors. The repository now holds the three newest `homelab-daily` snapshots and one `homelab-music` snapshot. Only 11.5 MiB was freed, because nearly all of the old snapshots' data was shared with the newer ones.

### Music added to the nightly backup

**Problem.** Nothing under `/mnt/storage/music` was backed up. That includes the Navidrome database, which holds stars, play counts and playlists.

**Changed.** [`homelab-backup.sh`](scripts/homelab-backup.sh) has two new steps:

- **"music database"** copies Navidrome's SQLite database with the online backup API, plus the Discover Weekly state and `slskd.yml`, into staging.
- **"music library"** backs up `/mnt/storage/music/library` straight from disk as its own snapshot (tag `homelab-music`). It refuses to run if the library would leave less than 20 GB free on the NVMe that holds the repository.

Also removed a `__pycache__` directory that had been committed by mistake, and added it to `.gitignore`.

**Verified.**

- Ran `homelab-backup.service` by hand. Every step reported `ok`. The music snapshot added 2.47 GiB (124 files, 11 s), and `restic forget` still kept three snapshots per group.
- Restored `navidrome.db` from the new snapshot with `restic dump`: `integrity_check` is `ok`, with 118 songs and the 25-song Discover Weekly playlist. The music snapshot lists the same 118 FLAC files as the library on disk.

**Still open.**

- The repository is still on the same machine (see [finding 2](docs/findings.md#2-backups-do-not-protect-against-losing-the-machine)), and the library will compete with the OS for NVMe space as it grows.

### Discover Weekly playlist from ListenBrainz recommendations

**Problem.** The music server only plays what is already in the library, so it had no way to suggest new music the way Spotify's radios and Discover Weekly do.

**Changed.**

- New [`discover-weekly.py`](scripts/discover-weekly.py) at `/usr/local/bin/`, run every Monday at 08:00 by [`discover-weekly.timer`](system/discover-weekly.timer). It takes ListenBrainz's Weekly Exploration playlist and unheard recommendations, downloads 25 new songs through slskd, files them under `library/discover/<week>/`, and writes `Discover Weekly.m3u`, which Navidrome imports as a synced playlist. After 28 days it deletes the songs that weren't starred, rated 4+, or played twice. How it chooses and matches songs is in [`docs/services.md`](docs/services.md#discover-weekly-job).
- slskd's API is now also published on `127.0.0.1:5030` for the job ([Compose file](compose/music/docker-compose.yml)). slskd was recreated with no transfers in progress.
- The `music.` and `slskd.` proxy hosts were added in the NPM UI.

**Verified.**

- A dry run picked 6 songs and found FLAC sources for all of them.
- A 3-song run downloaded, moved, and listed the songs, and Navidrome logged `Adding synced playlist` for "Discover Weekly", owned by the admin user.
- The first full run, through the systemd unit, took 14 minutes and ended with 25/25 songs. Three sources rejected or stalled and the next source was used. Navidrome shows the playlist with 25 songs (75 minutes). No files or empty folders were left in `library/soulseek/`.
- The timer's next run is Monday 2026-11-09 08:00.

**Still open.** The ListenBrainz Weekly Exploration playlist last generated on 2026-09-14 and has expired, so this week's songs all came from the general recommendations. The music data is still not in the restic backup.

### Music server: Navidrome and slskd

**Problem.** Replacing a Spotify subscription needs a player, a source of music, and a way to discover new music. This change covers the first two.

**Changed.**

- New Compose project `music` at `~/homelab/music` ([Compose file](compose/music/docker-compose.yml), [`.env.example`](compose/music/.env.example)) with Navidrome 0.64.2 and slskd 0.26.2, both on the `proxy` network and labelled for Watchtower.
- Created `/mnt/storage/music/{library,navidrome,slskd,incomplete}`, owned by UID 1000. slskd downloads into `library/soulseek/`, which Navidrome rescans every 15 minutes.
- slskd shares no directories. Port 50300/tcp is published but not forwarded on the router.
- A Soulseek account was registered on first login; its credentials and the slskd UI login are in `~/homelab/music/.env` (mode 600).

**Verified.** Both containers are up and slskd reports healthy. slskd logged `Logged in to the Soulseek server`. A test search through the slskd API returned 552 files from 252 users. Navidrome's first scan found an empty library, as expected.

**Still open.** Proxy hosts `music.` and `slskd.` need to be added in the NPM UI. The Navidrome admin account has not been created yet. The music data is not in the restic backup. The ListenBrainz discovery job is still to be built.

## 2026-10-25

### Rocketbook notes filed by class and lecture

**Problem.** Every Rocketbook scan landed in `Rocketbook Inbox`, while the vault's notes are organised as `<class>/Lecture <n>/`.

**Changed.**

- The workflow's "Build note" node reads a class and lecture code from the email subject (Rocketbook Smart Title, e.g. `##DE L3a##`) or from a `##...##` code in the scanned text, and sets `class` and `lecture` properties. Rocketbook's `.pdf-<send time>` suffix is now dropped from Smart Title subjects. Re-imported, re-published, restarted n8n.
- New [`/usr/local/bin/rocketbook-filer.py`](scripts/rocketbook-filer.py), started by [`rocketbook-filer.path`](system/rocketbook-filer.path) whenever the inbox changes. It moves notes with both properties, plus their embedded scans, into `<class>/Lecture <n>/`. It accepts only existing top-level class folders and lecture values like `3` or `3a`, and creates the lecture folder if needed. n8n's mount is unchanged (inbox only).

**Verified.** The test workflow sent three fake emails:

- Subject `DE L9b pipeline test.pdf-…`: filed to `Digital Electronics/Lecture 9/` as `… DE L9b pipeline test.md` with `lecture: "9b"`.
- Default `RB …` subject: stayed in the inbox.
- `##sts lecture 9##` in the email text: filed to `Science, Tech, and Society/Lecture 9/`.

In each case the PDF moved with the note, and the journal shows one `filed … -> …` line per note. Test files and folders were removed afterwards. The real workflow is active again after the restart.

**Still open.** The exact subject format Rocketbook uses for Smart Titles has not yet been seen on a real scan.

### Rocketbook notes named by scan time

**Problem.** The first real scan arrived and was handled correctly, but Rocketbook's default subject (`RB 2026-08-26 19.41.20.pdf-10/25/2026-16.25.20`) made the file name long and unreadable, and the note was dated by the email instead of the scan.

**Changed.** "Prepare files" now recognises the default subject: the name becomes `<scan time> Rocketbook scan` and `created` is the scan time, with a new `received` field for the email time. Other subjects are unchanged. Re-imported, re-published, restarted n8n. Renamed the first scan's note and PDF to the new scheme and fixed its embed.

**Verified.** The real scan (execution 32) produced the PDF and a note with the scan's text and was synced. The test copy, run with a default-style subject, produced `2026-08-26 194120 Rocketbook scan.md` with `created: 2026-08-26T19:41:20-04:00`. n8n logged the workflow as activated after the restart.

### Rocketbook scans now go to the Obsidian vault through n8n

**Problem.** The Rocketbook workflow in n8n targeted Trilium's ETAPI, and Trilium has been removed. It had never been activated.

**Changed.**

- Exported the old workflow as a backup, then replaced it (same ID, renamed "Rocketbook → Obsidian") with the flow described in [`docs/services.md`](docs/services.md#workflow-rocketbook--obsidian). It writes files into the vault instead of calling an API; LiveSync's server client syncs them.
- Mounted the vault's `Rocketbook Inbox/` folder into n8n ([Compose file](compose/n8n/docker-compose.yml)); a backup of the previous Compose file is `~/n8n/docker-compose.yml.bak-2026-10-25` on the host.
- Imported a test copy with a manual trigger.
- Published the workflow with `n8n publish:workflow` and restarted n8n.

**Verified.**

- The test copy ran successfully. It wrote the PDF and a note with the embed, the email text and the PDF's text, and `livesync-cli` uploaded them to CouchDB. Test files were then deleted.
- n8n logged `Activated workflow "Rocketbook → Obsidian"` with no IMAP errors. No unread mail was waiting, so nothing was imported.

**Still open.** ~~End-to-end test with a real Rocketbook scan~~ (done, see above). The unused Trilium ETAPI credential ("Header Auth account") can be deleted in the n8n UI.

### Deleted the Trilium archive; phone client connected

**Changed.**

- Removed the `trilium files` step from [`homelab-backup.sh`](scripts/homelab-backup.sh) before deleting the data, so the nightly run cannot fail on a missing source (a failed step would also skip pruning). Deployed to `/usr/local/bin`.
- Deleted `/mnt/storage/trilium` (data, Trilium's own backups, Compose file). Copies remain in the existing restic snapshots until retention (last 3) rotates them out.
- The phone joined LiveSync from the Setup URI and fetched from the server.

**Verified.**

- The deployed backup script matches the repo copy, passes `bash -n`, and no longer mentions Trilium.
- CouchDB logs show the phone's initial `_changes` and `_bulk_get` reads with no database delete or rebuild; the document count rose only by normal edits (373 to 398).

**Still open.** Delete the `notes.` proxy host in the NPM UI.

### Removed Trilium; deleted the proxy test database

**Problem.** Notes now live in Obsidian with LiveSync, and the desktop client has been verified to sync in both directions, so Trilium is no longer needed. A leftover test database, `zz_proxytest`, was also sitting in CouchDB.

**Changed.**

- `docker compose down` in `/mnt/storage/trilium` removed the container; the `triliumnext/trilium` image was deleted.
- Kept `/mnt/storage/trilium` (data, Trilium's own backups, Compose file) as an archive. It stays in the nightly backup.
- Deleted the CouchDB database `zz_proxytest`.

**Verified.** `docker ps -a` shows no `trilium` container. `notes.example.duckdns.org` returns 502. CouchDB's `_all_dbs` lists only `_replicator`, `_users`, `obsidiannotes`.

**Still open.** Delete the `notes.` proxy host in the NPM UI. Decide whether to delete the Trilium archive. Phone client, when wanted.

### Restored the LiveSync database after an accidental overwrite; first client connected

**Problem.** While setting up the first Obsidian client, the setup on the device rebuilt the server database from a new, empty vault (LiveSync's "Overwrite server data" path). CouchDB was left holding only Obsidian's default `Welcome.md`. The server's plain-Markdown copy in `vault/` was unaffected.

**Changed.**

- Stopped `livesync-cli` straight away so it could not mirror the empty state into `vault/`.
- Confirmed `vault/` was still identical to the converted notes, and saved copies of it and of `couchdb-data/` before touching anything.
- Rebuilt CouchDB from `vault/` with `livesync-cli rebuild --force`, then had the client run "Reset synchronisation on this device" (fetch).
- Unlocked the remote with `livesync-cli unlock-remote` once both clients (the desktop vault and `livesync-cli`) had been accepted. A rebuild leaves the remote locked, and a locked remote refuses sync from any client the lock has not accepted.

**Verified.**

- After the rebuild, a fresh CLI fetch into an empty folder matched the original conversion (41/41 files).
- Server → device: a note created in `vault/` appeared on the desktop client.
- Device → server: an edit typed on the desktop reached CouchDB and then `vault/`.
- A deletion in `vault/` was pushed to CouchDB.
- `livesync-cli` syncs every 60 seconds (`periodicReplication`, the Setup URI default), not live, so changes reach `vault/` within about a minute.

**Still open.** Phone client; retire Trilium.

**Lesson.** On every device after the first, open the Setup URI in an empty vault and choose to fetch from the server. "Overwrite server data" / "Rebuild" replaces the server's contents with the device's vault.

### Added the `obsidian.` proxy host for LiveSync

**Changed.** Created the `obsidian.example.duckdns.org` proxy host in NPM (by hand in the UI): backend `couchdb:5984` over http, wildcard certificate, Force SSL, websockets, block common exploits, and advanced config `proxy_buffering off`, `client_max_body_size 50M`, `proxy_read_timeout 3600s`.

**Verified.**

- HTTPS presents a valid certificate; plain HTTP redirects with 301; an anonymous request gets 401 from CouchDB.
- With credentials, `/obsidiannotes` is reachable through the proxy.
- A CORS preflight from origin `app://obsidian.md` returns 204 with `Access-Control-Allow-Origin: app://obsidian.md` and credentials allowed.
- A 15-second long-poll on `_changes` was held open for the full time and not cut off by the proxy.

**Still open.** Set up the Obsidian clients from the Setup URI, then retire Trilium.

### Migrated notes from Trilium to Obsidian with Self-hosted LiveSync

**Problem.** Notes were kept in Trilium. The goal was to move them to an Obsidian vault and sync it between devices through [Self-hosted LiveSync](https://github.com/vrtmrz/obsidian-livesync), with this host as the sync server.

**Changed.**

- Converted the Trilium database to Markdown with a small converter, [`scripts/trilium-to-obsidian/convert.js`](scripts/trilium-to-obsidian/convert.js), run against a read-only snapshot of `document.db`. It keeps the note tree as folders, turns tables and code blocks into GFM, extracts the 7 inline images to `_attachments/` as `![[...]]` embeds, exports the one PDF file note as a `.pdf`, and renames Journal day notes to `Journal/YYYY/YYYY-MM/YYYY-MM-DD.md` to match Obsidian's daily-notes format. Each note keeps its Trilium created/modified times in front matter and as the file's mtime. Result: 34 notes (4 of them empty in Trilium too), 7 images, 1 PDF. Trilium's system notes (`_hidden`, launchers, and so on) were not exported.
- Added the Compose project [`obsidian-livesync`](compose/obsidian-livesync/docker-compose.yml) in `/mnt/storage/obsidian-livesync`: `couchdb` (CouchDB 3.5.3) and `livesync-cli`, the plugin's headless client, which mirrors the vault as plain Markdown into `vault/` on the host. Both are on `proxy` with no published ports and are labelled for Watchtower.
- Provisioned CouchDB with LiveSync's own `couchdb-init.sh` (run in a `denoland/deno` container): single node, authentication required, CORS for the Obsidian origins, raised size limits, database `obsidiannotes`.
- Generated an end-to-end encryption passphrase and persistent Setup URIs with LiveSync's `generate_setup_uri.ts`: one for clients at `https://obsidian.example.duckdns.org`, one with the same ID recovery code for the CLI at `http://couchdb:5984`. Secrets are in `secrets/` (mode 600) beside the Compose file and are not in this repo.
- Uploaded the vault with `livesync-cli rebuild`, then started the CLI daemon.
- Added `/mnt/storage/obsidian-livesync` to the nightly backup ([`homelab-backup.sh`](scripts/homelab-backup.sh)).
- Trilium is left running and unchanged until every device is on Obsidian.

**Verified.**

- Word count of the converted Markdown (12,362) matches the text of the Trilium HTML (12,243; the difference is Markdown table and list syntax). No raw `<table>`, `<figure>` or `<td>` HTML is left, and every image embed resolves to a file.
- `rebuild` reported 41 files processed, 0 failed. A separate CLI instance set up from scratch ran `fetch` into an empty folder, and `diff -r` against the source vault found no differences.
- Documents in CouchDB are ciphertext: none of the note text or file names appear in `_all_docs?include_docs=true`.
- Anonymous requests to CouchDB return 401; the provisioned settings survive a container restart.
- A file created in `vault/` reached CouchDB through the daemon, including after CouchDB was restarted.
- As root, `cp -a /mnt/storage/obsidian-livesync` (the new backup step) completes.

**Still open.**

- ~~The `obsidian.` proxy host still has to be created in the NPM UI.~~ Done, see above.
- Obsidian clients (laptop, phone) still have to be set up from the Setup URI.
- Retire Trilium once the clients are syncing: stop the container and remove the `notes.` proxy host. The data stays in the backups.
- An inactive n8n workflow ("My workflow") still targets Trilium's ETAPI for a Rocketbook inbox.

## 2026-10-13

### Disabled SSH password login (finding 19)

**Problem.** SSH was documented as key-only and `sshd_config` said `PasswordAuthentication no`, but the daemon was accepting passwords. An installer-generated drop-in, `/etc/ssh/sshd_config.d/50-cloud-init.conf`, set `PasswordAuthentication yes`, and drop-ins are read before the main file. Every login since mid-August had in fact used a password; the one authorised key did not belong to any device in use.

**Changed.**

- Generated a key on the laptop and added its public half to the admin user's `authorized_keys`, after checking that its fingerprint matched the one printed at generation.
- Confirmed a successful key-only login from the laptop before touching the server configuration, to avoid a lockout.
- Set [`50-cloud-init.conf`](system/sshd_config.d/50-cloud-init.conf) to `PasswordAuthentication no`, ran `sshd -t`, and reloaded `ssh`.

**Verified.**

- The server log shows `Accepted publickey` with the laptop key's fingerprint.
- `sudo sshd -T` reports `passwordauthentication no` and `kbdinteractiveauthentication no`.
- A probe that offers no key is refused with `Permission denied (publickey)`; before the change the same probe listed `publickey,password`.

**Still open.** Port 22 is still allowed from anywhere in UFW (finding 17), `X11Forwarding` is still on, and an unused older key is still authorised (finding 16).

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
