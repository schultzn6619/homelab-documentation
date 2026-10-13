# Hardening

What protects the host, how each control is configured, and where the limits are. Gaps found during the 2026-10-13 audit are in [findings](findings.md).

## Exposure model

- **No inbound path from the internet.** The ISP uses CGNAT, no ports are forwarded, and no Tailscale Funnel is configured.
- **Remote access is Tailscale only.** Membership of the tailnet is the perimeter. The host is a subnet router, so a tailnet device can reach the whole LAN.
- **Web services are reachable from the LAN and the tailnet** through Nginx Proxy Manager with TLS. Applications handle their own authentication; the proxy adds no access lists.

## SSH

`/etc/ssh/sshd_config` sets:

```
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
KbdInteractiveAuthentication no
AllowUsers admin
X11Forwarding yes
```

- Listens on port 22 on all interfaces; UFW decides who can connect.
- One authorised key for the admin user.
- `sshd_config` starts with `Include /etc/ssh/sshd_config.d/*.conf`. For most options sshd uses the first value it reads, so a drop-in (the installer leaves `50-cloud-init.conf`) wins over the main file. Always confirm the effective values rather than the file contents:

```bash
sudo sshd -T | grep -Ei 'passwordauthentication|permitrootlogin|pubkeyauthentication|allowusers'
```

## Firewall (UFW)

| | |
|---|---|
| State | Enabled at boot, IPv6 enabled |
| Default inbound | DROP |
| Default outbound | ACCEPT |
| Default forward | ACCEPT (required for the Tailscale subnet router and Docker) |

Live rules on 2026-10-13 (`sudo ufw status verbose`), 20 in total:

| To | Action | From | Still meaningful? |
|---|---|---|---|
| 22/tcp | allow | anywhere, IPv4 and IPv6 | Yes. Broader than needed; see [finding 17](findings.md#17-firewall-rules-have-drifted) |
| any port on `tailscale0` | allow | anywhere, IPv4 and IPv6 | Yes. Admits all tailnet traffic |
| 8080/tcp | allow | LAN | Yes. UniFi device inform |
| 3478/udp | allow | LAN | Yes. UniFi STUN |
| 10001/udp | allow | LAN | Yes. UniFi discovery |
| 11443/tcp | allow | `172.16.0.0/12` | Yes. Lets Nginx Proxy Manager reach the UniFi UI from the Docker network |
| 443/tcp | allow | anywhere, IPv4 and IPv6 | No effect. The port is published by Docker |
| 80, 81, 9000, 8091 | allow | LAN | No effect. Published by Docker |
| 8097/tcp | allow | LAN and `172.16.0.0/12` | No effect. Published by Docker |
| 1900/udp | allow | LAN | Nothing listens on it |
| one retired service port (3 rules) | allow | LAN and `172.16.0.0/12` | Nothing listens on it |

The `DOCKER-USER` chain is empty for both IPv4 and IPv6, so nothing restricts Docker-published ports beyond their bind address.

UniFi OS Server also listens on 8444, 8880 to 8882, 6789, 5671, 9543, 28082, 5514/udp, and 10003/udp. None of those is allowed, so they are reachable only over Tailscale. That is fine unless the hotspot portal, mobile speed test, or remote syslog features are wanted on the LAN.

### Docker and the firewall

Docker programs its own NAT and filter rules for published ports. Those rules are evaluated before UFW's, so **a UFW rule cannot restrict a port that Docker publishes**. The bind address in the Compose file is the control:

```yaml
ports:
  - "192.168.1.10:81:81"   # reachable only through the LAN address
  - "8097:80"              # reachable on every interface, IPv4 and IPv6
```

Most published ports on this host use the first form. Three do not; see [finding 6](findings.md#6-three-containers-publish-ports-on-every-interface). The preferred pattern is to publish nothing and let Nginx Proxy Manager reach the container over the `proxy` network.

Docker's IPv6 support is enabled (`ip6tables: true`), so the same reasoning applies to IPv6.

Ports forwarded for UniFi OS Server are ordinary host sockets opened by a user-space process, so UFW does filter those.

## fail2ban

[`jail.local`](../system/fail2ban-jail.local) enables the `sshd` jail:

| Setting | Value |
|---|---|
| `maxretry` | 5 |
| `findtime` | 10 minutes |
| `bantime` | 1 hour |
| Backend | systemd journal |
| Ban action | nftables |

The jail is active with no bans and one failed attempt on record, which is expected for a host with no internet-facing SSH.

## Updates

| Component | Mechanism |
|---|---|
| Ubuntu packages | `unattended-upgrades` daily, from the release, security, and ESM pockets |
| Reboots | Not automatic. `/var/run/reboot-required` must be checked by hand |
| Third-party APT (Docker, MongoDB, UniFi source) | Not covered by unattended-upgrades; manual `apt upgrade` |
| Tailscale | Its own auto-update |
| Containers | See [update policy](services.md#update-policy) |
| Firmware | `fwupd` refreshes metadata; updates are applied manually |

## Accounts and privilege

- One human account, in `sudo` (password required) and `docker`.
- Membership of the `docker` group is equivalent to root, because any member can start a privileged container or mount the host filesystem.
- A separate unprivileged `uosserver` account runs UniFi OS Server in rootless Podman.

## Containers

- **Docker socket mounts:** Portainer (read-write), Watchtower (read-write), Nextcloud AIO master (read-only), and the on-demand AIO watchtower. Each is a path to full control of the host.
- **Shared network:** everything on `proxy` can reach everything else on it, including the Immich database and cache. No inter-container filtering is applied.
- **Privileges:** no container runs with `--privileged` or host networking. No container has a memory or CPU limit, so one runaway workload can starve the rest; the thermal watchdog is the only brake.
- **Secrets:** Immich and Twingate values live in `.env` files inside a home directory with mode 750. See [finding 9](findings.md#9-credentials-written-inline) for the exceptions.
- **Image provenance:** images come from Docker Hub and GHCR by mutable tag. Watchtower pulls new versions of four of them unattended.

## TLS

- One ECDSA wildcard certificate from Let's Encrypt, obtained by DNS-01 so no inbound HTTP is needed.
- Every proxy host forces HTTPS and sends an HSTS header (two-year max-age).
- Traffic between the proxy and backends is plain HTTP on the Docker bridge, except UniFi, which is HTTPS with the controller's self-signed certificate.

## Logging and detection

| Source | Where |
|---|---|
| System and services | journald, plus rsyslog files under `/var/log` |
| Performance history | `sysstat` (`sar`), 10-minute samples |
| Disk health | `smartd` to the journal |
| Thermal events | `/var/log/thermal-watchdog.log` |
| Container logs | `docker logs` (json-file driver with no size limit configured, so logs grow until the container is recreated) |

There is no alerting. Nothing notifies anyone when a unit fails, a disk reports errors, or a backup does not run. See [finding 3](findings.md#3-nothing-alerts-on-failure).
