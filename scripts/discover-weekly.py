#!/usr/bin/env python3
"""Discover Weekly for Navidrome.

Once a week:
  1. Clean up: delete songs fetched by earlier runs that are older than KEEP_DAYS
     and that the user neither starred, rated 4+, nor played at least twice.
  2. Pick new songs: the current ListenBrainz "Weekly Exploration" playlist first,
     then unheard ListenBrainz collaborative-filtering recommendations.
     Skips songs already in the library or fetched before, max 2 per artist.
  3. Download them through slskd (FLAC preferred, MP3 >= 256 kbps otherwise),
     move them to <library>/discover/<date>/ and write
     <library>/discover/Discover Weekly.m3u, which Navidrome imports as a playlist.

Configuration comes from environment variables (see DEFAULTS below).
SLSKD_USERNAME / SLSKD_PASSWORD are the slskd web UI login.

Usage: discover-weekly.py [--dry-run] [--count N] [--no-cleanup]
"""
import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULTS = {
    "LB_USER": "",           # ListenBrainz username (required)
    "ND_USER": "",           # Navidrome username whose plays/stars decide cleanup (required)
    "SLSKD_URL": "http://127.0.0.1:5030",
    "LIBRARY": "/mnt/storage/music/library",
    "ND_DB": "/mnt/storage/music/navidrome/navidrome.db",
    "STATE_DIR": "/mnt/storage/music/discover-state",
    "COUNT": "25",
    "KEEP_DAYS": "28",
    "PER_ARTIST": "2",
    "DEADLINE_MIN": "120",   # total time allowed for downloads
    "STALL_MIN": "10",       # give up on a source that hasn't started after this
}
CFG = {k: os.environ.get(k, v) for k, v in DEFAULTS.items()}
LB_API = "https://api.listenbrainz.org/1"
UA = "discover-weekly/1.0 (self-hosted Navidrome helper)"

LIB = Path(CFG["LIBRARY"])
DL_ROOT = LIB / "soulseek"          # where slskd puts finished downloads
DISCOVER = LIB / "discover"
STATE_FILE = Path(CFG["STATE_DIR"]) / "state.json"
PLAYLIST = DISCOVER / "Discover Weekly.m3u"

BAD_WORDS = {"instrumental", "karaoke", "acapella", "acappella", "remix", "sped",
             "slowed", "nightcore", "reverb", "cover", "8d", "tutorial"}


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- helpers
def norm(s):
    a = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    a = re.sub(r"[^a-z0-9]+", " ", a).strip()
    return a or re.sub(r"\s+", " ", s.lower()).strip()


def clean_title(t):
    t = re.sub(r"\s*[\(\[][^\)\]]*\b(feat|ft|featuring|with|prod)\b[^\)\]]*[\)\]]", "", t, flags=re.I)
    t = re.sub(r"\s+(feat\.?|ft\.?|featuring)\s.*$", "", t, flags=re.I)
    return t.strip()


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", s).strip(" .")
    return s[:150] or "track"


def http_json(url, method="GET", body=None, headers=None, timeout=30):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw.strip() else None


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"tracks": {}, "runs": []}


def save_state(st):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, ensure_ascii=False))
    tmp.replace(STATE_FILE)


def this_week():
    """Monday of the current week, so reruns in the same week top up one playlist."""
    today = dt.date.today()
    return (today - dt.timedelta(days=today.weekday())).isoformat()


def nd_db():
    return sqlite3.connect(f"file:{CFG['ND_DB']}?mode=ro", uri=True)


# ---------------------------------------------------------------- cleanup
def cleanup(st, dry):
    cutoff = time.time() - int(CFG["KEEP_DAYS"]) * 86400
    old = {k: v for k, v in st["tracks"].items()
           if v.get("status") == "fetched" and v["fetched_at"] < cutoff}
    if not old:
        log("cleanup: nothing old enough")
        return
    db = nd_db()
    row = db.execute('select id from user where user_name=?', (CFG["ND_USER"],)).fetchone()
    if not row:
        log("cleanup: Navidrome user not found, skipping")
        return
    uid = row[0]
    removed = kept = 0
    for key, t in old.items():
        p = DISCOVER / t["path"]
        rel = str(p.relative_to(LIB))
        ann = db.execute(
            "select coalesce(a.play_count,0), coalesce(a.starred,0), coalesce(a.rating,0) "
            "from media_file m left join annotation a on a.item_id=m.id and a.item_type='media_file' "
            "and a.user_id=? where m.path=?", (uid, rel)).fetchone()
        plays, starred, rating = ann or (0, 0, 0)
        if starred or rating >= 4 or plays >= 2:
            t["status"] = "kept"
            kept += 1
            log(f"cleanup: keep  {t['path']} (plays={plays} starred={starred} rating={rating})")
            continue
        log(f"cleanup: remove {t['path']} (plays={plays})")
        if not dry:
            if p.is_file() and DISCOVER in p.parents:
                p.unlink()
            t["status"] = "removed"
            t["removed_at"] = time.time()
            removed += 1
    if not dry:
        for d in DISCOVER.glob("*/"):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
    log(f"cleanup: removed {removed}, kept {kept}")


