# Changelog

A dated record of changes made to the server. Each entry corresponds to one commit in this repository: the commit updates the documentation and configuration copies to match what was changed on the host, and the entry says what was done, why, and how it was verified.

Newest first. Finding numbers refer to [`docs/findings.md`](docs/findings.md).

## 2026-11-25

### Updated n8n and Immich to clear critical image vulnerabilities

**Problem.** Arcane's Trivy scan of every image on the host reported critical vulnerabilities in 13 images. The two worst were both pinned well behind upstream:

- `n8nio/n8n:2.36.7`: 40 critical, including 21 sandbox-escape and code-execution CVEs in the bundled `vm2` 3.11.6, plus `shell-quote`, `simple-git`, `handlebars` and the image's OpenSSH packages.
- `immich-server:v3.1.0` (28 critical) and `immich-machine-learning:v3.1.0` (13 critical): Pillow heap overflows in the ML image, `proxy-addr` IP spoofing, `handlebars`, Mesa, Brotli and Perl in the server image. Immich v3.4.0's release notes also list security fixes in Immich itself.

**Changed.**

- n8n: `2.36.7` → `2.49.6` (current stable). No breaking changes are listed inside 2.x. `/mnt/storage/n8n` was archived to `/mnt/storage/backups/` first. Database migrations ran on startup.
- Immich: `IMMICH_VERSION` `v3.1.0` → `v3.4.2`. The `pg_dumpall` taken beforehand is in `/mnt/storage/backups/`. The valkey digest and healthcheck were updated to match upstream's v3.4.2 compose file. The Postgres image is unchanged upstream. The opt-in `MACHINE_LEARNING_MODEL_REVISION=v2` was not enabled.
- Each new image was scanned with Trivy before it was deployed.

**Verified.**

- Trivy, critical only: n8n 2.49.6 has 0 (was 40). immich-server v3.4.2 has 3 (was 28): OpenEXR and libxml2, with no fixed Debian package yet for libxml2. immich-machine-learning v3.4.2 has 2 (was 13): `anyio` and `certifi`.
- n8n `/healthz` returns ok, `n8n --version` reports 2.49.6, and the workflow index loaded its published workflow.
- All four Immich containers are healthy, migrations finished, and `/api/server/version` reports 3.4.2.
- Both services return 200 through NPM.

**Not acted on, reviewed as not reachable.** Vaultwarden's two MariaDB criticals are server-side bugs, but the image only ships the client library and Vaultwarden runs on SQLite. Home Assistant's OpenSSH critical is a server password-auth bug, but the image only has the client. Both images are already on the latest release.

**Still open.**

- The Nextcloud AIO containers have rebuilt images waiting (Brotli and Perl fixes). They update through the AIO interface.
- Home Assistant's bundled `Authlib` has a critical CVE, and no Home Assistant release fixes it yet.
- The residual Immich criticals listed above wait on upstream.

### Router: switched upstream DNS to DNS-over-HTTPS

**Problem.** dnsmasq on the router sent every LAN lookup it couldn't answer from cache to 1.1.1.1 and 8.8.8.8 in plain text over port 53. The ISP and anything else on the path could read or alter them.

**Changed.** On the router, through GL's own DNS API (`gl-session` module `dns`, `set_config`), so the GL interface shows the same setting:

- Mode `secure`, protocol DoH, provider Cloudflare, server "Standard" (unfiltered): `https://cloudflare-dns.com/dns-query`.
- GL starts `dnsproxy` on port 5453. dnsmasq now has `no-resolv` and `server=127.0.0.1#5453`, so it keeps answering clients, caching and applying the local overrides, but forwards upstream only through `dnsproxy`.
- `dnsproxy` uses plain DNS to 8.8.8.8 and 1.1.1.1 only to look up the address of `cloudflare-dns.com` itself.
- Rebind protection stays on.
- The previous `gl-dns-v2`, `dhcp` and `network` configs were copied to `/root/bak-2026-11-25/` on the router.

**Verified.**

- Public names resolve from the router and from the host, and nonexistent names return no answer.
- The service domain and its subdomains still resolve to the host's LAN address.
- The rebind test name still gets no answer.
- Connection tracking on the router shows its upstream DNS traffic on port 443 only, with no plain port 53 queries leaving the router or the LAN.
- Uncached lookups take 26 to 37 ms and cached ones 0 to 1 ms.

**Still open.** Clients that hard-code their own resolver (for example 8.8.8.8) still send plain DNS directly. GL's "force DNS" option would redirect them, and is left off.

### Router: redirected the admin interfaces to HTTPS

**Problem.** Both of the router's admin interfaces answered on plain HTTP on the LAN: the GL interface (nginx, port 80) and LuCI (uhttpd, port 8080). Logging in over those ports sent the admin password and session in the clear.

**Changed.** On the router, both interfaces now use their built-in redirect option:

- GL interface: `oui-httpd.main.redirect_https=1`, and nginx restarted.
- LuCI: `uhttpd.main.redirect_https=1`, and uhttpd restarted.

