# Operations runbook

Day-to-day procedures for this host. Paths are the real ones on the server; `~` is the admin user's home directory.

## Where things are

| Stack | Directory |
|---|---|
| `homelab-core` (NPM, Portainer, Watchtower) | `~/homelab-core` |
| `immich` | `~/immich` |
| `nextcloud` (AIO master) | `~/nextcloud` |
| `n8n` | `~/n8n` |
| `obsidian-livesync` | `/mnt/storage/obsidian-livesync` |
| `vaultwarden` | `/mnt/storage/vaultwarden` |
| `quartus` | `/mnt/storage/quartus` |
| Custom scripts | `/usr/local/bin/homelab-backup.sh`, `/usr/local/bin/thermal-watchdog.sh` |
| Custom units | `/etc/systemd/system/` |

`docker compose ls -a` prints the same list with the path of each Compose file.

## Daily health check

```bash
systemctl --failed                                   # should be empty
docker ps -a --format 'table {{.Names}}\t{{.Status}}' # everything Up, healthy where reported
df -h / /mnt/storage
cat /sys/block/bcache0/bcache/state                  # clean or dirty, never inconsistent
systemctl status homelab-backup.service | head -5    # last backup result
tailscale status
sensors | grep Tctl
ls /var/run/reboot-required 2>/dev/null              # present = reboot pending
```

