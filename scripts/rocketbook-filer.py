#!/usr/bin/env python3
# /usr/local/bin/rocketbook-filer.py
# Moves Rocketbook notes out of the vault's inbox into "<class>/Lecture <n>/".
# A note is filed when its front matter has `class` (an existing top-level folder of the
# vault) and `lecture` (like 3 or 3a). n8n sets both from a Smart Title code; they can also
# be added by hand. The note's embedded scans move with it. Run by rocketbook-filer.path.
import re
import shutil
import sys
import time
from pathlib import Path

VAULT = Path("/mnt/storage/obsidian-livesync/vault")
INBOX = VAULT / "Rocketbook Inbox"
SCANS = INBOX / "scans"
LECTURE = re.compile(r"^(\d{1,2})([ab]?)$")


def front_matter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    fields = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and not line.startswith(" "):
            fields[k.strip()] = v.strip().strip('"').strip("'")
    return fields


def free_path(path):
    n = 2
    while path.exists():
        path = path.with_name(f"{path.stem} {n}{path.suffix}")
        n += 1
    return path


def file_note(note):
    fm = front_matter(note.read_text(encoding="utf-8"))
    cls, lecture = fm.get("class", ""), fm.get("lecture", "").lower()
    m = LECTURE.match(lecture)
    class_dir = VAULT / cls
    # Only existing class folders; never a path outside the vault.
    if not (cls and m and "/" not in cls and not cls.startswith(".") and class_dir.is_dir()):
        return False
    dest = class_dir / f"Lecture {int(m.group(1))}"
    dest.mkdir(exist_ok=True)
    for embed in re.findall(r"!\[\[([^\]|#]+)", note.read_text(encoding="utf-8")):
        for src in (SCANS / embed, INBOX / embed):
            if src.is_file():
                shutil.move(src, free_path(dest / src.name))
                break
    target = free_path(dest / note.name)
    shutil.move(note, target)
    print(f"filed {note.name} -> {target.relative_to(VAULT)}")
    return True


def main():
    time.sleep(2)  # let n8n finish writing every file of the batch
    for note in sorted(INBOX.glob("*.md")):
        try:
            file_note(note)
        except Exception as e:  # leave the note in the inbox and carry on
            print(f"skipped {note.name}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
