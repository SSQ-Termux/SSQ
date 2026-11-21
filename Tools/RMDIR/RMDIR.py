#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSForceD - a safer, reversible file cleanup utility for Termux/Python.

Only regular files inside the user's home folder or Android shared storage are
eligible. Files are moved to a private quarantine first; this tool does not
bypass permissions, follow symlinks, or delete folders/system files.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable

APP_NAME = "SSForceD"
VERSION = "1.0.0"
HOME = Path.home().resolve()
APP_DIR = HOME / ".ssforced"
TRASH_DIR = APP_DIR / "quarantine"
INDEX_FILE = APP_DIR / "index.json"
MAX_SCAN_RESULTS = 3000

# Only these user-owned areas are considered. Missing roots are ignored.
ALLOWED_ROOTS = [HOME]
for candidate in (Path("/storage/emulated/0"), Path("/sdcard")):
    try:
        resolved = candidate.resolve()
        if resolved.exists() and resolved not in ALLOWED_ROOTS:
            ALLOWED_ROOTS.append(resolved)
    except OSError:
        pass

# These directories are not managed even if they are below shared storage.
PROTECTED_PARTS = {
    "Android/data", "Android/obb", ".ssforced", ".ssh", ".gnupg",
    ".termux", "proc", "sys", "dev", "system", "vendor", "metadata",
}

# ANSI terminal colors (works without third-party packages).
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"

CURRENT_DIR = HOME
LAST_RESULTS: list[Path] = []