# ---------------------------------------------------------------- picking
def library_index():
    db = nd_db()
    mbids, titles = set(), {}
    for mbid, title, artist in db.execute(
            "select mbz_recording_id, title, artist from media_file where missing=0"):
        if mbid:
            mbids.add(mbid)
        titles.setdefault(norm(clean_title(title)), []).append(norm(artist))
    return mbids, titles


def in_library(rec, mbids, titles):
    if rec["mbid"] in mbids:
        return True
    a = norm(rec["artist"])
    return any(a in x for x in titles.get(norm(rec["title"]), []))


def weekly_exploration():
    d = http_json(f"{LB_API}/user/{CFG['LB_USER']}/playlists/createdfor?count=25")
    now = dt.datetime.now(dt.timezone.utc)
    for p in d.get("playlists", []):
        pl = p["playlist"]
        ext = pl.get("extension", {}).get("https://musicbrainz.org/doc/jspf#playlist", {})
        meta = ext.get("additional_metadata", {})
        if meta.get("algorithm_metadata", {}).get("source_patch") != "weekly-exploration":
            continue
        exp = meta.get("expires_at")
        if exp and dt.datetime.fromisoformat(exp) < now:
            log(f"pick: newest Weekly Exploration ({pl['title']}) has expired")
            return []
        mbid = pl["identifier"].rsplit("/", 1)[-1]
        full = http_json(f"{LB_API}/playlist/{mbid}")["playlist"]
        out = []
        for t in full.get("track", []):
            arts = (t.get("extension", {}).get("https://musicbrainz.org/doc/jspf#track", {})
                    .get("additional_metadata", {}).get("artists", []))
            ident = t.get("identifier")
            ident = ident[0] if isinstance(ident, list) else ident
            out.append({
                "mbid": (ident or "").rsplit("/", 1)[-1],
                "artist": arts[0]["artist_credit_name"] if arts else t.get("creator", ""),
                "title": clean_title(t.get("title", "")),
                "length": (t.get("duration") or 0) / 1000,
                "source": "weekly-exploration",
            })
        log(f"pick: {pl['title']}: {len(out)} tracks")
        return out
    log("pick: no Weekly Exploration playlist found")
    return []


def cf_recommendations(limit):
    d = http_json(f"{LB_API}/cf/recommendation/user/{CFG['LB_USER']}/recording?count=1000")
    if not d:
        return []
    ids = [x["recording_mbid"] for x in d["payload"]["mbids"] if not x.get("latest_listened_at")]
    out = []
    for i in range(0, min(len(ids), limit), 50):
        chunk = ids[i:i + 50]
        meta = http_json(f"{LB_API}/metadata/recording/?recording_mbids={','.join(chunk)}&inc=artist")
        for m in chunk:
            v = meta.get(m)
            if not v:
                continue
            arts = v.get("artist", {}).get("artists", [])
            out.append({
                "mbid": m,
                "artist": arts[0]["name"] if arts else v["artist"].get("name", ""),
                "title": clean_title(v["recording"]["name"]),
                "length": (v["recording"].get("length") or 0) / 1000,
                "source": "cf-recommendation",
            })
    log(f"pick: {len(out)} unheard CF recommendations with metadata")
    return out


def pick(st, count):
    mbids, titles = library_index()
    seen_keys = set(st["tracks"])
    per_artist, out = {}, []
    want = count * 3  # extra, because some won't be found on Soulseek
    cands = weekly_exploration()
    cands += cf_recommendations(limit=want * 3)
    for r in cands:
        key = r["mbid"] or f"{norm(r['artist'])}|{norm(r['title'])}"
        a = norm(r["artist"])
        if not r["title"] or key in seen_keys or in_library(r, mbids, titles):
            continue
        if per_artist.get(a, 0) >= int(CFG["PER_ARTIST"]):
            continue
        seen_keys.add(key)
        per_artist[a] = per_artist.get(a, 0) + 1
        r["key"] = key
        out.append(r)
        if len(out) >= want:
            break
    log(f"pick: {len(out)} candidate songs for {count} slots")
    return out