Both still use the router's self-signed certificate.

**Verified.**

- `http://<router>/` returns 302 to `https://<router>/`.
- `http://<router>:8080/cgi-bin/luci` returns 307 to port 8443.
- The GL interface loads over HTTPS, and its `/rpc` API answers.
- LuCI's login page loads over HTTPS.

### Router: turned on DNS rebind protection

**Problem.** dnsmasq on the router had `rebind_protection='0'`. It passed on upstream answers that put a public name on a private or loopback address. A malicious web page can use that kind of answer (a DNS rebinding attack) to reach devices on the LAN from a browser.

**Changed.** On the router, `dhcp.@dnsmasq[0].rebind_protection=1`, and dnsmasq restarted. dnsmasq's generated config now has `stop-dns-rebind`. `rebind-localhost-ok` was already set. No `rebind_domain` exceptions were needed, because the router answers the service domain itself with an `address=` override, and rebind protection doesn't apply to its own answers.

**Verified.** A test name that resolves publicly to a private address (`192.168.1.1.nip.io`) now gets no answer. dnsmasq logs that rebind protection is active. The service domain and its subdomains still resolve to the host's LAN address from the router and from the host. `console.gl-inet.com` still points to the router, and public names resolve normally.

### Router: disabled unused GL services

**Problem.** The router was running GL services for hardware it doesn't have or features that are off: cellular modem and SMS managers (the Flint 2 has no modem), deep packet inspection, and `udpspeeder`, which listened on UDP 4095 and 4096 on every interface for a multipath tunnel that is turned off (`mptun.enable=0`).

**Changed.** On the router, each of these was stopped and disabled at boot with `/etc/init.d/<name> stop` and `disable`: `gl_cellular_manager`, `sms_manager`, `smstools3`, `modem_signal`, `udpspeeder`, `gl_dpi` and `gl_dpi_flow_statistics`.

Left alone on purpose:

- `carrier-monitor` watches the Ethernet link state, so it isn't cellular-related.
- The `mptun`, `mpifd` and `mpflow` services aren't running anyway.
- A firmware-owned cron job runs an ARP scan once a minute.

**Verified.** None of the disabled processes are running, and UDP 4095 and 4096 are closed. The router still resolves names and reaches the internet, the host reaches the internet, and the admin interface loads.

**Trade-off.** With DPI off, the GL interface no longer shows per-app traffic statistics for clients, and parental controls (already off) would not work. Turn it back on with `/etc/init.d/gl_dpi enable && /etc/init.d/gl_dpi start`, and the same for `gl_dpi_flow_statistics`.

### Router: turned off its Wi-Fi radios and repeater mode

**Problem.** Wi-Fi in the house comes from the UniFi access points. Every SSID on the router was already disabled, but both radios were still enabled, and repeater auto-connect (`repeater.auto=1`) kept the client interfaces `apcli0` and `apclix0` around for scanning.

**Changed.** On the router: `wireless.mt798611.disabled=1` (2.4 GHz) and `wireless.mt798612.disabled=1` (5 GHz), then `wifi reload`. `repeater.@main[0].auto=0`. The `gl-repeater` daemon is left installed and running, idle, so the GL admin interface keeps working.

**Verified.** None of the radio interfaces (`ra*`, `rax*`, `apcli*`) are up, and none have passed any traffic. Wired networking and internet access from the host still work.

### Router: shaped uploads with SQM to fix bufferbloat

**Problem.** Uploads made the whole connection lag. With 4 upload streams running, ping from the host to 1.1.1.1 had a median of 584 ms and a p90 of 759 ms, against 27 ms idle. The uplink measured about 7 Mb/s.

**Changed.** On the router, SQM (CAKE, `piece_of_cake.qos`) is turned on for the WAN interface `eth1`, shaping upload only: `upload=6000` kbit/s, `download=0`. The `sqm` section had pointed at `br-lan` with placeholder rates of 10 Gb/s. Downloads are not shaped, and hardware NAT is left on.

**Verified.** The same upload test now gives a median of 41 ms and a p90 of 90 ms, with about 5.1 Mb/s of upload throughput. `tc -s qdisc` shows CAKE on `eth1` handling the traffic and dropping packets. Downloads are unaffected: about 305 Mb/s, against 322 Mb/s before, which is within run-to-run noise.

**Still open.** The 6 Mb/s cap is fixed while 5G uplink capacity varies. On a weaker-signal day latency can creep back, and on a better day some upload speed goes unused. Download latency under load is still about +100 ms. Shaping downloads too would mean a fixed cap of a few hundred Mb/s that the router's CPU would have to handle.

### Router: stopped DNS query logging and removed a stale IPv6 port rule

**Problem.** A read-only review of the GL.iNet Flint 2 found two things worth fixing:

