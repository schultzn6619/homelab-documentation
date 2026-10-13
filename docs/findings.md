# Audit findings

Results of a full review of the live host on **2026-10-13**, ordered by priority. Each item states what was observed, why it matters, and a recommended fix. Nothing here has been changed on the server yet.

| # | Finding | Priority |
|---|---|---|
| 1 | [Nightly backups have been failing since 2026-09-22](#1-nightly-backups-have-been-failing-since-2026-09-22) | High |
| 2 | [Backups do not protect against losing the machine](#2-backups-do-not-protect-against-losing-the-machine) | High |
| 3 | [Nothing alerts on failure](#3-nothing-alerts-on-failure) | High |
| 4 | [Reboot pending for a kernel update](#4-reboot-pending-for-a-kernel-update) | Medium |
| 5 | [`homelab-core` Compose file has drifted from what is deployed](#5-homelab-core-compose-file-has-drifted-from-what-is-deployed) | Medium |
| 6 | [Three containers publish ports on every interface](#6-three-containers-publish-ports-on-every-interface) | Medium |
| 7 | [Stale AAAA record in public DNS](#7-stale-aaaa-record-in-public-dns) | Medium |
| 8 | [Nextcloud AIO admin interface is not reachable](#8-nextcloud-aio-admin-interface-is-not-reachable) | Medium |
| 9 | [Credentials written inline](#9-credentials-written-inline) | Medium |
| 10 | [Vaultwarden still allows sign-ups](#10-vaultwarden-still-allows-sign-ups) | Medium |
| 11 | [Leftovers from retired setups](#11-leftovers-from-retired-setups) | Low |
| 12 | [Two units fail at every boot](#12-two-units-fail-at-every-boot) | Low |
| 13 | [Unmanaged and stopped containers](#13-unmanaged-and-stopped-containers) | Low |
| 14 | [Update coverage and image pinning are uneven](#14-update-coverage-and-image-pinning-are-uneven) | Low |
| 15 | [Thermal watchdog matches more than it should](#15-thermal-watchdog-matches-more-than-it-should) | Low |
| 16 | [Minor host hygiene](#16-minor-host-hygiene) | Low |

---

## 1. Nightly backups have been failing since 2026-09-22

**Observed.** `homelab-backup.service` has exited with status 1 on 22 consecutive nights. The last successful run, and the newest of the three restic snapshots, is from 2026-09-21.

```
homelab-backup.sh: Error response from daemon: No such container: unifi-db
```

The script runs `mongodump` inside a Docker container called `unifi-db`. That container went away around 2026-09-21, when UniFi moved to UniFi OS Server. Because the script uses `set -e`, it stops at that line. The two PostgreSQL dumps before it succeed and are left in staging every night, but the Vaultwarden, Trilium, and Nextcloud copies and the `restic backup` after it never run.

**Impact.** No service has had a backup for three weeks, including the password manager.

**Fix.**

1. Remove the `mongodump` and `docker cp` block from `/usr/local/bin/homelab-backup.sh`.
2. Back up UniFi from its own scheduled backup files instead (Settings, System, Backups in the UniFi UI), by adding the directory they are written to as a staging source, or by downloading a backup after significant changes.
3. Run `sudo systemctl start homelab-backup.service` and confirm with `restic snapshots`.
4. Make each source independent so that one failure cannot cancel the rest: wrap each step in a function, record failures, continue, and exit non-zero at the end.

## 2. Backups do not protect against losing the machine

**Observed.**

- The restic repository is at `/var/backups/restic-repo` on the NVMe, the same disk as the operating system and in the same chassis as the data.
- Immich's photo and video library (17 GB, the only irreplaceable bulk data) is not in the backup. Only its database is.
- n8n, Nginx Proxy Manager, and Portainer state are not included.
- Retention is three snapshots, so three days of history.
- Vaultwarden and Trilium are copied with `cp -a` while running. A SQLite database copied mid-write with its WAL file can be inconsistent.
- Nextcloud's data directory is first copied in full to staging on the NVMe and then stored again in the repository on the same disk, so it needs twice its size in free space on the root filesystem as it grows.
- No restore has been tested.

**Impact.** A failed NVMe loses the OS and all backups together. Theft, fire, or a power-supply fault loses everything. The data tier is a single HDD behind a single writeback cache SSD, so backups are the only redundancy it has.

**Fix.**

1. Add a second restic repository off the host: an external USB disk, another machine over SFTP, or an object-storage bucket. restic encrypts client-side, so an untrusted remote is acceptable. `restic copy` can replicate the local repo.
2. Back up `/mnt/storage` paths directly with restic rather than copying to staging first. Keep staging only for database dumps.
3. Include `/mnt/storage/immich/library`, `/mnt/storage/n8n`, the Compose directories with their `.env` files, `/usr/local/bin/*.sh`, and `/etc/systemd/system/*.service|*.timer`.
4. For SQLite services use `sqlite3 <db> ".backup '<dest>'"`, or stop the container for the copy.
5. Use a time-based retention policy, for example `--keep-daily 7 --keep-weekly 4 --keep-monthly 6`.
6. Schedule a quarterly restore test into a scratch directory.

## 3. Nothing alerts on failure

**Observed.** The backup failed silently for three weeks. `smartd` is configured to mail `root`, but the host has no mail transport. There is no monitoring of units, disks, certificates, or container health.

**Fix.** The lightest option is a push notification on unit failure:

```ini
# /etc/systemd/system/notify-failure@.service
[Unit]
Description=Notify on failure of %i

[Service]
Type=oneshot
ExecStart=/usr/local/bin/notify.sh "%i failed on %H"
```

Add `OnFailure=notify-failure@%n.service` to `homelab-backup.service` and `thermal-watchdog.service`, and have `notify.sh` post to ntfy, a chat webhook, or an existing n8n webhook. A dead-man's-switch check (for example a healthchecks-style ping at the end of a successful backup) also catches the case where the timer never fires. Point `smartd` at the same script with `-M exec`.

## 4. Reboot pending for a kernel update

**Observed.** `/var/run/reboot-required` is present. Kernel 7.0.0-38 is installed; 7.0.0-34 has been running for 17 days. 19 packages are upgradable, including `openssh-server`, `docker-ce`, `containerd.io`, and `tailscale`, which unattended-upgrades does not handle because they are outside its allowed origins or held back.

**Fix.** `sudo apt upgrade`, then reboot following the [runbook](operations.md#reboot). Consider adding the Docker and Tailscale origins to `Unattended-Upgrade::Allowed-Origins`, or schedule a monthly maintenance window.

## 5. `homelab-core` Compose file has drifted from what is deployed

**Observed.** [`compose/homelab-core/docker-compose.yml`](../compose/homelab-core/docker-compose.yml) still defines a `twingate` connector with a static address of `172.18.0.3` on `proxy`. No such container exists; remote access moved to Tailscale. The address `172.18.0.3` is now held by `n8n`. Comments in the file still describe the NPM admin UI as "Twingate-only access".

**Impact.** A plain `docker compose up -d` in that directory would try to create the connector and fail with "address already in use". The `.env` file still holds Twingate tokens.

**Fix.** Delete the `twingate` service and its `.env` entries, revoke the connector tokens in the Twingate admin console, remove the unused `twingate/connector` image, and correct the comments.

## 6. Three containers publish ports on every interface

**Observed.**

| Container | Published as |
|---|---|
| `it-tools` | `0.0.0.0:8097` and `[::]:8097` |
| `SnapOtter` | `0.0.0.0:1349` and `[::]:1349` |
| `nextcloud-aio-apache` | `0.0.0.0:11000` and `[::]:11000` |

Every other published port is bound to the LAN address. Docker-published ports bypass UFW, Docker's IPv6 NAT is enabled, and the host holds a global IPv6 address. Whether these ports can be reached from the internet over IPv6 therefore depends entirely on the upstream routers' IPv6 firewalls, not on anything configured on this host. These three services also answer on the Tailscale interface without going through the proxy or TLS.

**Fix.**

- Move IT-Tools and SnapOtter into a Compose file on the `proxy` network with no published ports, and point their proxy hosts at `it-tools:80` and `SnapOtter:1349`.
- For Nextcloud, set `APACHE_IP_BINDING` on the master container (`127.0.0.1`, or leave unpublished since NPM reaches it by name on `proxy`), then stop and start the containers from the AIO interface.
- Confirm from an outside network that the host's global IPv6 address does not answer on those ports. If IPv6 is not needed for containers, remove `"ipv6": true` and `"ip6tables": true` from `daemon.json`.

## 7. Stale AAAA record in public DNS

**Observed.** The DuckDNS domain's public AAAA record points to a global IPv6 address in a prefix the host no longer has. The A record correctly points to the LAN address.

**Impact.** Clients that prefer IPv6 try the dead address first and wait for a timeout before falling back to IPv4, which looks like intermittent slowness. It also publishes a previous address of the host for no benefit.

**Fix.** Clear the record with DuckDNS's update API (`clear=true` removes both records; then set the IPv4 value again), and make sure no updater script or router DDNS client is still sending an IPv6 address.

## 8. Nextcloud AIO admin interface is not reachable

**Observed.** The Compose file publishes `192.168.1.10:8091` to container port `8092`. The AIO master container listens on 80, 8080, and 8443; nothing listens on 8092, and connections to 8091 are refused. The interface answers only on the container's own address.

**Impact.** Nextcloud updates, AIO backups, and container start and stop cannot be driven from a browser without a workaround.

**Fix.** Change the mapping to `"192.168.1.10:8091:8080"` and run `docker compose up -d` in `~/nextcloud`. The interface is then at `https://192.168.1.10:8091` with a self-signed certificate. Reach it by address and port, as AIO expects, rather than through the reverse proxy.

## 9. Credentials written inline

**Observed.**

- The deployed Quartus Compose file contains the desktop username and password in plain text. The file is world-readable.
- `/usr/local/bin/homelab-backup.sh` (mode 755) contains a database password on the `mongodump` command line.
- Database dumps in `/var/backups/staging` are created world-readable (644 in a 755 directory).
- Vaultwarden's data directory, including its database and RSA signing key, is world-readable on the host.

**Impact.** Any local account or any process that can read the host filesystem can read these. Only two local accounts exist, so exposure is limited, but the files should not rely on that.

**Fix.** Move the Quartus values to a `.env` file with mode 600, as in this repo's copy, and change the password. Removing the `mongodump` block (finding 1) removes the second. Add `umask 077` at the top of the backup script and `chmod 700 /var/backups/staging`. `chmod 700 /mnt/storage/vaultwarden/data`.

## 10. Vaultwarden still allows sign-ups

**Observed.** `SIGNUPS_ALLOWED=true`, with a comment saying to turn it off after creating the account.

**Impact.** Anyone who can reach the service on the LAN or tailnet can create an account on the password manager.

**Fix.** Set `SIGNUPS_ALLOWED=false` and `docker compose up -d`. Use invitations for any additional users. Consider setting `ADMIN_TOKEN` (as an Argon2 hash) only if the admin page is needed.

## 11. Leftovers from retired setups

**Observed.**

- A MongoDB 7.0 server (`mongod`, package on hold) runs on the host on loopback with an essentially empty data directory and no client connections. UniFi OS Server bundles its own database and does not use it.
- The Ubiquiti APT source and `openjdk-17-jre-headless` remain from a native UniFi install.
- Two Docker networks with no containers, four volumes with no containers, and images for retired stacks. `docker system df` reports 26.6 GB of reclaimable images and 17.2 GB of build cache.
- An unused `containrrr/watchtower` image and a second `raetro/quartus` tag (16.1 GB) that the current Dockerfile does not use.
- UFW rules were added for services that no longer exist. The live rule list could not be read during the audit.

**Fix.** After checking nothing depends on them:

```bash
sudo systemctl disable --now mongod && sudo apt purge mongodb-org-server mongodb-org-shell
sudo rm /etc/apt/sources.list.d/100-ubnt-unifi.sources /etc/apt/sources.list.d/mongodb-org-7.0.sources
docker network prune
docker volume ls -f dangling=true      # review, then remove by name
docker image prune -a                  # removes every image not used by a container
docker builder prune
sudo ufw status numbered               # delete rules for retired ports
```

Images referenced by a stopped container, such as Quartus, are kept by `docker image prune -a`. Review what each command lists before confirming.

## 12. Two units fail at every boot

**Observed.**

- `systemd-networkd-wait-online.service` times out after 120 seconds. Boot is delayed by two minutes and `network-online.target` is not a reliable signal, which is why `wait-for-internet.service` exists.
- `openipmi.service` fails because the board has no BMC.

**Fix.** For the first, find which link never reaches "configured" with `networkctl status -a`. Usually the cure is to mark non-essential links as optional in netplan (`optional: true`) or to override the unit to wait for one interface: `ExecStart=/usr/lib/systemd/systemd-networkd-wait-online --interface=eno1 --timeout=30`. For the second, `sudo apt purge openipmi ipmitool`.

## 13. Unmanaged and stopped containers

**Observed.**

- `it-tools` and `SnapOtter` were created with `docker run`. Their configuration exists only in the running containers.
- `SnapOtter` has restart policy `no` and will stay down after the next reboot.
- `quartus` is stopped, so `quartus.example.duckdns.org` returns 502.
- The `it-tools` image has not been updated upstream in two years.

**Fix.** Put both `docker run` services into Compose (see finding 6). Either start Quartus on demand and accept the 502, or disable its proxy host while it is stopped.

## 14. Update coverage and image pinning are uneven

**Observed.** Watchtower updates four containers unattended, all on the `latest` tag, including the reverse proxy and the password manager. `n8n` tracks `latest` but is not labelled, so it only changes when pulled by hand. Immich tracks `release`. Only two images are pinned by digest.

**Impact.** A breaking upstream release lands at 04:00 with no review and no recorded previous version to roll back to. Because backups are not running, there is no pre-update restore point either.

**Fix.** Pin a version tag for anything stateful and let Watchtower follow patch releases only, or switch Watchtower to notify-only (`WATCHTOWER_MONITOR_ONLY=true`) and update by hand. At minimum, run the backup before the update window: the timer already fires at 00:00, four hours ahead of Watchtower, once it works again.

## 15. Thermal watchdog matches more than it should

**Observed.** In the warning tier the script throttles `$(pgrep -f python3)`, which is every Python process on the host, including `fail2ban`, `unattended-upgrades`, and `networkd-dispatcher`, not only Immich's ML workers. It clears the throttle with `pkill -f cpulimit`. The log file has no rotation. The watchdog last acted on 2026-08-21.

**Fix.** Limit the container instead of host processes, which also removes the need for `cpulimit`:

```bash
docker update --cpus 6 immich_machine_learning    # throttle
docker update --cpus 12 immich_machine_learning   # clear
```

Or set a permanent `cpus:` limit on the ML service in the Compose file so the watchdog is only a last resort. Log with `logger -t thermal-watchdog` so entries go to the journal.

## 16. Minor host hygiene

- **Firmware:** UEFI F50 is from 2019. Later releases for this board carry AGESA security and stability fixes.
- **Unneeded services:** `ModemManager`, `multipathd`, and `open-iscsi` are enabled by default and serve no purpose here. `sudo systemctl disable --now ModemManager multipathd open-iscsi iscsid.socket`.
- **SSH:** `X11Forwarding yes` is not needed on a headless server. Confirm effective settings with `sudo sshd -T`, because drop-in files override `sshd_config`.
- **Container logs:** the json-file driver has no size limit. Add `"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}` to `daemon.json`.
- **Resource limits:** no container has memory or CPU limits.
- **Host address:** the LAN address comes from DHCP while Compose files and proxy hosts hard-code it. Make sure the router has a static lease for it.
- **Time zones:** containers do not all set the same `TZ` as the host; align them so logs and schedules agree.
- **Fan monitoring:** only the motherboard's secondary sensor chip is detected and its fan inputs read 0 RPM, so a failed fan would only show up as temperature.
- **Proxy host definitions** exist only in the NPM volume. Back that volume up (finding 2) or export the configuration.