# ---------------------------------------------------------------- slskd
class Slskd:
    def __init__(self):
        self.base = CFG["SLSKD_URL"].rstrip("/") + "/api/v0"
        r = http_json(f"{self.base}/session", "POST",
                      {"username": os.environ["SLSKD_USERNAME"], "password": os.environ["SLSKD_PASSWORD"]})
        self.h = {"Authorization": f"Bearer {r['token']}"}

    def call(self, path, method="GET", body=None):
        return http_json(self.base + path, method, body, self.h)

    def search(self, text):
        sid = str(uuid.uuid4())
        self.call("/searches", "POST", {"id": sid, "searchText": text, "searchTimeout": 12000,
                                         "responseLimit": 150, "fileLimit": 20000,
                                         "filterResponses": True, "minimumResponseFileCount": 1})
        for _ in range(30):
            time.sleep(1.5)
            if "Completed" in self.call(f"/searches/{sid}")["state"]:
                break
        res = self.call(f"/searches/{sid}/responses") or []
        try:
            self.call(f"/searches/{sid}", "DELETE")
        except urllib.error.HTTPError:
            pass
        return res

    def enqueue(self, user, f):
        self.call(f"/transfers/downloads/{urllib.parse.quote(user)}", "POST",
                  [{"filename": f["filename"], "size": f["size"]}])

    def transfer(self, user, filename):
        try:
            d = self.call(f"/transfers/downloads/{urllib.parse.quote(user)}")
        except urllib.error.HTTPError:
            return None
        for dd in (d or {}).get("directories", []):
            for f in dd["files"]:
                if f["filename"] == filename:
                    return f
        return None

    def cancel(self, user, tid, remove=True):
        try:
            self.call(f"/transfers/downloads/{urllib.parse.quote(user)}/{tid}?remove={str(remove).lower()}", "DELETE")
        except urllib.error.HTTPError:
            pass


def rank(rec, responses):
    title_t = set(norm(rec["title"]).split())
    artist_t = set(norm(rec["artist"]).split())
    best = {}
    for resp in responses:
        for f in resp.get("files", []):
            if f.get("isLocked"):
                continue
            ext = (f.get("extension") or f["filename"].rsplit(".", 1)[-1]).lower().lstrip(".")
            br = f.get("bitRate") or 0
            size = f.get("size") or 0
            if ext == "flac":
                if not 3e6 < size < 250e6:
                    continue
                q = 3
            elif ext == "mp3":
                if br < 256:
                    continue
                q = 2 if br >= 320 else 1
            else:
                continue
            parts = re.split(r"[\\/]", f["filename"])
            base_t = set(norm(parts[-1].rsplit(".", 1)[0]).split())
            path_t = set(norm(" ".join(parts[-3:])).split())
            if not title_t <= base_t or not artist_t <= path_t:
                continue
            if (base_t & BAD_WORDS) - title_t:
                continue
            if rec["length"] and f.get("length") and abs(f["length"] - rec["length"]) > 10:
                continue
            score = (q + (3 if resp.get("hasFreeUploadSlot") else 0)
                     - min(resp.get("queueLength", 0), 50) / 10
                     + min(resp.get("uploadSpeed", 0) / 1e6, 5) * 0.5)
            u = resp["username"]
            if u not in best or score > best[u][0]:
                best[u] = (score, u, f, ext)
    return [b[1:] for b in sorted(best.values(), key=lambda b: -b[0])][:4]


def locate(filename, size, since):
    parts = re.split(r"[\\/]", filename)
    p = DL_ROOT / parts[-2] / parts[-1] if len(parts) > 1 else DL_ROOT / parts[-1]
    if p.is_file():
        return p
    for q in DL_ROOT.rglob("*"):  # slskd may have sanitised the name
        if q.is_file() and q.stat().st_size == size and q.stat().st_mtime >= since - 120:
            return q
    return None


