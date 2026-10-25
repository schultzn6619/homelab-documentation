# Changelog

A dated record of changes made to the server. Each entry corresponds to one commit in this repository: the commit updates the documentation and configuration copies to match what was changed on the host, and the entry says what was done, why, and how it was verified.

Newest first. Finding numbers refer to [`docs/findings.md`](docs/findings.md).

## 2026-10-25

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
