#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Browse My Files — a terminal file manager for Android / Termux and desktop Python.

No third-party packages are required.  The program uses only Python's standard
library and stores its preferences in ~/.browse_my_files.json.

Termux setup:
    termux-setup-storage
    python Browse_My_Files.py

Safety notes:
* Delete sends items to a private trash folder instead of removing them at once.
* Archive extraction checks destination paths to prevent ZIP path traversal.
* Recursive search skips directories it cannot read and never follows symlinks.
* File operations show errors rather than silently ignoring failures.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import stat
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

APP_NAME = "Browse My Files"
APP_VERSION = "1.0.0"
HOME = Path.home()
CONFIG_FILE = HOME / ".browse_my_files.json"
TRASH_DIR = HOME / ".browse_my_files_trash"
PREVIEW_LIMIT = 96 * 1024
SEARCH_LIMIT = 10000

# ANSI styling is deliberately optional: set NO_COLOR=1 to disable it.
USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ

class C:
    RESET = "\033[0m" if USE_COLOR else ""
    BOLD = "\033[1m" if USE_COLOR else ""
    DIM = "\033[2m" if USE_COLOR else ""
    RED = "\033[91m" if USE_COLOR else ""
    GREEN = "\033[92m" if USE_COLOR else ""
    YELLOW = "\033[93m" if USE_COLOR else ""
    BLUE = "\033[94m" if USE_COLOR else ""
    MAGENTA = "\033[95m" if USE_COLOR else ""
    CYAN = "\033[96m" if USE_COLOR else ""
    WHITE = "\033[97m" if USE_COLOR else ""


def paint(text: object, color: str = "") -> str:
    return f"{color}{text}{C.RESET}"


def clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def pause(message: str = "برای ادامه Enter بزنید...") -> None:
    try:
        input("\n" + paint(message, C.DIM))
    except (EOFError, KeyboardInterrupt):
        pass


def human_size(value: int) -> str:
    amount = float(max(0, value))
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{amount:.2f} PB"