def fetch(st, recs, count, dry):
    sl = Slskd()
    week = this_week()
    dest_dir = DISCOVER / week
    deadline = time.time() + int(CFG["DEADLINE_MIN"]) * 60
    stall = int(CFG["STALL_MIN"]) * 60
    queue = list(recs)
    active, done = [], []

    def start_next(job):
        while job["cands"]:
            u, f, ext = job["cands"].pop(0)
            try:
                sl.enqueue(u, f)
            except urllib.error.HTTPError as e:
                log(f"  enqueue failed ({e.code}) from {u}")
                continue
            job.update(user=u, file=f, ext=ext, started=time.time(), last_bytes=0, last_move=time.time())
            log(f"  -> {u}: {f['filename'].split(chr(92))[-1]}")
            return True
        return False

    while time.time() < deadline and len(done) < count:
        # keep `count - done` downloads in flight
        while queue and len(active) + len(done) < count:
            rec = queue.pop(0)
            text = f"{norm(rec['artist'])} {norm(rec['title'])}"
            try:
                cands = rank(rec, sl.search(text))
            except Exception as e:  # noqa: BLE001 - keep going on any search error
                log(f"search error for {text}: {e}")
                cands = []
            log(f"search '{text}': {len(cands)} usable sources")
            if not cands:
                st["tracks"].setdefault(rec["key"], {}).update(
                    status="not-found", artist=rec["artist"], title=rec["title"], tried_at=time.time())
                continue
            if dry:
                u, f, ext = cands[0]
                log(f"  [dry] would fetch from {u}: {f['filename']}")
                done.append(rec)
                continue
            job = {"rec": rec, "cands": cands}
            if start_next(job):
                active.append(job)
        if dry or (not active and not queue):
            break
        time.sleep(15)
        for job in list(active):
            t = sl.transfer(job["user"], job["file"]["filename"])
            state = t["state"] if t else "missing"
            now = time.time()
            if state == "Completed, Succeeded":
                src = locate(job["file"]["filename"], job["file"]["size"], job["started"])
                active.remove(job)
                if not src:
                    log(f"  !! finished but file not found: {job['file']['filename']}")
                    continue
                rec = job["rec"]
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / f"{safe_name(rec['artist'] + ' - ' + rec['title'])}.{job['ext']}"
                n = 2
                while dest.exists():
                    dest = dest.with_stem(f"{dest.stem} ({n})")
                    n += 1
                src.rename(dest)
                try:
                    src.parent.rmdir()
                except OSError:
                    pass
                sl.cancel(job["user"], t["id"], remove=True)  # tidy the slskd list
                st["tracks"][rec["key"]] = {
                    "status": "fetched", "artist": rec["artist"], "title": rec["title"],
                    "source": rec["source"], "path": str(dest.relative_to(DISCOVER)),
                    "length": rec["length"], "fetched_at": now, "week": week}
                done.append(rec)
                save_state(st)
                log(f"  ok  {dest.name}  ({len(done)}/{count})")
                continue
            failed = state.startswith("Completed") or state == "missing"
            if t and state == "InProgress":
                if t.get("bytesTransferred", 0) > job["last_bytes"]:
                    job["last_bytes"], job["last_move"] = t["bytesTransferred"], now
                failed = now - job["last_move"] > 300
            elif not failed:
                failed = now - job["started"] > stall  # still queued / requested
            if failed:
                log(f"  xx  {job['user']} ({state}) for {job['rec']['artist']} - {job['rec']['title']}")
                if t:
                    sl.cancel(job["user"], t["id"], remove=True)
                if not start_next(job):
                    active.remove(job)
                    st["tracks"].setdefault(job["rec"]["key"], {}).update(
                        status="failed", artist=job["rec"]["artist"],
                        title=job["rec"]["title"], tried_at=now)
    for job in active:  # out of time
        t = sl.transfer(job["user"], job["file"]["filename"])
        if t:
            sl.cancel(job["user"], t["id"], remove=True)
        log(f"  timeout: {job['rec']['artist']} - {job['rec']['title']}")
    return done, week


def write_playlist(st, week):
    rows = [t for t in st["tracks"].values() if t.get("status") in ("fetched", "kept") and t.get("week") == week]
    if not rows:
        log("playlist: no songs this week, keeping the previous playlist")
        return
    lines = ["#EXTM3U", "#PLAYLIST:Discover Weekly"]
    for t in sorted(rows, key=lambda t: t["fetched_at"]):
        lines.append(f"#EXTINF:{int(t.get('length') or -1)},{t['artist']} - {t['title']}")
        lines.append(t["path"])
    tmp = PLAYLIST.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(PLAYLIST)
    log(f"playlist: {len(rows)} songs written to {PLAYLIST}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--count", type=int, default=int(CFG["COUNT"]))
    ap.add_argument("--no-cleanup", action="store_true")
    a = ap.parse_args()
    missing = [k for k in ("LB_USER", "ND_USER", "SLSKD_USERNAME", "SLSKD_PASSWORD")
               if not (CFG.get(k) or os.environ.get(k))]
    if missing:
        sys.exit(f"missing configuration: {', '.join(missing)}")
    st = load_state()
    DISCOVER.mkdir(parents=True, exist_ok=True)
    if not a.no_cleanup:
        cleanup(st, a.dry_run)
    have = sum(1 for t in st["tracks"].values()
               if t.get("week") == this_week() and t.get("status") in ("fetched", "kept"))
    need = max(a.count - have, 0)
    log(f"week {this_week()}: {have} songs already, fetching {need}")
    done, week = [], this_week()
    if need:
        recs = pick(st, need)
        done, week = fetch(st, recs, need, a.dry_run)
    if not a.dry_run:
        write_playlist(st, week)
        st["runs"].append({"at": time.time(), "week": week, "fetched": len(done)})
        save_state(st)
    log(f"done: {have + len(done)}/{a.count} songs this week")
    return 0 if (done or not need) else 1


if __name__ == "__main__":
    sys.exit(main())
