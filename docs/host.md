# Host

Hardware, operating system, and everything that runs directly on the host. Values were read from the live system on 2026-10-13.

## Hardware

| Component | Detail |
|---|---|
| Motherboard | Gigabyte B450 AORUS M, UEFI firmware F50 (2019-11-27) |
| CPU | AMD Ryzen 5 2600X, 6 cores / 12 threads, 2.2 to 3.8 GHz, AMD-V capable |
| Memory | 32 GB DDR4, non-ECC: 4 x 8 GB from two different kits, all running at 2666 MT/s. All four slots are populated (board maximum 128 GB). 8 GB swap file at `/swap.img` |
| Boot disk | Sabrent NVMe, 238.5 GB (Phison E12 controller) |
| Cache disk | Kingston SA400 SATA SSD, 111.8 GB |
| Data disk | Seagate ST4000DM000 HDD, 3.6 TB |
| GPU | AMD Radeon "Oland" (R7 240 class), display output only, not used by any workload |
| Network | Realtek RTL8111 1 GbE (`eno1`) |
| Form factor | Desktop chassis, no BMC or IPMI |

Sensors come from `lm-sensors`: `k10temp` for the CPU (`Tctl`, which the thermal watchdog reads), `amdgpu`, and the NVMe composite temperature. The motherboard's secondary `it8792` chip is detected but its fan inputs read 0 RPM, so fan speeds are not monitored.

At idle the CPU sits around 48 °C and the NVMe around 28 °C.

## Operating system

| | |
|---|---|
| Distribution | Ubuntu Server 26.04.1 LTS (Resolute Raccoon) |
| Kernel | 7.0.0-34-generic running; 7.0.0-38 installed and waiting for a reboot |
| Boot | UEFI, GRUB, ext4 root on NVMe |
| Init / network | systemd, systemd-networkd via netplan (`eno1` with DHCPv4 and DHCPv6), systemd-resolved (stub resolver) |
| Time | chrony, synchronized to Ubuntu NTS servers; time zone America/New_York |
| Uptime at audit | 17 days (booted 2026-09-26) |

## Resource usage at audit

| Metric | Value |
|---|---|
| Load average | 0.17 / 0.17 / 0.12 |
| CPU | about 99% idle |
| Memory | 7.4 GiB used, 22 GiB page cache, 22 GiB available |
| Swap | 280 MiB of 8 GiB |
| Root filesystem | 93 GB of 233 GB (42%) |
| `/mnt/storage` | 18 GB of 3.6 TB (1%) |

Largest memory users are `immich_server` (1.4 GiB), `n8n` (485 MiB), and `SnapOtter` (466 MiB). No OOM kills are recorded in the kernel log.

## Users

| User | UID | Purpose |
|---|---|---|
| `admin` | 1000 | Interactive administrator. Member of `sudo`, `docker`, `adm`, `lxd`, `uosserver`. Sudo requires a password |
| `uosserver` | 1001 | Service account created by the UniFi OS Server installer; owns the rootless Podman container |

`root` cannot log in over SSH.

## Software installed outside the base system

| Area | Packages |
|---|---|
| Containers | `docker-ce` 29.8.1, `docker-compose-plugin` 5.5.1, `docker-buildx-plugin`, `containerd.io` 2.3.6, `podman` 5.7.0 |
| Remote access | `tailscale` 1.102.4, `openssh-server` 10.2 |
| Security | `ufw` 0.36.2, `fail2ban` 1.1.0, `unattended-upgrades`, `debsums` |
| Storage and backup | `bcache-tools`, `restic` 0.18.1, `smartmontools` |
| Monitoring and tuning | `lm-sensors`, `cpulimit`, `sysstat`, `btop`, `stress-ng`, `fastfetch` |
| Left over from earlier setups | `mongodb-org-server` 7.0.43 (held), `mongodb-org-shell`, `openjdk-17-jre-headless`, `ipmitool` |
| Shell tooling | `neovim`, `ripgrep`, `fzf`, `net-tools`, `netcat-traditional` |

