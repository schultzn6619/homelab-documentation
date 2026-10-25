# Changelog

A dated record of changes made to the server. Each entry corresponds to one commit in this repository: the commit updates the documentation and configuration copies to match what was changed on the host, and the entry says what was done, why, and how it was verified.

Newest first. Finding numbers refer to [`docs/findings.md`](docs/findings.md).

## 2026-10-25

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

- The `obsidian.` proxy host still has to be created in the NPM UI; until then clients cannot reach the server.
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