- dnsmasq had `logqueries` on. Query lines made up 3,973 of the 4,163 lines in the router's 512 KB log ring, so the log only reached back about 15 minutes. A WAN reconnect two hours earlier had already been pushed out, so dropouts could not be diagnosed. It also recorded every DNS lookup on the LAN.
- A custom firewall rule, `Allow-Nath-Serv-HTTPS-v6`, let the internet reach port 443 on the host's global IPv6 address. The ISP has since handed out a new prefix, so the rule matched nothing. It was dead, but if someone updated the address it would expose the reverse proxy over IPv6, which the public DNS no longer advertises (finding 7).

**Changed.** On the router, with a `sysupgrade -b` config backup taken first and kept on the host:

- `dhcp.@dnsmasq[0].logqueries` set to `0`, and dnsmasq restarted.
- The `Allow-Nath-Serv-HTTPS-v6` rule deleted, and the firewall reloaded.

**Verified.** dnsmasq's generated config no longer has `log-queries`, and the log now shows only service messages. `ip6tables` has no rule for port 443. The router still answers the local override for the service domain with the host's LAN address, and the host resolves names and reaches the internet. The review also confirmed the router has a static DHCP lease for the host (finding 16).

**Still open.**

- The router's link to the switch runs at 1 Gb/s on a router port that supports 2.5 Gb/s, because the switch end is a 1.25 Gb/s SFP module. It is not a bottleneck: internet throughput is about 320 Mb/s, and LAN-to-LAN traffic stays inside the switch.
- Bufferbloat: latency from the host rose from about 27 ms idle to about 120 ms under a download and about 580 ms under an upload (upload measured at about 7 Mb/s). SQM is configured on the router but off. Turning it on is a trade-off against hardware NAT and throughput, so it has not been changed.

### Added n8n to the nightly backup (finding 2, partly)

**Problem.** n8n was the last service whose state was not backed up. That includes the "Rocketbook → Obsidian" workflow, two saved credentials, and the key that encrypts them.

**Changed.** [`homelab-backup.sh`](scripts/homelab-backup.sh) has a new `n8n` step:

- `/mnt/storage/n8n` is copied with `rsync`, without event logs or `crash.journal`.
- `database.sqlite` is copied with SQLite's online backup API.
- `config` is included, because the saved credentials cannot be decrypted without the key in it.

The Rocketbook inbox that n8n writes to is in the Obsidian vault, which was already backed up. The previous script is kept on the server as `homelab-backup.sh.bak-2026-11-25-n8n`.

**Verified.** A manual run reported every step ok. The snapshot contains `n8n/config` and `n8n/database.sqlite`. The database, restored to a scratch directory, passed `PRAGMA integrity_check` and lists both workflows ("Rocketbook → Obsidian" active, the test copy inactive) and 2 credentials.

### Added NPM and Arcane to the nightly backup (finding 2, partly)

**Problem.** The NPM volumes hold every proxy host, the access lists, the wildcard certificate and the DuckDNS settings. Arcane's volume holds its users and settings. None of them were backed up, so losing the NVMe meant rebuilding all 13 proxy hosts by hand.

**Changed.** [`homelab-backup.sh`](scripts/homelab-backup.sh) has two new steps:

- `nginx proxy manager`: copies `npm_data` without logs, and `npm_letsencrypt`, with `rsync`. `database.sqlite` is copied with SQLite's online backup API.
- `arcane`: copies `arcane_data` without the databases and the stale `initial-admin-password`. `arcane.db` and `arcane.francis.db` get SQLite backup copies. It also copies `arcane.env`, whose encryption key is needed to read Arcane's stored secrets after a restore.

The staging directory is root-only and the restic repository is encrypted. The previous script is kept on the server as `homelab-backup.sh.bak-2026-11-25-core`.

**Verified.**

- A manual run reported every step ok.
- The snapshot contains NPM's `database.sqlite`, `keys.json` and `live/npm-1/fullchain.pem`, and Arcane's two databases and `arcane.env`.
- NPM's and Arcane's main databases were restored from the snapshot to a scratch directory. Both passed `PRAGMA integrity_check`, and the restored NPM database lists 13 proxy hosts.

**Still open.** Every copy is still on the same machine (finding 2).

### Replaced Portainer with Arcane