def human_time(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "نامشخص"


def safe_input(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def is_inside(child: Path, parent: Path) -> bool:
    """Return True when child resolves inside parent (including parent itself)."""
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def load_config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}


def save_config(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CONFIG_FILE)


def default_start() -> Path:
    android_shared = Path("/storage/emulated/0")
    if android_shared.is_dir() and os.access(android_shared, os.R_OK):
        return android_shared
    return HOME


def entry_icon(path: Path) -> str:
    if path.is_symlink():
        return "🔗"
    if path.is_dir():
        return "📁"
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".svg"}:
        return "🖼️"
    if suffix in {".mp4", ".mkv", ".avi", ".mov", ".webm", ".3gp"}:
        return "🎬"
    if suffix in {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}:
        return "🎵"
    if suffix in {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz"}:
        return "📦"
    if suffix in {".py", ".js", ".java", ".kt", ".c", ".cpp", ".html", ".css", ".sh"}:
        return "💻"
    if suffix in {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt"}:
        return "📄"
    if suffix in {".apk", ".xapk", ".apks"}:
        return "📱"
    return "📄"


def file_type(path: Path) -> str:
    if path.is_symlink():
        return "پیوند نمادین"
    if path.is_dir():
        return "پوشه"
    mime, _ = mimetypes.guess_type(str(path))
    return mime or (path.suffix[1:].upper() if path.suffix else "فایل")


def directory_size(path: Path) -> int:
    total = 0
    try:
        for root, dirs, files in os.walk(path, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
            for name in files:
                item = Path(root) / name
                try:
                    if not item.is_symlink():
                        total += item.stat().st_size
                except OSError:
                    continue
    except OSError:
        pass
    return total


def path_size(path: Path) -> int:
    try:
        if path.is_symlink():
            return len(os.readlink(path))
        return directory_size(path) if path.is_dir() else path.stat().st_size
    except OSError:
        return 0


def format_permissions(mode: int) -> str:
    return stat.filemode(mode)


class BrowseMyFiles:
    def __init__(self) -> None:
        self.config = load_config()
        saved = self.config.get("last_path")
        candidate = Path(saved).expanduser() if isinstance(saved, str) else default_start()
        self.current = candidate if candidate.is_dir() else default_start()
        self.show_hidden = bool(self.config.get("show_hidden", False))
        self.sort_by = str(self.config.get("sort_by", "name"))
        self.reverse = bool(self.config.get("reverse", False))
        self.bookmarks = self._valid_bookmarks(self.config.get("bookmarks", []))
        self.history: list[Path] = []
        self.running = True

    @staticmethod
    def _valid_bookmarks(raw: object) -> list[str]:
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if isinstance(item, str) and Path(item).expanduser().is_dir() and item not in result:
                result.append(item)
        return result[:100]

    def persist(self) -> None:
        self.config.update({
            "last_path": str(self.current),
            "show_hidden": self.show_hidden,
            "sort_by": self.sort_by,
            "reverse": self.reverse,
            "bookmarks": self.bookmarks,
        })
        try:
            save_config(self.config)
        except OSError as exc:
            print(paint(f"ذخیره تنظیمات ناموفق بود: {exc}", C.RED))

    def header(self, subtitle: str = "مدیریت فایل هوشمند") -> None:
        clear_screen()
        width = min(max(shutil.get_terminal_size((78, 20)).columns, 42), 100)
        line = "━" * width
        print(paint(line, C.CYAN))
        print(paint(f"  ✦ {APP_NAME}  ✦  نسخه {APP_VERSION}", C.BOLD + C.CYAN))
        print(paint(f"  {subtitle}", C.DIM))
        print(paint(line, C.CYAN))

    def list_entries(self) -> list[Path]:
        try:
            entries = list(self.current.iterdir())
        except PermissionError:
            print(paint("دسترسی به این پوشه وجود ندارد.", C.RED))
            return []
        except OSError as exc:
            print(paint(f"خطا در خواندن پوشه: {exc}", C.RED))
            return []
        if not self.show_hidden:
            entries = [p for p in entries if not p.name.startswith(".")]
        if self.sort_by == "size":
            key = lambda p: (not p.is_dir(), path_size(p), p.name.casefold())
        elif self.sort_by == "date":
            key = lambda p: (not p.is_dir(), self._mtime(p), p.name.casefold())
        elif self.sort_by == "type":
            key = lambda p: (not p.is_dir(), file_type(p).casefold(), p.name.casefold())
        else:
            key = lambda p: (not p.is_dir(), p.name.casefold())
        try:
            return sorted(entries, key=key, reverse=self.reverse)
        except OSError:
            return sorted(entries, key=lambda p: p.name.casefold())

    @staticmethod
    def _mtime(path: Path) -> float:
        try:
            return path.lstat().st_mtime
        except OSError:
            return 0

    def draw(self, entries: list[Path]) -> None:
        self.header("مدیریت و مرور فایل‌ها")
        print(paint(f"📍 مسیر: {self.current}", C.YELLOW))
        print(paint(f"مرتب‌سازی: {self.sort_by} | مخفی‌ها: {'نمایش' if self.show_hidden else 'پنهان'} | تعداد: {len(entries)}", C.DIM))
        print(paint("─" * min(max(shutil.get_terminal_size((78, 20)).columns, 42), 100), C.DIM))
        if not entries:
            print(paint("این پوشه خالی است یا قابل خواندن نیست.", C.DIM))
        else:
            max_rows = max(6, min(24, shutil.get_terminal_size((78, 20)).lines - 13))
            for index, item in enumerate(entries[:max_rows], 1):
                try:
                    size = "پوشه" if item.is_dir() else human_size(item.stat().st_size)
                except OSError:
                    size = "نامشخص"
                name = item.name + ("/" if item.is_dir() else "")
                if len(name) > 40:
                    name = name[:37] + "..."
                color = C.BLUE if item.is_dir() else C.WHITE
                print(f"{paint(f'{index:>2}.', C.DIM)} {entry_icon(item)} {paint(name, color):<50} {paint(size, C.DIM)}")
            if len(entries) > max_rows:
                print(paint(f"... و {len(entries) - max_rows} مورد دیگر. برای جست‌وجو از گزینه جست‌وجو استفاده کن.", C.DIM))
        print(paint("─" * min(max(shutil.get_terminal_size((78, 20)).columns, 42), 100), C.DIM))
        print("[شماره] باز/انتخاب | [..] پوشه بالاتر | [m] منو | [q] خروج")

    def run(self) -> None:
        try:
            while self.running:
                entries = self.list_entries()
                self.draw(entries)
                choice = safe_input(paint("Browse > ", C.GREEN)).lower()
                if choice in {"q", "quit", "exit"}:
                    self.running = False
                elif choice in {"..", "up", "back"}:
                    self.go_up()
                elif choice in {"m", "menu"}:
                    self.menu()
                elif choice.isdigit():
                    number = int(choice)
                    if 1 <= number <= len(entries):
                        self.open_entry(entries[number - 1])
                    else:
                        pause("شماره معتبر نیست. Enter بزنید...")
                elif choice:
                    pause("ورودی شناخته نشد. Enter بزنید...")
        except KeyboardInterrupt:
            self.running = False
        finally:
            self.persist()
            clear_screen()
            print(paint("Browse My Files بسته شد. خداحافظ!", C.CYAN))

    def change_dir(self, target: Path) -> bool:
        try:
            target = target.expanduser().resolve(strict=True)
            if not target.is_dir():
                print(paint("مسیر انتخاب‌شده پوشه نیست.", C.RED))
                return False
            if not os.access(target, os.R_OK | os.X_OK):
                print(paint("مجوز خواندن/ورود به این پوشه وجود ندارد.", C.RED))
                return False
            self.history.append(self.current)
            self.current = target
            self.persist()
            return True
        except (OSError, RuntimeError) as exc:
            print(paint(f"باز کردن مسیر ناموفق بود: {exc}", C.RED))
            return False

    def go_up(self) -> None:
        parent = self.current.parent
        if parent != self.current:
            self.change_dir(parent)

    def open_entry(self, path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            self.change_dir(path)
        else:
            self.entry_menu(path)

    def menu(self) -> None:
        while True:
            self.header("منوی ابزارها")
            options = [
                ("1", "جست‌وجوی نام فایل/پوشه"),
                ("2", "ساخت پوشه جدید"),
                ("3", "ساخت فایل متنی"),
                ("4", "مدیریت نشانک‌ها"),
                ("5", "تغییر روش مرتب‌سازی"),
                ("6", "نمایش/مخفی‌کردن فایل‌های مخفی"),
                ("7", "اطلاعات حافظه دستگاه"),
                ("8", "مدیریت سطل زباله"),
                ("9", "فشرده‌سازی پوشه/فایل ZIP"),
                ("10", "استخراج فایل ZIP"),
                ("11", "رفتن به مسیر دلخواه"),
                ("12", "بازخوانی و بازگشت"),
            ]
            for key, label in options:
                print(f" {paint(key, C.GREEN):>4}  {label}")
            print("  q   بازگشت")
            choice = safe_input("انتخاب: ").lower()
            actions = {
                "1": self.search, "2": self.create_folder, "3": self.create_text_file,
                "4": self.bookmark_menu, "5": self.change_sort, "6": self.toggle_hidden,
                "7": self.storage_info, "8": self.trash_menu, "9": self.create_zip,
                "10": self.extract_zip, "11": self.go_to_path,
            }
            if choice in {"q", "", "12"}:
                return
            action = actions.get(choice)
            if action:
                action()
            else:
                pause("گزینه معتبر نیست.")

    def entry_menu(self, path: Path) -> None:
        while True:
            self.header("عملیات روی مورد انتخاب‌شده")
            print(f"{entry_icon(path)} {path.name}")
            print("1) پیش‌نمایش متن     2) اطلاعات کامل")
            print("3) کپی               4) انتقال")
            print("5) تغییر نام         6) انتقال به سطل زباله")
            print("7) بازکردن با برنامه اندروید/سیستم")
            print("8) محاسبه SHA-256    9) ساخت ZIP از این مورد")
            print("q) بازگشت")
            choice = safe_input("عملیات: ").lower()
            if choice == "1": self.preview(path)
            elif choice == "2": self.properties(path)
            elif choice == "3": self.copy_item(path)
            elif choice == "4": self.move_item(path)
            elif choice == "5": self.rename_item(path)
            elif choice == "6": self.trash_item(path)
            elif choice == "7": self.open_external(path)
            elif choice == "8": self.hash_file(path)
            elif choice == "9": self.zip_selected(path)
            elif choice in {"q", ""}: return
            else: pause("گزینه معتبر نیست.")
            if not path.exists() and not path.is_symlink():
                return

    def preview(self, path: Path) -> None:
        self.header("پیش‌نمایش فایل")
        if path.is_dir():
            pause("پیش‌نمایش مستقیم پوشه ممکن نیست.")
            return
        try:
            if path.stat().st_size > PREVIEW_LIMIT:
                print(paint(f"فایل بزرگ است؛ فقط {human_size(PREVIEW_LIMIT)} اول نمایش داده می‌شود.", C.YELLOW))
            data = path.open("rb").read(PREVIEW_LIMIT)
            text = data.decode("utf-8", errors="replace")
            print("\n" + "─" * 50)
            print(text[:12000])
            if len(text) > 12000:
                print("\n... ادامه محتوا برای جلوگیری از شلوغی نمایش داده نشد.")
        except OSError as exc:
            print(paint(f"خواندن فایل ناموفق بود: {exc}", C.RED))
        pause()

    def properties(self, path: Path) -> None:
        self.header("اطلاعات فایل")
        try:
            info = path.lstat()
            print(f"نام: {path.name}")
            print(f"مسیر: {path}")
            print(f"نوع: {file_type(path)}")
            print(f"حجم: {human_size(path_size(path))}")
            print(f"اندازه خام: {info.st_size:,} bytes")
            print(f"آخرین تغییر: {human_time(info.st_mtime)}")
            print(f"ایجاد (در صورت پشتیبانی سیستم): {human_time(info.st_ctime)}")
            print(f"دسترسی‌ها: {format_permissions(info.st_mode)}")
            print(f"مالک UID: {info.st_uid} | گروه GID: {info.st_gid}")
            print(f"مخفی: {'بله' if path.name.startswith('.') else 'خیر'}")
            print(f"پیوند نمادین: {'بله' if path.is_symlink() else 'خیر'}")
            if path.is_symlink():
                print(f"مقصد پیوند: {os.readlink(path)}")
            if path.is_dir():
                print("محاسبه اندازه پوشه ممکن است کمی زمان ببرد...")
                print(f"حجم کل محتویات: {human_size(directory_size(path))}")
        except OSError as exc:
            print(paint(f"خطا: {exc}", C.RED))
        pause()

    def ask_destination(self, action: str) -> Optional[Path]:
        raw = safe_input(f"مسیر مقصد برای {action} (خالی = پوشه فعلی): ")
        target = Path(raw).expanduser() if raw else self.current
        try:
            target = target.resolve(strict=True)
            if not target.is_dir() or not os.access(target, os.W_OK | os.X_OK):
                raise PermissionError("مقصد پوشه قابل نوشتن نیست")
            return target
        except (OSError, RuntimeError) as exc:
            print(paint(f"مقصد معتبر نیست: {exc}", C.RED))
            return None

    @staticmethod
    def conflict_target(target: Path) -> Path:
        if not target.exists() and not target.is_symlink():
            return target
        stem, suffix = target.stem, target.suffix
        for number in range(1, 10000):
            candidate = target.with_name(f"{stem} ({number}){suffix}")
            if not candidate.exists() and not candidate.is_symlink():
                return candidate
        raise FileExistsError("نام جایگزین آزاد پیدا نشد")

    def copy_item(self, source: Path) -> None:
        destination = self.ask_destination("کپی")
        if destination is None: return
        try:
            if source.is_dir() and not source.is_symlink() and is_inside(destination, source):
                raise ValueError("نمی‌توان پوشه را داخل خودش کپی کرد")
            target = self.conflict_target(destination / source.name)
            if source.is_symlink():
                os.symlink(os.readlink(source), target)
            elif source.is_dir():
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target)
            pause(f"کپی انجام شد: {target}")
        except (OSError, shutil.Error, ValueError) as exc:
            pause(f"کپی ناموفق بود: {exc}")

    def move_item(self, source: Path) -> None:
        destination = self.ask_destination("انتقال")
        if destination is None: return
        try:
            if source.is_dir() and not source.is_symlink() and is_inside(destination, source):
                raise ValueError("نمی‌توان پوشه را داخل خودش منتقل کرد")
            target = self.conflict_target(destination / source.name)
            shutil.move(str(source), str(target))
            pause(f"انتقال انجام شد: {target}")
        except (OSError, shutil.Error, ValueError) as exc:
            pause(f"انتقال ناموفق بود: {exc}")

    def rename_item(self, source: Path) -> None:
        new_name = safe_input("نام جدید (بدون مسیر): ")
        if not new_name or new_name in {".", ".."} or "/" in new_name or "\\" in new_name:
            pause("نام واردشده معتبر نیست.")
            return
        target = source.with_name(new_name)
        if target.exists() or target.is_symlink():
            pause("موردی با این نام وجود دارد.")
            return
        try:
            source.rename(target)
            pause("نام با موفقیت تغییر کرد.")
        except OSError as exc:
            pause(f"تغییر نام ناموفق بود: {exc}")

    def ensure_trash(self) -> Path:
        TRASH_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        return TRASH_DIR

    def trash_item(self, source: Path) -> None:
        answer = safe_input(f"'{source.name}' به سطل زباله منتقل شود؟ (y/N): ").lower()
        if answer != "y": return
        try:
            trash = self.ensure_trash()
            target = self.conflict_target(trash / source.name)
            shutil.move(str(source), str(target))
            metadata = trash / (target.name + ".trashinfo")
            metadata.write_text(json.dumps({"original": str(source), "deleted": time.time()}, ensure_ascii=False), encoding="utf-8")
            pause("به سطل زباله منتقل شد؛ هنوز برای همیشه پاک نشده است.")
        except OSError as exc:
            pause(f"انتقال به سطل زباله ناموفق بود: {exc}")

    def trash_menu(self) -> None:
        trash = self.ensure_trash()
        while True:
            self.header("سطل زباله")
            items = [p for p in trash.iterdir() if not p.name.endswith(".trashinfo")]
            if not items:
                print("سطل زباله خالی است.")
                pause(); return
            for i, item in enumerate(items, 1):
                print(f"{i}) {entry_icon(item)} {item.name}  ({human_size(path_size(item))})")
            print("r) بازیابی مورد | e) خالی‌کردن کامل | q) بازگشت")
            choice = safe_input("انتخاب: ").lower()
            if choice == "q": return
            if choice == "e":
                if safe_input("تمام محتویات برای همیشه حذف شوند؟ تایپ کن EMPTY: ") == "EMPTY":
                    for item in items:
                        self._permanent_remove(item)
                        info = trash / (item.name + ".trashinfo")
                        try: info.unlink(missing_ok=True)
                        except OSError: pass
                    pause("سطل زباله خالی شد.")
                continue
            if choice == "r":
                number = safe_input("شماره مورد برای بازیابی: ")
                if number.isdigit() and 1 <= int(number) <= len(items):
                    item = items[int(number) - 1]
                    info_path = trash / (item.name + ".trashinfo")
                    original = self.current / item.name
                    try:
                        if info_path.exists():
                            data = json.loads(info_path.read_text(encoding="utf-8"))
                            original = Path(data.get("original", str(original))).expanduser()
                        original.parent.mkdir(parents=True, exist_ok=True)
                        restored = self.conflict_target(original)
                        shutil.move(str(item), str(restored))
                        info_path.unlink(missing_ok=True)
                        pause(f"بازیابی شد: {restored}")
                    except (OSError, ValueError, json.JSONDecodeError) as exc:
                        pause(f"بازیابی ناموفق بود: {exc}")

    @staticmethod
    def _permanent_remove(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)

    def create_folder(self) -> None:
        name = safe_input("نام پوشه جدید: ")
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            pause("نام پوشه معتبر نیست."); return
        try:
            (self.current / name).mkdir()
            pause("پوشه ساخته شد.")
        except OSError as exc:
            pause(f"ساخت پوشه ناموفق بود: {exc}")

    def create_text_file(self) -> None:
        name = safe_input("نام فایل (مثلاً note.txt): ")
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            pause("نام فایل معتبر نیست."); return
        path = self.current / name
        if path.exists():
            pause("این نام از قبل وجود دارد."); return
        print("متن را بنویس. برای پایان، یک خط فقط شامل .SAVE وارد کن:")
        lines = []
        while True:
            try: line = input()
            except (EOFError, KeyboardInterrupt): break
            if line == ".SAVE": break
            lines.append(line)
        try:
            path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            pause("فایل ساخته شد.")
        except OSError as exc:
            pause(f"ساخت فایل ناموفق بود: {exc}")

    def search(self) -> None:
        query = safe_input("عبارت جست‌وجو در نام: ").casefold()
        if not query: return
        include_subfolders = safe_input("زیرپوشه‌ها هم جست‌وجو شوند؟ (Y/n): ").lower() != "n"
        self.header("نتایج جست‌وجو")
        found = 0
        walked = 0
        if include_subfolders:
            walker: Iterable[tuple[str, list[str], list[str]]] = os.walk(self.current, followlinks=False)
        else:
            try:
                names = list(os.scandir(self.current))
            except OSError as exc:
                pause(f"خطا: {exc}"); return
            walker = [(str(self.current), [], [e.name for e in names])]
        for root, dirs, files in walker:
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
            all_names = dirs + files
            for name in all_names:
                walked += 1
                if query in name.casefold():
                    print(f"{entry_icon(Path(root) / name)} {Path(root) / name}")
                    found += 1
                    if found >= 300: break
                if walked >= SEARCH_LIMIT: break
            if found >= 300 or walked >= SEARCH_LIMIT: break
        print(paint(f"\n{found} نتیجه | {walked} مورد بررسی‌شده", C.GREEN))
        if walked >= SEARCH_LIMIT: print(paint("محدودیت ایمنی جست‌وجو رسید؛ نتایج ممکن است کامل نباشند.", C.YELLOW))
        pause()

    def change_sort(self) -> None:
        self.header("مرتب‌سازی")
        print("1) نام   2) حجم   3) تاریخ تغییر   4) نوع")
        choice = safe_input("انتخاب: ")
        self.sort_by = {"1": "name", "2": "size", "3": "date", "4": "type"}.get(choice, self.sort_by)
        if safe_input("ترتیب معکوس؟ (y/N): ").lower() == "y": self.reverse = True
        else: self.reverse = False
        self.persist()

    def toggle_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        self.persist()
        pause(f"نمایش فایل‌های مخفی: {'روشن' if self.show_hidden else 'خاموش'}")

    def storage_info(self) -> None:
        self.header("وضعیت حافظه")
        locations = [self.current]
        shared = Path("/storage/emulated/0")
        if shared.exists() and shared not in locations: locations.append(shared)
        if HOME not in locations: locations.append(HOME)
        for location in locations:
            try:
                usage = shutil.disk_usage(location)
                used_percent = (usage.used / usage.total * 100) if usage.total else 0
                print(f"\n📍 {location}")
                print(f"کل: {human_size(usage.total)} | استفاده‌شده: {human_size(usage.used)} | آزاد: {human_size(usage.free)}")
                bar_width = 28
                filled = int(bar_width * used_percent / 100)
                print("[" + "█" * filled + "░" * (bar_width - filled) + f"] {used_percent:.1f}%")
            except OSError as exc:
                print(f"{location}: {exc}")
        pause()

    def bookmark_menu(self) -> None:
        while True:
            self.header("نشانک‌های پوشه")
            for i, item in enumerate(self.bookmarks, 1): print(f"{i}) {item}")
            print("a) افزودن پوشه فعلی | d) حذف نشانک | q) بازگشت")
            choice = safe_input("انتخاب: ").lower()
            if choice == "q": return
            if choice == "a":
                value = str(self.current)
                if value not in self.bookmarks: self.bookmarks.append(value)
                self.persist(); pause("به نشانک‌ها اضافه شد.")
            elif choice == "d":
                n = safe_input("شماره نشانک: ")
                if n.isdigit() and 1 <= int(n) <= len(self.bookmarks):
                    removed = self.bookmarks.pop(int(n) - 1); self.persist()
                    pause(f"حذف شد: {removed}")
            elif choice.isdigit() and 1 <= int(choice) <= len(self.bookmarks):
                self.change_dir(Path(self.bookmarks[int(choice) - 1])); return

    def go_to_path(self) -> None:
        raw = safe_input("مسیر کامل پوشه: ")
        if raw: self.change_dir(Path(raw).expanduser())

    def open_external(self, path: Path) -> None:
        command = shutil.which("termux-open") or shutil.which("xdg-open")
        if not command:
            pause("برنامه termux-open یا xdg-open پیدا نشد. در Termux می‌توانی termux-api را نصب کنی.")
            return
        try:
            import subprocess
            subprocess.Popen([command, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pause("درخواست بازکردن به سیستم ارسال شد.")
        except OSError as exc:
            pause(f"بازکردن ناموفق بود: {exc}")

    def hash_file(self, path: Path) -> None:
        if not path.is_file() or path.is_symlink():
            pause("محاسبه SHA-256 فقط برای فایل معمولی انجام می‌شود."); return
        try:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            print(f"SHA-256: {digest.hexdigest()}")
        except OSError as exc:
            print(paint(f"خطا: {exc}", C.RED))
        pause()

    def create_zip(self) -> None:
        raw = safe_input("نام فایل ZIP (مثلاً backup.zip): ")
        if not raw: return
        target = Path(raw).expanduser()
        if not target.is_absolute(): target = self.current / target
        if target.suffix.lower() != ".zip": target = target.with_suffix(".zip")
        if target.exists():
            pause("فایل مقصد از قبل وجود دارد."); return
        try:
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for item in self.current.iterdir():
                    if item == target or item.is_symlink(): continue
                    if item.is_dir():
                        for root, dirs, files in os.walk(item, followlinks=False):
                            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
                            for name in files:
                                p = Path(root) / name
                                if not p.is_symlink(): archive.write(p, p.relative_to(self.current))
                    else:
                        archive.write(item, item.relative_to(self.current))
            pause(f"ZIP ساخته شد: {target}")
        except (OSError, zipfile.BadZipFile, ValueError) as exc:
            try: target.unlink(missing_ok=True)
            except OSError: pass
            pause(f"فشرده‌سازی ناموفق بود: {exc}")

    def zip_selected(self, source: Path) -> None:
        if source.is_symlink():
            pause("فشرده‌سازی پیوند نمادین پشتیبانی نمی‌شود."); return
        target = source.with_name(source.name + ".zip")
        if target.exists(): target = self.conflict_target(target)
        try:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                if source.is_dir():
                    for root, dirs, files in os.walk(source, followlinks=False):
                        dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
                        for name in files:
                            p = Path(root) / name
                            if not p.is_symlink(): archive.write(p, p.relative_to(source.parent))
                else:
                    archive.write(source, source.name)
            pause(f"آرشیو ساخته شد: {target}")
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            try: target.unlink(missing_ok=True)
            except OSError: pass
            pause(f"خطا: {exc}")

    def extract_zip(self) -> None:
        archives = [p for p in self.current.iterdir() if p.is_file() and p.suffix.lower() == ".zip"]
        self.header("استخراج ZIP")
        if not archives:
            pause("فایل ZIP در این پوشه پیدا نشد."); return
        for i, archive in enumerate(archives, 1): print(f"{i}) {archive.name}")
        choice = safe_input("شماره آرشیو: ")
        if not choice.isdigit() or not 1 <= int(choice) <= len(archives): return
        archive = archives[int(choice) - 1]
        raw = safe_input("پوشه مقصد (خالی = همین‌جا): ")
        destination = Path(raw).expanduser() if raw else self.current
        try:
            destination.mkdir(parents=True, exist_ok=True)
            destination = destination.resolve(strict=True)
            with zipfile.ZipFile(archive, "r") as zf:
                members = zf.infolist()
                total = sum(max(0, member.file_size) for member in members)
                if len(members) > 20000 or total > 10 * 1024**3:
                    raise ValueError("آرشیو بیش از محدودیت ایمنی (۲۰٬۰۰۰ فایل یا ۱۰ گیگابایت) است")
                for member in members:
                    # Reject absolute paths, parent traversal and Windows drive paths.
                    member_name = member.filename.replace("\\", "/")
                    parts = Path(member_name).parts
                    if member_name.startswith("/") or any(part == ".." for part in parts) or (parts and ":" in parts[0]):
                        raise ValueError(f"مسیر ناامن در ZIP: {member.filename}")
                    out = (destination / member_name).resolve(strict=False)
                    if not is_inside(out, destination):
                        raise ValueError(f"مسیر خارج از مقصد: {member.filename}")
                zf.extractall(destination)
            pause(f"استخراج انجام شد: {destination}")
        except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as exc:
            pause(f"استخراج ناموفق بود: {exc}")


def main() -> int:
    app = BrowseMyFiles()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
