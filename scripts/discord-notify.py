#!/usr/bin/env python3
"""Post a message to the homelab Discord webhook.

Usage: discord-notify.py [--ping] [--key KEY --cooldown SECONDS] TITLE [BODY]
  BODY is read from stdin when it is not given and stdin is not a terminal.
  --ping      mention DISCORD_PING_USER_ID
  --key/--cooldown  skip the post if the same KEY was posted less than
              SECONDS ago (state in STATE_DIR, default /var/lib/homelab-alerts)

Settings come from the environment, or from /etc/discord-notify.env when
DISCORD_WEBHOOK_URL is not set and that file is readable:
  DISCORD_WEBHOOK_URL, DISCORD_PING_USER_ID
"""
import json
import os
import re
import sys
import time
import urllib.request

ENV_FILE = "/etc/discord-notify.env"
UA = "homelab-discord-notify/1.0"
LIMIT = 1900


def load_settings():
    if not os.environ.get("DISCORD_WEBHOOK_URL") and os.access(ENV_FILE, os.R_OK):
        with open(ENV_FILE) as f:
            for line in f:
                m = re.match(r"^\s*([A-Z_]+)=(.*)$", line)
                if m:
                    os.environ.setdefault(m.group(1), m.group(2).strip().strip('"'))
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        raise SystemExit("DISCORD_WEBHOOK_URL is not set")
    return url, os.environ.get("DISCORD_PING_USER_ID", "").strip()


def in_cooldown(key, seconds):
    state_dir = os.environ.get("STATE_DIR", "/var/lib/homelab-alerts")
    path = os.path.join(state_dir, "cooldown-" + re.sub(r"[^A-Za-z0-9_.@-]", "_", key))
    now = time.time()
    try:
        if now - os.path.getmtime(path) < seconds:
            return True
    except OSError:
        pass
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(path, "w") as f:
            f.write(str(int(now)))
    except OSError:
        pass  # no state dir: never suppress
    return False


def send(title, body="", ping=False):
    url, user_id = load_settings()
    head = f"<@{user_id}> " if ping and user_id else ""
    text = f"{head}**{title}**"
    if body:
        body = body.strip()
        room = LIMIT - len(text) - 10
        if len(body) > room:
            body = body[: room - 20] + "\n... (truncated)"
        text += "\n```\n" + body.replace("```", "'''") + "\n```"
    payload = {"content": text,
               "allowed_mentions": {"users": [user_id] if ping and user_id else []}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    urllib.request.urlopen(req, timeout=30).close()


def main():
    args = sys.argv[1:]
    ping = "--ping" in args
    args = [a for a in args if a != "--ping"]
    key = cooldown = None
    if "--key" in args:
        i = args.index("--key"); key = args[i + 1]; del args[i:i + 2]
    if "--cooldown" in args:
        i = args.index("--cooldown"); cooldown = int(args[i + 1]); del args[i:i + 2]
    if not args:
        raise SystemExit(__doc__)
    title = args[0]
    body = args[1] if len(args) > 1 else ("" if sys.stdin.isatty() else sys.stdin.read())
    if key and cooldown and in_cooldown(key, cooldown):
        print(f"Skipped (posted '{key}' less than {cooldown}s ago)")
        return
    send(title, body, ping)
    print("Posted")


if __name__ == "__main__":
    main()