def color(text: str, shade: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"{shade}{text}{RESET}"


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def path_is_protected(path: Path) -> bool:
    """Check path components without following a path supplied for deletion."""
    parts = [part.lower() for part in path.parts]
    joined = "/".join(parts)
    if any(part in {"proc", "sys", "dev", "system", "vendor", "metadata"} for part in parts):
        return True
    if "/android/data/" in f"/{joined}/" or "/android/obb/" in f"/{joined}/":
        return True
    if any(part in {".ssforced", ".ssh", ".gnupg", ".termux"} for part in parts):
        return True
    return False


def allowed_location(path: Path) -> bool:
    return any(is_inside(path, root) for root in ALLOWED_ROOTS)


def initialize_storage() -> None:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        if not INDEX_FILE.exists():
            save_index([])
    except OSError as exc:
        print(color(f"[!] Cannot initialize private storage: {exc}", RED))


def load_index() -> list[dict]:
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_index(records: list[dict]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temporary = INDEX_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(INDEX_FILE)


def resolve_user_directory(raw: str) -> Path | None:
    try:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = CURRENT_DIR / candidate
        # Do not allow a symlink as the selected directory.
        if candidate.is_symlink():
            print(color("[!] Symbolic-link directories are not supported.", RED))
            return None
        target = candidate.resolve(strict=True)
        if not target.is_dir() or not allowed_location(target) or path_is_protected(target):
            print(color("[!] Choose a normal folder inside Home or Android shared storage.", RED))
            return None
        return target
    except (OSError, RuntimeError) as exc:
        print(color(f"[!] Invalid folder: {exc}", RED))
        return None


def is_manageable_file(path: Path, base: Path) -> bool:
    try:
        # Do not follow links; only regular files are eligible.
        if path.is_symlink() or not path.is_file():
            return False
        parent = path.parent.resolve(strict=True)
        resolved = path.resolve(strict=True)
        return (
            is_inside(resolved, base)
            and allowed_location(resolved)
            and not path_is_protected(resolved)
            and not path_is_protected(parent)
        )
    except (OSError, RuntimeError):
        return False


def scan_files(base: Path, recursive: bool = False) -> list[Path]:
    found: list[Path] = []
    if not recursive:
        try:
            for item in base.iterdir():
                if len(found) >= MAX_SCAN_RESULTS:
                    break
                if is_manageable_file(item, base):
                    found.append(item)
        except OSError as exc:
            print(color(f"[!] Cannot read folder: {exc}", RED))
        return sorted(found, key=lambda p: p.name.casefold())

    def walk_error(exc: OSError) -> None:
        print(color(f"[!] Skipped an inaccessible folder: {exc}", YELLOW))

    try:
        for current, dirs, files in os.walk(base, topdown=True, followlinks=False, onerror=walk_error):
            current_path = Path(current)
            # Prune protected areas and symlink directories before descending.
            dirs[:] = [
                name for name in dirs
                if not (current_path / name).is_symlink()
                and not path_is_protected(current_path / name)
            ]
            for name in files:
                item = current_path / name
                if is_manageable_file(item, base):
                    found.append(item)
                    if len(found) >= MAX_SCAN_RESULTS:
                        print(color(f"[!] Scan capped at {MAX_SCAN_RESULTS} files.", YELLOW))
                        return sorted(found, key=lambda p: str(p).casefold())
    except OSError as exc:
        print(color(f"[!] Scan stopped: {exc}", RED))
    return sorted(found, key=lambda p: str(p).casefold())


def display_files(files: Iterable[Path], base: Path) -> None:
    global LAST_RESULTS
    LAST_RESULTS = list(files)
    if not LAST_RESULTS:
        print(color("No eligible files found.", YELLOW))
        return
    total = 0
    print(color("\n  ID  SIZE          FILE", CYAN))
    print(color("  ─── ────────────  ─────────────────────────────────────", DIM))
    for number, path in enumerate(LAST_RESULTS, 1):
        try:
            stat = path.stat()
            size = stat.st_size
            total += size
            try:
                shown = str(path.relative_to(base))
            except ValueError:
                shown = path.name
            print(f"  {number:>3} {human_size(size):<13} {shown}")
        except OSError:
            print(color(f"  {number:>3} {'<unavailable>':<13} {path.name}", YELLOW))
    print(color(f"\n  Files: {len(LAST_RESULTS)}    Total: {human_size(total)}", GREEN))


def parse_selection(raw: str, maximum: int) -> list[int]:
    selected: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            left, right = chunk.split("-", 1)
            start, end = int(left.strip()), int(right.strip())
            if start > end:
                start, end = end, start
            # Clamp before building the range so malformed huge input cannot
            # allocate an enormous set.
            start = max(1, start)
            end = min(maximum, end)
            if start <= end:
                selected.update(range(start, end + 1))
        else:
            selected.add(int(chunk))
    return sorted(i for i in selected if 1 <= i <= maximum)


def ask_selection(maximum: int) -> list[int]:
    if maximum == 0:
        return []
    raw = input("Select IDs (e.g. 1,3,5-8) or Enter to cancel: ").strip()
    if not raw:
        return []
    try:
        return parse_selection(raw, maximum)
    except ValueError:
        print(color("[!] Invalid selection format.", RED))
        return []


def quarantine_files(indices: list[int], base: Path) -> None:
    if not indices:
        print(color("Nothing selected.", YELLOW))
        return
    chosen = [LAST_RESULTS[i - 1] for i in indices if i - 1 < len(LAST_RESULTS)]
    valid = [p for p in chosen if is_manageable_file(p, base)]
    if not valid:
        print(color("[!] No eligible files in that selection.", RED))
        return

    print(color("\nFiles selected for reversible removal:", YELLOW))
    for path in valid:
        try:
            print(f"  • {path.name}  ({human_size(path.stat().st_size)})")
        except OSError:
            print(f"  • {path.name}")
    confirmation = input(color("Type MOVE to send these files to quarantine: ", MAGENTA)).strip()
    if confirmation != "MOVE":
        print("Cancelled. No files were changed.")
        return

    records = load_index()
    moved = 0
    for source in valid:
        # Re-check immediately before moving to reduce race-condition risk.
        if not is_manageable_file(source, base):
            print(color(f"[SKIP] No longer eligible: {source.name}", YELLOW))
            continue
        item_id = uuid.uuid4().hex
        destination = TRASH_DIR / f"{item_id}_{source.name}"
        try:
            size = source.stat().st_size
            shutil.move(str(source), str(destination))
            records.append({
                "id": item_id,
                "name": source.name,
                "original": str(source),
                "stored": str(destination),
                "size": size,
                "moved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            })
            moved += 1
            print(color(f"[MOVED] {source.name}", GREEN))
        except OSError as exc:
            print(color(f"[FAILED] {source.name}: {exc}", RED))
    save_index(records)
    print(color(f"\nDone: {moved} file(s) moved to quarantine. Use Restore to recover them.", GREEN))


def show_quarantine() -> list[dict]:
    records = load_index()
    print(color("\n  QUARANTINE", MAGENTA))
    if not records:
        print(color("  Quarantine is empty.", YELLOW))
        return records
    for number, record in enumerate(records, 1):
        print(f"  {number:>3}. {record.get('name', 'unknown')}  |  {human_size(int(record.get('size', 0)))}  |  {record.get('moved_at', '')}")
    print(color(f"\n  Items: {len(records)}", GREEN))
    return records


def restore_files() -> None:
    records = show_quarantine()
    if not records:
        return
    indices = ask_selection(len(records))
    if not indices:
        return
    updated = records[:]
    for index in indices:
        record = updated[index - 1]
        original = Path(record.get("original", ""))
        stored = Path(record.get("stored", ""))
        try:
            # Verify both paths: restore only to the recorded user-owned location.
            if not allowed_location(original) or path_is_protected(original):
                raise ValueError("original location is protected")
            if not original.parent.is_dir():
                print(color(f"[SKIP] Original folder no longer exists: {original.parent}", YELLOW))
                continue
            resolved_parent = original.parent.resolve(strict=True)
            if not allowed_location(resolved_parent) or path_is_protected(resolved_parent):
                raise ValueError("original parent is no longer a safe user folder")
            if not is_inside(stored.resolve(strict=True), TRASH_DIR.resolve(strict=True)):
                raise ValueError("quarantine path validation failed")
            if not stored.is_file() or stored.is_symlink():
                raise ValueError("quarantined file is missing or invalid")
            if original.exists():
                print(color(f"[SKIP] Destination already exists: {original}", YELLOW))
                continue
            if not original.parent.is_dir():
                print(color(f"[SKIP] Original folder no longer exists: {original.parent}", YELLOW))
                continue
            shutil.move(str(stored), str(original))
            updated.remove(record)
            print(color(f"[RESTORED] {original}", GREEN))
        except (OSError, ValueError) as exc:
            print(color(f"[FAILED] {record.get('name', 'file')}: {exc}", RED))
    save_index(updated)


def permanently_empty_quarantine() -> None:
    records = show_quarantine()
    if not records:
        return
    print(color("\nWARNING: this step permanently removes quarantined files.", RED))
    confirmation = input(color("Type PURGE permanently to continue: ", RED)).strip()
    if confirmation != "PURGE permanently":
        print("Cancelled. Quarantine was not changed.")
        return

    remaining = records[:]
    removed = 0
    trash_root = TRASH_DIR.resolve()
    for record in records:
        stored = Path(record.get("stored", ""))
        try:
            resolved = stored.resolve(strict=True)
            if not is_inside(resolved, trash_root) or stored.is_symlink() or not stored.is_file():
                print(color(f"[SKIP] Invalid quarantine entry: {record.get('name', 'unknown')}", YELLOW))
                continue
            stored.unlink()
            remaining.remove(record)
            removed += 1
            print(color(f"[PURGED] {record.get('name', 'file')}", GREEN))
        except FileNotFoundError:
            remaining.remove(record)
        except OSError as exc:
            print(color(f"[FAILED] {record.get('name', 'file')}: {exc}", RED))
    save_index(remaining)
    print(color(f"\nPermanently removed: {removed} file(s).", GREEN))


def choose_folder() -> None:
    global CURRENT_DIR, LAST_RESULTS
    print("Allowed locations:")
    for root in ALLOWED_ROOTS:
        print(f"  - {root}")
    raw = input(f"Folder path [current: {CURRENT_DIR}]: ").strip()
    if not raw:
        return
    target = resolve_user_directory(raw)
    if target:
        CURRENT_DIR = target
        LAST_RESULTS = []
        print(color(f"[OK] Current folder: {CURRENT_DIR}", GREEN))


def show_status() -> None:
    print(color("\n  SSForceD STATUS", CYAN))
    print(f"  Current folder : {CURRENT_DIR}")
    print(f"  Private storage: {APP_DIR}")
    print(f"  Allowed roots  : {len(ALLOWED_ROOTS)}")
    print(f"  Quarantined    : {len(load_index())} file(s)")
    print("  Mode           : reversible quarantine")


def banner() -> None:
    os.system("clear" if os.name != "nt" else "cls")
    art = r"""
   _____ _____ _____                 ____
  / ____/ ____/ ____|               |  _ \
 | (___| (___| |  ___  ___  _ __ ___| | | |
  \___ \\___ \| | |_ |/ _ \| '__/ __| | | |
  ____) |___) | |__| | (_) | | | (__| |_| |
 |_____/_____/ \_____|\___/|_|  \___|____/
"""
    print(color(art, CYAN))
    print(color(f"  {APP_NAME}  //  SAFE FILE CLEANER  //  v{VERSION}", BOLD))
    print(color("  Reversible first. No system-file force deletion.", DIM))
    print(color(f"  Location: {CURRENT_DIR}\n", DIM))


def main() -> None:
    global LAST_RESULTS
    initialize_storage()
    if not CURRENT_DIR.exists():
        print(color("[!] Home folder is unavailable.", RED))
        return
    while True:
        print(color("  [1] Change folder", CYAN))
        print(color("  [2] Browse files (current folder)", CYAN))
        print(color("  [3] Scan recursively", CYAN))
        print(color("  [4] Move selected files to quarantine", YELLOW))
        print(color("  [5] View quarantine", MAGENTA))
        print(color("  [6] Restore files", GREEN))
        print(color("  [7] Permanently empty quarantine", RED))
        print(color("  [8] Status / Help", CYAN))
        print(color("  [0] Exit", DIM))
        choice = input(color("\nSSForceD > ", BOLD)).strip()
        if choice == "1":
            choose_folder()
        elif choice == "2":
            LAST_RESULTS = scan_files(CURRENT_DIR, recursive=False)
            display_files(LAST_RESULTS, CURRENT_DIR)
        elif choice == "3":
            answer = input("Scan subfolders too? Type YES to confirm: ").strip()
            if answer == "YES":
                LAST_RESULTS = scan_files(CURRENT_DIR, recursive=True)
                display_files(LAST_RESULTS, CURRENT_DIR)
            else:
                print("Recursive scan cancelled.")
        elif choice == "4":
            if not LAST_RESULTS:
                print(color("Scan or browse files first.", YELLOW))
            else:
                selected = ask_selection(len(LAST_RESULTS))
                quarantine_files(selected, CURRENT_DIR)
        elif choice == "5":
            show_quarantine()
        elif choice == "6":
            restore_files()
        elif choice == "7":
            permanently_empty_quarantine()
        elif choice == "8":
            show_status()
            print("\n  Tips:")
            print("  • In Termux, run: termux-setup-storage")
            print("  • Use /storage/emulated/0 to browse shared storage.")
            print("  • Select files by ID: 1,3,5-8")
            print("  • Files first go to ~/.ssforced/quarantine.")
            print("  • Protected folders, symlinks and directories are skipped.")
            print("  • Permission errors are not bypassed.")
        elif choice == "0":
            print(color("SSForceD closed. Your quarantined files are preserved.", GREEN))
            break
        else:
            print(color("Unknown option. Choose 0-8.", RED))
        input(color("\nPress Enter to continue...", DIM))
        banner()


if __name__ == "__main__":
    try:
        banner()
        main()
    except KeyboardInterrupt:
        print("\n" + color("Interrupted. Quarantined files are preserved.", YELLOW))
