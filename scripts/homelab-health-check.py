#!/usr/bin/env python3
"""Periodic health check for problems that are not a failed systemd unit.

Checks:
  - containers that are restarting, unhealthy, or restarted 3+ times since the
    last run (a restart loop caught while the container is briefly up)
  - the nightly backup: last run failed, or no successful run for BACKUP_MAX_AGE_H
  - free space below DISK_MIN_FREE_PCT on each path in DISK_PATHS
  - the TLS certificate at CERT_CHECK_ADDR for CERT_CHECK_HOST: invalid, or
    expiring within CERT_MIN_DAYS
  - CPU temperature (k10temp Tctl) at or above CPU_MAX_C. The board's fan
    inputs cannot be read, so this is how a failed fan would show up.

New problems are posted to Discord with a ping; cleared problems are posted
without one. State is kept in STATE_DIR so each problem is reported once.
Usage: homelab-health-check.py [--dry-run]
"""
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time

STATE_DIR = os.environ.get("STATE_DIR", "/var/lib/homelab-alerts")
STATE = os.path.join(STATE_DIR, "health-state.json")
BACKUP_UNIT = os.environ.get("BACKUP_UNIT", "homelab-backup.service")
BACKUP_MAX_AGE_H = float(os.environ.get("BACKUP_MAX_AGE_H", "26"))
DISK_PATHS = os.environ.get("DISK_PATHS", "/ /mnt/storage").split()
DISK_MIN_FREE_PCT = float(os.environ.get("DISK_MIN_FREE_PCT", "10"))
CERT_HOST = os.environ.get("CERT_CHECK_HOST", "")
CERT_ADDR = os.environ.get("CERT_CHECK_ADDR", "")
CERT_MIN_DAYS = int(os.environ.get("CERT_MIN_DAYS", "14"))
CPU_MAX_C = float(os.environ.get("CPU_MAX_C", "85"))
IGNORE_CONTAINERS = set(os.environ.get("IGNORE_CONTAINERS", "").split())


def run(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def check_containers(prev_counts):
    problems, counts = {}, {}
    ids = run("docker", "ps", "-aq").split()
    if not ids:
        return problems, counts
    for c in json.loads(run("docker", "inspect", *ids)):
        name = c["Name"].lstrip("/")
        if name in IGNORE_CONTAINERS:
            continue
        st = c["State"]
        counts[name] = c.get("RestartCount", 0)
        health = (st.get("Health") or {}).get("Status")
        if st.get("Restarting"):
            problems[f"container:{name}"] = (
                f"Container {name} is restart-looping (exit code {st.get('ExitCode')}, "
                f"{counts[name]} restarts)")
        elif st.get("Running") and health == "unhealthy":
            problems[f"container:{name}"] = f"Container {name} is unhealthy"
        elif name in prev_counts and counts[name] - prev_counts[name] >= 3:
            problems[f"container:{name}"] = (
                f"Container {name} restarted {counts[name] - prev_counts[name]} times "
                f"in the last check interval")
    return problems, counts


def container_log(key):
    name = key.split(":", 1)[1]
    try:
        r = subprocess.run(["docker", "logs", "--tail", "15", name],
                           capture_output=True, text=True, timeout=20)
        return (r.stdout + r.stderr)[-1500:]
    except Exception:
        return ""


def check_backup():
    out = run("systemctl", "show", "--timestamp=unix", "-p", "Result",
              "-p", "ExecMainExitTimestamp", "-p", "ExecMainStatus", BACKUP_UNIT)
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    last = props.get("ExecMainExitTimestamp", "").lstrip("@")
    if props.get("Result") not in ("success", None) or props.get("ExecMainStatus", "0") != "0":
        return {"backup": f"Last {BACKUP_UNIT} run failed (result {props.get('Result')}, "
                          f"status {props.get('ExecMainStatus')})"}
    if not last.isdigit():
        return {"backup": f"{BACKUP_UNIT} has not run since boot"} if uptime_h() > BACKUP_MAX_AGE_H else {}
    age = (time.time() - int(last)) / 3600
    if age > BACKUP_MAX_AGE_H:
        return {"backup": f"No successful {BACKUP_UNIT} run for {age:.0f} hours"}
    return {}


def uptime_h():
    with open("/proc/uptime") as f:
        return float(f.read().split()[0]) / 3600


def check_disks():
    problems = {}
    for p in DISK_PATHS:
        try:
            u = shutil.disk_usage(p)
        except OSError as e:
            problems[f"disk:{p}"] = f"Cannot read free space on {p}: {e}"
            continue
        free = 100 * u.free / u.total
        if free < DISK_MIN_FREE_PCT:
            problems[f"disk:{p}"] = f"{p} has {free:.1f}% free ({u.free / 1e9:.1f} GB)"
    return problems


def check_cert():
    if not (CERT_HOST and CERT_ADDR):
        return {}
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((CERT_ADDR, 443), timeout=15) as s:
            with ctx.wrap_socket(s, server_hostname=CERT_HOST) as t:
                cert = t.getpeercert()
        days = (ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) / 86400
    except Exception as e:
        return {"cert": f"TLS check for {CERT_HOST} failed: {e}"}
    if days < CERT_MIN_DAYS:
        return {"cert": f"Certificate for {CERT_HOST} expires in {days:.0f} days"}
    return {}


def check_cpu_temp():
    for hw in sorted(os.listdir("/sys/class/hwmon")):
        base = os.path.join("/sys/class/hwmon", hw)
        try:
            with open(os.path.join(base, "name")) as f:
                if f.read().strip() != "k10temp":
                    continue
            with open(os.path.join(base, "temp1_input")) as f:
                temp = int(f.read()) / 1000
        except OSError:
            continue
        if temp >= CPU_MAX_C:
            return {"cpu-temp": f"CPU temperature is {temp:.0f} C (alert at {CPU_MAX_C:.0f} C)"}
        return {}
    return {"cpu-temp": "Cannot read the CPU temperature (no k10temp sensor)"}


def main():
    dry = "--dry-run" in sys.argv
    try:
        with open(STATE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    old = state.get("problems", {})
    problems, counts = check_containers(state.get("restart_counts", {}))
    for check in (check_backup, check_disks, check_cert, check_cpu_temp):
        problems.update(check())

    new = {k: v for k, v in problems.items() if k not in old}
    cleared = {k: v for k, v in old.items() if k not in problems}
    host = socket.gethostname()
    if dry:
        print(json.dumps({"problems": problems, "new": new, "cleared": cleared}, indent=2))
        return
    import importlib.util
    spec = importlib.util.spec_from_file_location("dn", "/usr/local/bin/discord-notify.py")
    dn = importlib.util.module_from_spec(spec); spec.loader.exec_module(dn)
    for k, msg in new.items():
        dn.send(f"{msg} on {host}", container_log(k) if k.startswith("container:") else "", ping=True)
    for k, msg in cleared.items():
        dn.send(f"Resolved on {host}: {msg}")
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"problems": problems, "restart_counts": counts, "checked": int(time.time())}, f, indent=2)
    os.replace(tmp, STATE)
    for k, msg in problems.items():
        print(("NEW " if k in new else "    ") + msg)
    if not problems:
        print("All checks passed")


if __name__ == "__main__":
    main()