Third-party APT sources: Docker, Tailscale, MongoDB 7.0, and Ubiquiti UniFi. No snaps are installed.

## systemd units

### Custom units

| Unit | Type | What it does | Source |
|---|---|---|---|
| `thermal-watchdog.service` | simple, always restarts | Runs the CPU temperature watchdog; requires `docker.service` | [`scripts/`](../scripts/thermal-watchdog.service) |
| `homelab-backup.timer` | timer, `OnCalendar=daily`, persistent | Triggers the backup at midnight | [`scripts/`](../scripts/homelab-backup.timer) |
| `homelab-backup.service` | oneshot | Runs `/usr/local/bin/homelab-backup.sh`. **Currently failing** | [`scripts/`](../scripts/homelab-backup.service) |
| `tailscale-gro.service` | oneshot, before `tailscaled` | `ethtool -K eno1 rx-udp-gro-forwarding on rx-gro-list off` | [`system/`](../system/tailscale-gro.service) |
| `wait-for-internet.service` | oneshot, before `docker` | Blocks up to 120 s until a public hostname resolves | [`system/`](../system/wait-for-internet.service) |
| `uosserver.service` | simple, user `uosserver` | UniFi OS Server | Installed by vendor |
| `uosserver-updater.service` | simple, root | UniFi OS Server self-updater | Installed by vendor |

### Other notable running services

`docker`, `containerd`, `tailscaled`, `ssh`, `fail2ban`, `ufw`, `chrony`, `smartmontools`, `unattended-upgrades`, `rsyslog`, `cron`, `mongod`, `fwupd`, `sysstat`.

Also enabled by the Ubuntu Server defaults but not needed on this machine: `ModemManager`, `multipathd`, `open-iscsi`, `udisks2`, `upower`.

### Failed units at audit

| Unit | Cause |
|---|---|
| `homelab-backup.service` | Script references a container that no longer exists. See [finding 1](findings.md#1-nightly-backups-have-been-failing-since-2026-09-22) |
| `systemd-networkd-wait-online.service` | Timed out after 120 s at boot. `wait-for-internet.service` is the working substitute |
| `openipmi.service` | No IPMI hardware on this board |

### Timers

| Timer | Schedule | Purpose |
|---|---|---|
| `homelab-backup.timer` | daily 00:00 | Backups |
| `apt-daily.timer`, `apt-daily-upgrade.timer` | daily | Package lists and unattended upgrades |
| `fstrim.timer` | weekly | SSD TRIM |
| `e2scrub_all.timer` | weekly | ext4 metadata check |
| `logrotate.timer` | daily | Log rotation |
| `sysstat-collect.timer` | every 10 min | `sar` performance history |
| `fwupd-refresh.timer` | periodic | Firmware metadata |

There are no user crontabs. Watchtower's 04:00 schedule runs inside its container, not from systemd or cron.

## Kernel parameters

| File | Setting | Why |
|---|---|---|
| [`99-tailscale.conf`](../system/99-tailscale.conf) | `net.ipv4.ip_forward = 1`, `net.ipv6.conf.all.forwarding = 1` | Subnet routing |
| [`99-uosserver.conf`](../system/99-uosserver.conf) | `net.ipv4.ping_group_range = 0 2147483647` | Lets the rootless UniFi container send ICMP |

## Docker daemon

[`/etc/docker/daemon.json`](../system/docker-daemon.json) enables IPv6 on the default bridge with a ULA range and turns on `ip6tables`:

```json
{
  "ipv6": true,
  "fixed-cidr-v6": "fd00:dead:beef::/64",
  "ip6tables": true
}
```

Disk usage: 68.7 GB of images (26.6 GB reclaimable), 17.2 GB of build cache, 2.8 GB in named volumes.

## How this was collected

Most of the audit ran as an unprivileged user in the `docker` and `adm` groups. A second pass with root read the firewall rules, the effective SSH daemon configuration, SMART data, the memory layout, the netplan file, and the restic snapshot list. Every command was read-only.