Web checks: each hostname in the [proxy host table](networking.md#reverse-proxy-hosts) should load over HTTPS with a valid certificate.

## Start, stop, restart

```bash
cd <stack directory>
docker compose ps
docker compose up -d          # create or update to match the file
docker compose restart <svc>
docker compose logs -f --tail 100 <svc>
docker compose down           # stop and remove containers; volumes and bind mounts are kept
```

Start order after a full stop: `homelab-core` first, because it creates the external `proxy` network that every other stack requires. The others can follow in any order.

Exceptions:

- **`homelab-core`:** do not run a bare `docker compose up -d` until the `twingate` service is removed from the file. Target services by name: `docker compose up -d npm portainer watchtower`. See [finding 5](findings.md#5-homelab-core-compose-file-has-drifted-from-what-is-deployed).
- **Nextcloud:** start and stop the application containers from the AIO interface. `docker compose` in `~/nextcloud` only manages the master container. The published port for the interface is currently wrong ([finding 8](findings.md#8-nextcloud-aio-admin-interface-is-not-reachable)); until it is fixed the interface answers only on the container address, `https://172.18.0.7:8080` from the host, for example through an SSH tunnel.
- **IT-Tools and SnapOtter:** not in Compose. Use `docker start|stop|restart it-tools` and `SnapOtter`. SnapOtter has no restart policy and must be started by hand after a reboot.
- **UniFi OS Server:** `sudo systemctl restart uosserver`.

## Reboot

```bash
ls /var/run/reboot-required && cat /var/run/reboot-required.pkgs
cat /sys/block/bcache0/bcache/dirty_data     # let writeback settle if large
sudo reboot
```

After boot, expect about two minutes of delay while `systemd-networkd-wait-online` times out. Then:

```bash
findmnt /mnt/storage                 # the data volume must be mounted
systemctl --failed
docker ps -a --format 'table {{.Names}}\t{{.Status}}'
docker start SnapOtter               # no restart policy
systemctl is-active uosserver tailscaled thermal-watchdog
ethtool -k eno1 | grep rx-udp-gro-forwarding     # on
```

If `/mnt/storage` did not mount, stop the stacks that bind-mount it before they write into empty directories on the root disk, fix the mount, then start them again.

## Updates

### Operating system

```bash
sudo apt update && apt list --upgradable
sudo apt upgrade
```

Unattended-upgrades handles Ubuntu's own pockets. Docker Engine, containerd, and other third-party packages need the manual `apt upgrade`. Upgrading `docker-ce` restarts the daemon and every container.

### Containers

| Stack | Procedure |
|---|---|
| NPM, Portainer, Vaultwarden, CouchDB, LiveSync CLI | Automatic at 04:00 by Watchtower. To force: `docker compose pull && docker compose up -d` |
| Immich | Read the release notes for breaking changes, then `cd ~/immich && docker compose pull && docker compose up -d` |
| Nextcloud | AIO interface, "Update containers". Take a backup first |
| n8n | `cd ~/n8n && docker compose pull && docker compose up -d` |
| IT-Tools, SnapOtter | `docker pull <image>`, then remove and re-create the container with the same `docker run` arguments |
| Quartus | `cd /mnt/storage/quartus && docker compose build --pull && docker compose up -d` |
| UniFi OS Server | Automatic through `uosserver-updater.service` |

Clean up afterwards:

```bash
docker image prune        # dangling images
docker system df          # see what is reclaimable before pruning more
```

## Backups

```bash
systemctl list-timers homelab-backup.timer
journalctl -u homelab-backup.service -n 50
sudo systemctl start homelab-backup.service      # run now

sudo -i
export RESTIC_REPOSITORY=/var/backups/restic-repo RESTIC_PASSWORD_FILE=/root/.restic-password
restic snapshots
restic check
```

Restore steps are in [storage and backups](storage-and-backups.md#restore).

## Certificates

Nginx Proxy Manager renews the wildcard certificate automatically. If renewal fails, check the DuckDNS token in the certificate's settings in the NPM UI and that the host can reach DuckDNS and Let's Encrypt. Current expiry:

```bash
docker exec npm openssl x509 -in /etc/letsencrypt/live/npm-1/cert.pem -noout -enddate
```

## Adding a service

1. Create a directory with a `docker-compose.yml`. Attach the service to the external `proxy` network and publish no ports:

   ```yaml
   services:
     app:
       image: example/app:1.2.3
       container_name: app
       restart: unless-stopped
       networks: [proxy]
       labels:
         - "com.centurylinklabs.watchtower.enable=true"   # only if unattended updates are wanted
   networks:
     proxy:
       external: true
   ```

2. `docker compose up -d`.
3. In NPM add a proxy host `app.example.duckdns.org` pointing at `app:<port>`, select the wildcard certificate, and enable Force SSL.
4. No DNS change is needed if the router has a wildcard override for the domain.
5. Decide where its data lives (`/mnt/storage/<app>` for bulk data) and add it to the backup script.
6. Add it to [services](services.md) and copy the Compose file into [`compose/`](../compose).

## Troubleshooting quick reference

| Symptom | First checks |
|---|---|
| A hostname returns 502 | Is the backend container running (`docker ps -a`)? Is it on the `proxy` network? Does the NPM proxy host use the right name and port? |
| No hostname resolves remotely | `tailscale status` on the client; Split DNS entry for the domain in the Tailscale admin console; router reachable through the subnet route |
| Hostnames resolve but connections stall | Client preferring an IPv6 answer. See [finding 7](findings.md#7-stale-aaaa-record-in-public-dns) |
| `address already in use` when starting a container | Another container holds a static address on `proxy`. `docker network inspect proxy` |
| Containers fail at boot with DNS errors | `systemctl status wait-for-internet`; uplink may have taken longer than 120 s |
| Immich unresponsive under load | `tail /var/log/thermal-watchdog.log`; containers may be paused. `docker unpause immich_server immich_machine_learning` once cool |
| Slow or erroring storage | `dmesg | grep -iE 'bcache|ext4|ata'`, bcache `state`, `sudo smartctl -a /dev/sdb` |
| UniFi devices show offline | `systemctl status uosserver`; port 8080 reachable from the device's network; device inform URL is `http://192.168.1.10:8080/inform` |
| Remote throughput poor | `tailscale netcheck`; `tailscale status` shows whether the path is direct or relayed |
