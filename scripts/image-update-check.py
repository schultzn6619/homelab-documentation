#!/usr/bin/env python3
"""Report newer releases of the container images that are pinned to a version tag.

Looks at every running container whose image tag is a version number such as
2.16.0 or 1.0.43-cli, lists that repository's tags, and keeps the newer tags
with the same shape (same number of parts, same suffix), so -alpine variants,
build tags and pr-123 tags are ignored. Posts a summary to a Discord webhook
(DISCORD_WEBHOOK_URL). Releases listed in IGNORE_TAGS ("container:tag ...")
are left out. Nothing is pulled or changed.

Usage: image-update-check.py [--dry-run] [--test]
  --dry-run  print the report instead of posting it
  --test     post a short test message and exit
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

UA = "homelab-image-update-check/1.0"
VERSION_TAG = re.compile(r"^v?(\d+(?:\.\d+)+)(-[a-z][a-z0-9]*)?$")

RELEASE_NOTES = {
    "jc21/nginx-proxy-manager": "https://github.com/NginxProxyManager/nginx-proxy-manager/releases",
    "portainer/portainer-ce": "https://github.com/portainer/portainer/releases",
    "vaultwarden/server": "https://github.com/dani-garcia/vaultwarden/releases",
    "couchdb": "https://docs.couchdb.org/en/stable/whatsnew/index.html",
    "deluan/navidrome": "https://github.com/navidrome/navidrome/releases",
    "slskd/slskd": "https://github.com/slskd/slskd/releases",
    "ghcr.io/vrtmrz/livesync-cli": "https://github.com/vrtmrz/obsidian-livesync/releases",
}


def http_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def running_pinned():
    """(container, repository, tag) for running containers on a version tag."""
    names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], check=True,
                           capture_output=True, text=True).stdout.split()
    out = []
    for name in sorted(names):
        image = subprocess.run(["docker", "inspect", "--format", "{{.Config.Image}}", name],
                               check=True, capture_output=True, text=True).stdout.strip()
        if "@" in image:
            continue
        repo, sep, tag = image.rpartition(":")
        if not sep or "/" in tag or not VERSION_TAG.match(tag):
            continue
        out.append((name, repo, tag))
    return out


def list_tags(repo):
    if repo.startswith("ghcr.io/"):
        path = repo[len("ghcr.io/"):]
        token = http_json(f"https://ghcr.io/token?scope=repository:{path}:pull")["token"]
        tags, last = [], None
        while True:
            url = f"https://ghcr.io/v2/{path}/tags/list?n=1000"
            if last:
                url += "&last=" + urllib.parse.quote(last)
            page = http_json(url, {"Authorization": f"Bearer {token}"}).get("tags") or []
            tags += page
            if len(page) < 1000:
                return tags
            last = page[-1]
    if "/" not in repo:
        repo = "library/" + repo
    elif "." in repo.split("/")[0]:
        raise ValueError(f"unsupported registry for {repo}")
    # Newest first. Docker Hub refuses pages past the first 1,000 tags (HTTP 403),
    # which is far more history than is needed to spot a newer release.
    tags = []
    url = f"https://hub.docker.com/v2/repositories/{repo}/tags?page_size=100&name=.&ordering=last_updated"
    for _ in range(10):
        page = http_json(url)
        tags += [t["name"] for t in page.get("results", [])]
        url = page.get("next")
        if not url:
            break
    return tags


def newer_tags(current, tags):
    m = VERSION_TAG.match(current)
    cur = tuple(int(x) for x in m.group(1).split("."))
    suffix = m.group(2) or ""
    found = []
    for t in set(tags):
        tm = VERSION_TAG.match(t)
        if not tm or (tm.group(2) or "") != suffix:
            continue
        ver = tuple(int(x) for x in tm.group(1).split("."))
        # Same number of parts, or one more (CouchDB's 3.5.2.1 style rebuilds).
        if len(ver) not in (len(cur), len(cur) + 1):
            continue
        if ver > cur:
            found.append((ver, t))
    return [t for _, t in sorted(found)]


def ignored():
    """IGNORE_TAGS="container:tag ..." hides releases known to be bad."""
    return set(os.environ.get("IGNORE_TAGS", "").split())


def build_report():
    lines, errors = [], []
    skip = ignored()
    for name, repo, tag in running_pinned():
        try:
            newer = [t for t in newer_tags(tag, list_tags(repo)) if f"{name}:{t}" not in skip]
        except Exception as e:  # report and carry on with the others
            errors.append(f"- `{name}` ({repo}): could not list tags: {e}")
            continue
        if not newer:
            continue
        latest = newer[-1]
        major = VERSION_TAG.match(latest).group(1).split(".")[0] != VERSION_TAG.match(tag).group(1).split(".")[0]
        flag = " **(major version)**" if major else ""
        between = f", {len(newer) - 1} other release(s) in between" if len(newer) > 1 else ""
        notes = RELEASE_NOTES.get(repo)
        link = f" - [release notes](<{notes}>)" if notes else ""
        lines.append(f"- `{name}`: {tag} -> **{latest}**{flag}{between}{link}")
    return lines, errors


def post(content):
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        sys.exit("DISCORD_WEBHOOK_URL is not set")
    for start in range(0, len(content), 1900):
        body = json.dumps({"content": content[start:start + 1900],
                           "allowed_mentions": {"parse": []}}).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": UA})
        urllib.request.urlopen(req, timeout=30).close()


def main():
    args = set(sys.argv[1:])
    host = os.uname().nodename
    if "--test" in args:
        post(f"Test message from the image update check on `{host}`.")
        print("Test message posted")
        return
    lines, errors = build_report()
    parts = []
    if lines:
        parts.append(f"**Image updates available on `{host}`**\n" + "\n".join(lines)
                     + "\nUpdate by hand: see docs/operations.md (Updating).")
    if errors:
        parts.append("**Image update check had errors**\n" + "\n".join(errors))
    report = "\n\n".join(parts)
    if not report:
        print("All pinned images are on their newest release")
        return
    if "--dry-run" in args:
        print(report)
    else:
        post(report)
        print(report)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        try:
            if "--dry-run" not in sys.argv:
                post(f"**Image update check failed on `{os.uname().nodename}`**: {e}")
        finally:
            raise
