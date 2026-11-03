#!/usr/bin/env python3
"""Keep unreleased/leaked music tidy in the Navidrome library.

1. Sort: folders that slskd finished downloading into <library>/soulseek/ are moved
   to <library>/leaks/<Artist>/ when their folder name or tags say they are leaks
   (unreleased, leak(s), leaked, snippet(s), OG file(s), CDQ) and they match exactly
   one artist in ARTISTS. Folders touched in the last 5 minutes are left alone.
2. Tag: every audio file under <library>/leaks/<Artist>/ gets
     album artist = <Artist>, genre = Unreleased,
     album = the sub-folder name(s), cleaned, ending in "(Unreleased)",
     artist = <Artist> unless the existing artist tag already names them,
     title = the existing title, or one derived from the file name if missing/junk,
   and MusicBrainz album IDs are removed so leaks never merge with official albums.
   Files are only rewritten when something changes.

Usage: leaks-organize.py [--dry-run]
"""
import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

import mutagen

LIB = Path(os.environ.get("LIBRARY", "/mnt/storage/music/library"))
INBOX = LIB / "soulseek"
LEAKS = LIB / "leaks"
ARTISTS = {  # canonical name -> lower-case patterns that identify them
    "Juice WRLD": [r"juice\s*wrld", r"juicewrld"],
    "Playboi Carti": [r"playboi\s*carti", r"\bcarti\b"],
    "Travis Scott": [r"travis\s*scott", r"\btravis\b"],
    "Yeat": [r"\byeat\b"],
    "Lil Uzi Vert": [r"lil\s*uzi(\s*vert)?", r"\buzi\b"],
}
LEAK_WORDS = re.compile(r"\b(unreleased|leaks?|leaked|snippets?|og\s*files?|cdq)\b", re.I)
AUDIO = {".flac", ".mp3", ".m4a", ".ogg", ".opus"}
JUNK_TITLE = re.compile(r"^\s*(track\s*)?\d*\s*$", re.I)
QUALITY_BRACKETS = re.compile(
    r"\s*[\[\(][^\]\)]*\b(flac|mp3|kbps|320|v0|web|cdq|\d+\s*b(it)?|\d+(\.\d+)?\s*khz)\b[^\]\)]*[\]\)]", re.I)
SETTLE = 300  # seconds a folder must be untouched before it is moved


def log(*a):
    print(*a, flush=True)


def audio_files(d):
    return sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO)


def easy(path):
    try:
        return mutagen.File(path, easy=True)
    except Exception as e:  # noqa: BLE001 - unreadable file, report and skip
        log(f"  can't read tags: {path.name}: {e}")
        return None


def first(tags, key):
    v = tags.get(key) if tags is not None else None
    return v[0] if v else ""


def match_artists(text):
    t = text.lower()
    return {name for name, pats in ARTISTS.items() if any(re.search(p, t) for p in pats)}


# ---------------------------------------------------------------- 1. sort
def sort_inbox(dry):
    if not INBOX.is_dir():
        return
    now = time.time()
    for d in sorted(p for p in INBOX.iterdir() if p.is_dir()):
        files = audio_files(d)
        if not files:
            continue
        if now - max(p.stat().st_mtime for p in [d, *files]) < SETTLE:
            continue
        sample = [easy(f) for f in files[:5]]
        tag_text = " ".join(f"{first(t, 'album')} {first(t, 'artist')} {first(t, 'albumartist')}"
                            for t in sample if t is not None)
        if not (LEAK_WORDS.search(d.name) or LEAK_WORDS.search(tag_text)):
            continue
        who = match_artists(d.name) or match_artists(tag_text)
        if len(who) != 1:
            log(f"sort: skip '{d.name}' (artists matched: {sorted(who) or 'none'})")
            continue
        artist = who.pop()
        dest = LEAKS / artist / d.name
        log(f"sort: '{d.name}' -> leaks/{artist}/")
        if dry:
            continue
        dest.mkdir(parents=True, exist_ok=True)
        for p in sorted(d.rglob("*")):  # merge file by file: slskd may add more later
            if p.is_file():
                target = dest / p.relative_to(d)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    p.unlink() if target.stat().st_size == p.stat().st_size else None
                    continue
                shutil.move(str(p), str(target))
        for sub in sorted((p for p in d.rglob("*") if p.is_dir()), reverse=True):
            if not any(sub.iterdir()):
                sub.rmdir()
        if not any(d.iterdir()):
            d.rmdir()


# ---------------------------------------------------------------- 2. tag
def album_name(artist, parts):
    if not parts:
        return f"{artist} – Unreleased"
    name = " – ".join(QUALITY_BRACKETS.sub("", p).strip(" -_") or p for p in parts)
    if not re.search(r"unreleased", name, re.I):
        name += " (Unreleased)"
    return name


def title_from_filename(path, artist):
    t = path.stem
    t = re.sub(r"^\s*(\d+[-.]?)?\d+\s*[-._)]*\s*", "", t)            # 01 / 1-03 / 01. / 01 -
    t = re.sub(rf"^\s*{re.escape(artist)}\s*[-–]\s*", "", t, flags=re.I)  # "Artist - "
    return t.replace("_", " ").strip() or path.stem


def tag_tree(dry):
    changed = 0
    for artist in ARTISTS:
        root = LEAKS / artist
        if not root.is_dir():
            continue
        for f in audio_files(root):
            tags = easy(f)
            if tags is None:
                continue
            if tags.tags is None:
                tags.add_tags()
            parts = list(f.relative_to(root).parent.parts)
            want = {
                "albumartist": artist,
                "album": album_name(artist, parts),
                "genre": "Unreleased",
            }
            cur_artist = first(tags, "artist")
            if not match_artists(cur_artist) or artist not in match_artists(cur_artist):
                want["artist"] = artist
            cur_title = first(tags, "title")
            if not cur_title or JUNK_TITLE.match(cur_title):
                want["title"] = title_from_filename(f, artist)
            diff = {k: v for k, v in want.items() if first(tags, k) != v}
            drop = [k for k in ("musicbrainz_albumid", "musicbrainz_releasegroupid", "compilation")
                    if k in tags]
            if not diff and not drop:
                continue
            changed += 1
            log(f"tag: {f.relative_to(LEAKS)}: {diff}{' drop ' + str(drop) if drop else ''}")
            if dry:
                continue
            for k, v in diff.items():
                tags[k] = v
            for k in drop:
                del tags[k]
            tags.save()
    log(f"tag: {changed} file(s) {'would change' if dry else 'updated'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    for artist in ARTISTS:
        (LEAKS / artist).mkdir(parents=True, exist_ok=True)
    sort_inbox(a.dry_run)
    tag_tree(a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