**Problem.** Portainer was to be replaced by [Arcane](https://getarcane.app/), which manages Compose projects as plain folders on disk rather than as stacks in its own database.

**Changed.**

- Portainer managed no stacks of its own, since every project was deployed with `docker compose` from a folder, so nothing needed exporting.
- Added `arcane` (`getarcaneapp/manager:v3.1.1`) to [`homelab-core`](compose/homelab-core/docker-compose.yml), on `proxy` with no published port. It can see `~/homelab` and the two project folders under `/mnt/storage` at their real paths.
- The encryption key is in `arcane.env` (mode 600, not published; see [`arcane.env.example`](compose/homelab-core/arcane.env.example)). The proxy host is `arcane.` → `arcane:3552`, with websockets on.
- Arcane sent one anonymous usage heartbeat on its first start, before it was turned off. `ANALYTICS_ENABLED=false` is now set, and its heartbeat host resolves to `0.0.0.0` inside the container.
- Removed the `portainer` service, its image, the `ptnr.` proxy host, and the UFW rule allowing 9000 from the LAN. The volume `homelab-core_portainer_data` is kept for now in case of a rollback.
- [`image-update-check.py`](scripts/image-update-check.py): release-note links for Arcane and Home Assistant, Portainer's removed. Its tag pattern already accepts `v3.1.1` and ignores `-next.N` pre-releases. The previous script is kept on the server as `image-update-check.py.bak-2026-11-25`.
- Docs: services, networking, hardening, architecture, operations, storage and backups, findings and README.

**Verified.**

- Arcane's log lists all nine projects: `homeassistant`, `homelab-core`, `immich`, `music`, `n8n`, `nextcloud`, `utilities`, `obsidian-livesync` and `vaultwarden`.
- `https://arcane.example.duckdns.org` returns 200. The admin account no longer has `requires_password_change` set, so the generated first password has been replaced.
- NPM stayed up throughout. Nothing listens on 9000, and UFW has no rule for it.

**Still open.** Delete the `homelab-core_portainer_data` volume once Arcane has been in use for a while (`docker volume rm homelab-core_portainer_data`).

### Cleared the stale AAAA record (finding 7)

**Problem.** Every hostname under the DuckDNS domain also resolved to a global IPv6 address, `2607:fb91:4c8e:8054:…`, in a prefix the host no longer has. The host's current global prefix is different, and the ISP rotates it. Nothing is reachable from the internet in any case. Clients that prefer IPv6 try the dead address first, which can stall connections. This showed up again when checking the new `ha.` host.

**Changed.** Both records were cleared through DuckDNS's update API (`clear=true`), and the A record was set back to the host's LAN address straight away. DuckDNS cannot clear only the AAAA record. The token was read from NPM's certificate settings into a root-only temporary file and deleted afterwards. It was never printed.

**Verified.**

- 1.1.1.1, 8.8.8.8 and DuckDNS's name servers `ns6` and `ns7` return only the A record for the domain and for `ha.`.
- The router's dnsmasq does the same, and `https://ha.example.duckdns.org` still returns 200.
- No cron job, systemd unit, script or container on the host updates DuckDNS.

**Still open.** If the AAAA record comes back, the router's DDNS client is sending it. Turn off IPv6 there or remove the DDNS entry.

### Added Home Assistant

**Problem.** Home Assistant was wanted on the server. Only network devices are planned (Wi-Fi, Ethernet and cloud integrations), with no Zigbee, Z-Wave or Thread radio.

**Changed.**

- New Compose project [`homeassistant`](compose/homeassistant/docker-compose.yml) in `~/homelab/homeassistant`: `homeassistant/home-assistant:2026.11.3` (Container install), `network_mode: host` so mDNS and SSDP discovery reach LAN devices. Data is in `/mnt/storage/homeassistant/config`.
- UFW: `8123/tcp` allowed from `172.16.0.0/12` only, the same pattern as UniFi's 11443, so NPM can reach it but the LAN cannot reach it directly.
- Home Assistant trusts `X-Forwarded-For` from NPM's static address `172.18.255.10` only. In this release, HTTP settings live in `.storage/http`. YAML is imported once, on first start, and an imported change is a five-minute trial that an admin must confirm. The first start ran before the proxy settings were in the YAML. Nobody had created an account yet, so the stored settings were reset to import them, then written as the confirmed (`stable`) settings, and the YAML block was removed again. Details in [services](docs/services.md#home-assistant).
- [`homelab-backup.sh`](scripts/homelab-backup.sh): a new `home assistant` step copies the config without logs and takes a consistent SQLite copy of the recorder database. The previous script is kept on the server as `homelab-backup.sh.bak-2026-11-25`.
- Docs: services, networking, hardening, storage and backups, architecture and README. The README's stale NPM and SnapOtter versions and its container count were corrected too.

**Verified.**

- The container runs. A request from inside the NPM container to the host address on 8123 with `X-Forwarded-For` set returns 302 (to onboarding). Before the fix it returned 400 ("not set-up for reverse proxies"). `.storage/http` has no pending trial, so nothing will revert.
- A manual backup run reported every step ok, including `home assistant`. The new snapshot contains `configuration.yaml`, `.storage/http` and `home-assistant_v2.db`.
- During setup, unattended-upgrades updated Docker from 29.9.2 to 29.9.3 at 16:37 and restarted the daemon. Live-restore kept every other container running. Home Assistant was being restarted at that moment and was left stopped, so it was started again.

**Follow-up the same day.** The `ha.` proxy host was added in NPM (forward to `192.168.1.10:8123`, http, websockets on, wildcard certificate, Force SSL, HSTS) and the owner account was created. `https://ha.example.duckdns.org` returns 200 with a valid certificate, plain HTTP redirects with 301, the HSTS header is present, `/api/websocket` upgrades with 101 over HTTP/1.1, and onboarding reports every step done.

### Updated NPM, Portainer and SnapOtter

**Problem.** The weekly [image update check](docs/services.md#image-update-check) reported new releases for five pinned images. SnapOtter 2.3.0 closes six security advisories that affect 2.2.0, one of them rated high. n8n (a major version, 2.36.7 to 3.4.0) and LiveSync CLI (kept on 1.0.43 on purpose) were left for later.

**Changed.**

- [`homelab-core`](compose/homelab-core/docker-compose.yml): `jc21/nginx-proxy-manager` 2.16.0 → 2.17.1, `portainer/portainer-ce` 2.45.3 → 2.45.4.
- [`utilities`](compose/utilities/docker-compose.yml): `snapotter/snapotter` 2.2.0 → 2.3.0.
- Read the release notes first. NPM 2.17 updates Certbot to 5.10, and the notes warn that DNS plugins may break. The certificate uses the DuckDNS DNS challenge. Portainer's breaking changes only affect Kubernetes shells and non-admin users. NPM was recreated on its own, as [operations](docs/operations.md#containers) requires. The previous Compose files are kept on the server with the suffix `.bak-2026-11-25`.

**Verified.**

- All three containers run the new tags. SnapOtter is healthy. NPM kept its static address `172.18.255.10`.
- Every proxy host answers through NPM with its usual status (200, 302 for sign-in redirects, 401 for CouchDB).
- `certbot plugins` in the new NPM image still lists `dns-duckdns`. NPM writes the DuckDNS credentials file just before each renewal and deletes it afterwards, so a manual `certbot renew --dry-run` fails with "credentials file not found" and does not tell you whether renewal works. The certificate is valid until 2027-01-09, so the first real renewal under 2.17.1 will happen in about two weeks.
- A health check run reports all checks passed.

**Still open.** n8n 3.x (a major version: read the migration notes before updating). LiveSync CLI stays pinned. The Immich images could not be checked this run because GHCR returned HTTP 429.

## 2026-11-04

### Hardened Docker networking against power cuts

**Problem.** The 14:01 reboot was caused by a power bump. Reviewing how Docker comes back after one turned up three more ways the proxy, or everything, could stay down:

- `docker.service` had `Requires=wait-for-internet.service`, and that unit gives up after 120 s if `pubnub.com` (a Twingate domain) does not resolve. After a power cut the modem is often slower than that, and Docker would then not start at all.
- NPM, Portainer and other containers publish ports on the LAN address. If DHCP is late, those containers fail with "cannot assign requested address" and do not retry.
- Docker's built-in address pools include `192.168.0.0/20`, which contains the LAN. A new Compose network taken from that pool would cut the host off the LAN.

The dead `twingate` service also still had a static address that `n8n` now holds (finding 5).

**Changed.**

- [`docker-override.conf`](system/docker-override.conf): Docker now only `Wants=` the network and [`wait-for-internet.service`](system/wait-for-internet.service), so it still waits up to 120 s but starts anyway. The wait now looks up `registry-1.docker.io` instead of the Twingate domain.
- [`60-nonlocal-bind.conf`](system/60-nonlocal-bind.conf): `net.ipv4.ip_nonlocal_bind` and `net.ipv6.ip_nonlocal_bind` are set to 1, so ports can be bound to the LAN address before DHCP assigns it.
- [`daemon.json`](system/docker-daemon.json): `default-address-pools` is `10.88.0.0/16` in `/24` blocks. No route on the host or the tailnet uses `10.x`. Existing networks keep their subnets. `live-restore` is on, so a Docker restart, such as an unattended upgrade, no longer restarts every container.
- Removed the `twingate` service from [`homelab-core`](compose/homelab-core/docker-compose.yml), deleted the unused `twingate/connector` image and corrected the "Twingate-only" comment (finding 5, partly).
- Docker was restarted once to load the daemon settings. The health check timer was paused during the change. The previous versions of the changed files are kept on the server with the suffix `.bak-2026-11-04`.

**Verified.**

- `dockerd --validate` accepted the new `daemon.json`. After the restart `docker info` reports live-restore enabled, and the same 21 containers are running, none unhealthy.
- A throwaway network got `10.88.0.0/24` and was then removed.
- `systemctl show docker` lists `wait-for-internet.service` under `Wants` and not under `Requires`. Both sysctls read 1.
- NPM is still on `172.18.255.10`. Every proxy host answers with its usual status, and a health check dry run reports no problems.

**Not changed.** The `proxy` network was left without an `ip_range`. Docker cannot change a network's address settings in place, so adding one means removing and recreating the network, with every stack on it down, Nextcloud AIO's included. With NPM's address at the top of the subnet, it would add little.

**Still open.** Revoke the Twingate connector tokens in the Twingate admin console, then delete `~/homelab/homelab-core/.env` (finding 5). A UPS would remove the power-cut trigger itself.

### Moved NPM's static address out of the automatic range

**Problem.** The server rebooted at 14:01. While Docker brought containers back, `navidrome` was given `172.18.0.10` on `proxy`. That is NPM's static address, so NPM failed to start ("failed to set up container networking: Address already in use") and stayed down. Every proxied service was unreachable and the health check's TLS alert fired ("Connection refused"). This had already happened once during a recreate (2026-11-03, below). The reboot showed that start order at boot can cause it too, so any reboot could take the proxy down.

**Changed.**

- Recovery first. Stopped `navidrome`, started `npm` and started `navidrome` again. It moved to `.17`.
- NPM's address in [`homelab-core`](compose/homelab-core/docker-compose.yml) is now `172.18.255.10`. Docker gives each container the lowest free address on the network, so the top of the `/16` will not be taken. Nothing else referred to the old address. Only `npm` was recreated (`docker compose up -d --no-deps npm`), with the health check timer paused for the change.
- Updated [operations](docs/operations.md), [networking](docs/networking.md), [services](docs/services.md) and [architecture](docs/architecture.md).

**Verified.**

- `npm` is on `172.18.255.10` and running.
- Every proxy host answers through NPM with its usual status: 200 for most, a login redirect from `cloud.` and `music.`, and 401 from CouchDB. The admin UI on port 81 answers.
- The certificate is still valid until 2027-01-09. A dry run of the health check shows the TLS alert as cleared, and the timer is active again.

**Still open.**

- The `twingate` service still has a static address of `172.18.0.3` in the same file and would hit the same collision if it were ever started (finding 5). (Removed later the same day, entry above.)
- The journal of the previous boot ends at 02:30. The 14:01 boot followed about 11.5 hours with no log entries, so it does not look like a clean restart, and the boot before it also ended in a crash. (The 14:01 boot followed a power bump; see the entry above.)

## 2026-11-03

### Stopped head parking on the data disk (finding 18)

**Problem.** The 4 TB data disk's firmware parked its heads after a few seconds idle, about 24 times an hour. Its load cycle count had reached 499,212, well past the roughly 300,000 this class of drive is rated for. No SMART self-test had ever been run on it.

**Changed.**

- Added [`datadisk-apm.service`](system/datadisk-apm.service), which runs `hdparm -B 254` on the disk by its `by-id` path at boot. Ubuntu's hdparm udev hook, which would apply `/etc/hdparm.conf`, skips this disk because udev does not report `ID_ATA_FEATURE_SET_APM` for it, so a `/etc/hdparm.conf` entry would not apply.
- Set [`smartd.conf`](system/smartd.conf) to run a short self-test daily at 02:00 and a long one weekly on Saturday at 03:00, with `smartd-runner` so failures reach Discord.

**Verified.**

- After a reboot at 17:29 the service had run and `hdparm -B` reported `APM_level = 254`.
- The load cycle count was 499,212 at 17:37 and still 499,212 at 18:07. At the old rate it would have risen by about 12.
- A short self-test run by hand passed with no errors.

**Still open.** The disk is still the only copy of the application data, and the photo library is not in any backup (finding 2). Plan a replacement or a mirror disk (step 4).

### Health check alerts on stopped containers (finding 3)

**Problem.** The [health check](scripts/homelab-health-check.py) caught containers that were restart-looping or unhealthy, but not one that had simply stopped and stayed down. That gap mattered more once unattended-upgrades could restart Docker on its own (entry below).

**Changed.** A container whose restart policy is `always` or `unless-stopped` and that has been stopped for `STOPPED_GRACE_MIN` (default 15) minutes or more is now reported, with its status, exit code and last log lines. The grace period keeps short maintenance from paging. Containers with no restart policy are skipped, which leaves out one-off and development containers such as `corvid-postgres-1` and the AIO-managed `nextcloud-aio-watchtower`. `IGNORE_CONTAINERS` still applies.

**Verified.**

- A throwaway container with `--restart unless-stopped`, stopped with `docker stop`, was reported with `STOPPED_GRACE_MIN=0` ("stopped for 0 min (status exited, exit code 137)"), was not reported at the default 15 minutes, and was not reported when listed in `IGNORE_CONTAINERS`. It was then removed.
- Deployed to `/usr/local/bin`. A run of `homelab-health-check.service` succeeded with "All checks passed".
- End-to-end test on Discord: a stopped throwaway container `alert-test`, checked once with `STOPPED_GRACE_MIN=0`, produced a pinged alert with its last log line. Removing it and running the service produced the "Resolved" message. Both arrived.

### Unattended-upgrades for Docker and Tailscale (finding 4)

**Problem.** unattended-upgrades only took packages from Ubuntu's own pockets. Docker Engine, containerd and the Tailscale client waited for a manual `apt upgrade`, which is how they had fallen behind in finding 4.

**Changed.** Added [`/etc/apt/apt.conf.d/52unattended-upgrades-thirdparty`](system/52unattended-upgrades-thirdparty) with two `Origins-Pattern` entries. The two repositories describe themselves differently: Docker's sets an archive (`a=resolute`) but no codename, and Tailscale's sets a codename (`n=resolute`) but no archive. So Docker is matched on `origin=Docker,archive=${distro_codename},label=Docker CE` and Tailscale on `origin=Tailscale,codename=${distro_codename}`. A first attempt that matched Docker on codename was silently ignored.

**Verified.** `unattended-upgrade --dry-run --debug` lists both patterns among the allowed origins and no longer marks either repository "not allowed". Neither has an update waiting, so the first real upgrade will show in the unattended-upgrades log.

**Side effect.** A `docker-ce` or `containerd.io` upgrade restarts the daemon and every container, around 06:00 when `apt-daily-upgrade.timer` fires. The health check alerts on a container that comes back unhealthy or restart-looping, and (since the entry above) on one that stays stopped.

### Rebooted onto the current kernel (finding 4)

**Problem.** The host was running an older kernel than the one installed, and `/var/run/reboot-required` was set. Several packages, including `docker-ce`, `containerd.io`, `openssh-server` and `tailscale`, were waiting for an upgrade.

**Changed.** unattended-upgrades installed kernel 7.0.0-42, and the host was rebooted onto it on 2026-11-03 (at 12:05, 12:10 and 17:29, the last to test the data-disk service for finding 18).

**Verified.**

- `uname -r` reports `7.0.0-42-generic`, the newest kernel in `/boot`, and `/var/run/reboot-required` is gone.
- `docker-ce`, `containerd.io`, `openssh-server` and `tailscale` are no longer upgradable. Five packages remain: three security updates that unattended-upgrades will install, and two `software-properties` updates.
- After the 17:29 reboot, every container came back up, every container with a health check reports healthy, and no systemd unit failed.

**Still open.** The Docker and Tailscale repositories were not yet covered by unattended-upgrades. Done in the entry above.

### Fixed the AIO interface port and pinned n8n and Immich (findings 8 and 14)

**Problem.**

- The Nextcloud AIO master published `8091` to container port `8092`, where nothing listens, so the AIO interface could not be reached. Maintenance needed workarounds, such as the `daily-backup.sh` call used for findings 6 and 16.
- n8n tracked `latest` and Immich tracked `release`. They were the last service images without a version pin, and the update check could not see them.

**Changed.**

- Changed the mapping to `192.168.1.10:8091:8080` in `~/homelab/nextcloud/docker-compose.yml` ([copy](compose/nextcloud/docker-compose.yml)) and recreated the master container. The Nextcloud containers kept running.
- Pinned n8n to `n8nio/n8n:2.36.7` ([Compose file](compose/n8n/docker-compose.yml)), and Immich to `IMMICH_VERSION=v3.1.0` in `~/homelab/immich/.env` ([example](compose/immich/.env.example)). Before switching, checked that each tag's registry digest matched the running image, so no version changed. Recreated both and removed the old `latest` and `release` tags.
- Added release-notes links for Immich, n8n and SnapOtter to the [update check](scripts/image-update-check.py).

**Verified.**

- `https://192.168.1.10:8091` redirects to the AIO login page.
- n8n and Immich are healthy on their pinned tags. `immich.` reports 3.1.0, and n8n's "Rocketbook → Obsidian" workflow is still active.
- A dry run of the update check now also covers n8n and Immich. It reports Immich v3.3.5, n8n 3.1.0 (a major version) and SnapOtter 2.3.0 as available.

### Locked down Vaultwarden (findings 9 and 10)

**Problem.** Vaultwarden's data directory, which holds the database and the RSA signing key, was readable by every local account (mode 755, files 644). The server also still allowed anyone who could reach it to create an account.

**Changed.**

- `chmod 700 /mnt/storage/vaultwarden/data`. The container runs as root, and so does the backup that copies the directory, so neither is affected.
- Checked the database read-only first: it holds one account, the admin's, and no pending invitations. Then set `SIGNUPS_ALLOWED=false` in the [Compose file](compose/vaultwarden/docker-compose.yml) and recreated the container.

**Verified.**

- The admin user can no longer list the directory.
- Vaultwarden is healthy and runs with `SIGNUPS_ALLOWED=false`.
- A registration attempt through NPM (`POST /identity/accounts/register/send-verification-email`) is refused with HTTP 400, "Registration not allowed or user already exists". Invitations stay enabled for adding users later.

### Host hygiene (finding 16)

**Changed.**

- **Unneeded services.** Disabled and stopped `ModemManager`, `multipathd` (with its socket), `open-iscsi` and `iscsid.socket`. The host has no modem, no multipath devices (`multipath -ll` lists nothing) and no iSCSI targets.
- **SSH.** Added [`20-no-x11.conf`](system/sshd_config.d/20-no-x11.conf) (`X11Forwarding no`) and reloaded sshd after `sshd -t`. Removed the old `authorized_keys` entry from the host's first setup. Its private key is not on the host, and the journal shows no login with it since at least 2026-10-01. The laptop and phone keys, which are the ones in use, remain.
- **Container logs.** Added `log-driver: json-file` with `max-size: 10m` and `max-file: 3` to [`daemon.json`](system/docker-daemon.json) and restarted Docker. Logs totalled 20 MB, the largest being `immich_server` at 11 MB.
- **Time zones.** Set `TZ=America/New_York` on every container in the [Compose files](compose/). That covers NPM, Portainer, Vaultwarden, CouchDB, LiveSync CLI, Navidrome, slskd, IT-Tools, SnapOtter, n8n, the Immich server, ML, Redis and Postgres, and the Nextcloud master. Immich's `.env` changed from America/Detroit, which keeps the same clock. Navidrome's Alpine image has no tzdata, so the host's `/usr/share/zoneinfo` is mounted read-only into it. The Nextcloud AIO child containers already used America/New_York.
- **Recreating the containers.** Log options and environment only apply to new containers, so every stack was recreated one at a time. The AIO children were recreated with AIO's own script, as in finding 6. NPM was recreated last and on its own, so it kept `172.18.0.10`. No images were pulled. The health check timer was paused during the work.
- **Fans.** The primary sensor chip is not detected, even with `ignore_resource_conflict=1 force_id=0x8686`, so fan speeds cannot be read. The [health check](scripts/homelab-health-check.py) now alerts when the CPU (`k10temp` Tctl) reaches 85 °C, the thermal watchdog's critical level.

**Verified.**

- Every running container has `max-size: 10m` and `max-file: 3`, and every container that has a `date` command reports EST.
- Every proxy host answers through NPM as before. n8n's "Rocketbook → Obsidian" workflow is still active, and a LiveSync round trip succeeded.
- The temperature check fires when its threshold is forced to 30 °C.

**Still open.** These need hands-on work or a decision: matched memory, a UPS, a firmware update (UEFI F50 is from 2019), a static DHCP lease for the host, and backing up NPM's proxy definitions (finding 2). Blanket resource limits were not added; Immich ML is handled under finding 15. The AIO master container reports UTC because its image has no tzdata, which does not matter here because its backup schedule is set in the AIO interface.

### Stopped publishing Nextcloud's Apache port (finding 6)

**Problem.** `nextcloud-aio-apache` published port 11000 on every interface, IPv4 and IPv6. That bypassed UFW and let anyone reach Nextcloud without going through the proxy or TLS. NPM already reached it by name on `proxy`, so the published port was not needed.

**Changed.**

- Added `APACHE_IP_BINDING: "@INTERNAL"` to the master container in `~/homelab/nextcloud/docker-compose.yml` ([copy](compose/nextcloud/docker-compose.yml)). With this value, the installed AIO version skips publishing Apache's port.
- Recreated the master container with `docker compose up -d`.
- The AIO interface is not reachable (finding 8), so the AIO containers were stopped and started with AIO's own script instead: `docker exec -e DAILY_BACKUP=0 -e STOP_CONTAINERS=1 -e START_CONTAINERS=1 -e AUTOMATIC_UPDATES=0 nextcloud-aio-mastercontainer /daily-backup.sh`. Starting deletes and recreates each container without pulling new images, so no versions changed. Nextcloud was down for a few minutes.

**Verified.**

- Every `nextcloud-aio-*` container is healthy, and nothing listens on 11000 on the host.
- `cloud.` returns 200 through NPM, and `status.php` reports 34.0.4 installed, with no maintenance mode and no database upgrade needed.
- The only Docker port still published on every interface is slskd's 50300, which is meant to be reachable by Soulseek peers.

**Still open.** Not yet checked from an outside network: whether the host's global IPv6 address answers on 50300.

### Moved IT-Tools and SnapOtter into Compose (findings 13 and 6)

**Problem.** IT-Tools and SnapOtter had been started with `docker run`, so their configuration existed only in the containers. Both published ports on every interface, IPv4 and IPv6 (8097 and 1349). SnapOtter had restart policy `no` and had been down since the reboot on 2026-10-13.

**Changed.**

- Checked that neither container had settings beyond its image defaults: environment, command and entrypoint all matched the image.
- Created the Compose project `utilities` in `~/homelab/utilities` ([Compose file](compose/utilities/docker-compose.yml)). Both services are on `proxy` with no published ports and `restart: unless-stopped`. They are pinned to the versions they were running: `corentinth/it-tools:2024.10.22-7ca5933` (the same image as `latest`) and `snapotter/snapotter:2.2.0`. SnapOtter reuses its existing volume `SnapOtter-data` as an external volume and has the network alias `snapotter`.
- Replaced the two containers. IT-Tools was down for about two minutes, because the old container was removed before the new project directory had been created.
- Pointed the NPM proxy hosts `it.` and `tools.` at `it-tools:80` and `snapotter:1349`. The change was made in NPM's database and in the generated nginx config together, and checked with `nginx -t` before reloading. The previous database and config files were backed up first.
- Deleted the two UFW rules for 8097/tcp, which had no effect, and removed the now-unused `latest` tags.

**Verified.** `it.` and `tools.` both return 200 through NPM. SnapOtter's health check reports healthy, and its data volume was reused. Nothing listens on 8097 or 1349 on the host any more. UFW now has 14 rules.

**Still open.** The update check posts SnapOtter releases (2.3.0 is already out), but it cannot read IT-Tools's date-style tag.

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

**Still open.** NPM's fixed address can still be taken whenever several containers on `proxy` are recreated at the same time. (Fixed 2026-11-04, entry above.)

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
