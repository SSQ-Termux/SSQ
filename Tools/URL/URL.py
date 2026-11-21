#!/usr/bin/env python3
# SSurl - Smart URL Opener
# Python 3 | Standard library only

import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from urllib.parse import urlparse, quote_plus

APP_NAME = "SSurl"
VERSION = "2.0"
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ssurl_history.json")
MAX_HISTORY = 100

# ANSI colors (works in most Termux terminals)
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
DIM = "\033[2m"


def color(text, shade=CYAN):
    return f"{shade}{text}{RESET}"


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def pause():
    input(f"\n{DIM}Press Enter to continue...{RESET}")


def load_history():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as file:
            json.dump(history[-MAX_HISTORY:], file, ensure_ascii=False, indent=2)
    except OSError as error:
        print(color(f"Could not save history: {error}", RED))


def normalize_url(value):
    """Add https:// when the user enters a domain without a scheme."""
    value = value.strip()
    if not value:
        return ""
    if any(ch.isspace() for ch in value):
        return ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value
    return value


def validate_url(value):
    url = normalize_url(value)
    if not url:
        return False, "", "URL is empty or contains spaces."

    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False, url, "Only HTTP and HTTPS links are supported."
        if not parsed.hostname:
            return False, url, "A valid domain or IP address is required."
        # Accessing .port also detects malformed port numbers.
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            return False, url, "Port must be between 1 and 65535."
        if parsed.username or parsed.password:
            return False, url, "Links containing embedded usernames/passwords are not accepted."
        return True, url, "Valid URL."
    except ValueError:
        return False, url, "Malformed URL or port."


def open_url(url):
    """Use Android's termux-open when available, otherwise system browser."""
    if shutil.which("termux-open"):
        try:
            result = subprocess.run(
                ["termux-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=12
            )
            if result.returncode == 0:
                return True, "Sent to Android's default browser."
            detail = result.stderr.strip() or "termux-open returned an error."
            return False, detail
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, str(error)

    try:
        opened = webbrowser.open(url, new=2)
        if opened:
            return True, "Open request sent to the default browser."
        return False, "No default browser handler was found."
    except Exception as error:
        return False, str(error)


def add_history(history, url, status):
    history.append({
        "url": url,
        "status": status,
        "time": time.strftime("%Y-%m-%d %H:%M:%S")
    })
    save_history(history)


def header():
    print(color(r"""
  ███████╗███████╗██╗   ██╗██████╗ ██╗
  ██╔════╝██╔════╝██║   ██║██╔══██╗██║
  ███████╗███████╗██║   ██║██████╔╝██║
  ╚════██║╚════██║██║   ██║██╔══██╗██║
  ███████║███████║╚██████╔╝██║  ██║██║
  ╚══════╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝
""", CYAN))
    print(color(f"          SMART URL OPENER  v{VERSION}", BOLD + MAGENTA))
    print(color("  Safe URL validation | Browser launcher | History", DIM))
    print(color("  " + "─" * 49, CYAN))


def ask_and_open(history):
    raw = input(color("\nSSurl / URL > ", GREEN))
    valid, url, message = validate_url(raw)
    if not valid:
        print(color(f"[!] {message}", RED))
        return
    print(color(f"[VALID] {url}", GREEN))
    confirm = input(color("Open this link? [Y/n]: ", YELLOW)).strip().lower()
    if confirm not in ("", "y", "yes"):
        print(color("Cancelled.", YELLOW))
        return
    ok, result = open_url(url)
    if ok:
        print(color(f"[OK] {result}", GREEN))
        add_history(history, url, "opened")
    else:
        print(color(f"[ERROR] {result}", RED))
        add_history(history, url, "failed")


def multiple_open(history):
    print(color("\nEnter URLs separated by commas.", YELLOW))
    raw = input(color("URLs > ", GREEN))
    items = [item.strip() for item in raw.split(",") if item.strip()]
    if not items:
        print(color("No URLs entered.", RED))
        return

    valid_items = []
    for item in items:
        valid, url, message = validate_url(item)
        if valid:
            valid_items.append(url)
        else:
            print(color(f"[SKIP] {item} - {message}", RED))

    if not valid_items:
        print(color("No valid URLs to open.", RED))
        return

    print(color(f"\n{len(valid_items)} valid URL(s) found.", GREEN))
    confirm = input(color("Open all? [y/N]: ", YELLOW)).strip().lower()
    if confirm not in ("y", "yes"):
        print(color("Cancelled.", YELLOW))
        return

    for number, url in enumerate(valid_items, 1):
        ok, result = open_url(url)
        status = "opened" if ok else "failed"
        add_history(history, url, status)
        label = "OK" if ok else "ERROR"
        shade = GREEN if ok else RED
        print(color(f"[{label}] {number}. {url} - {result}", shade))
        time.sleep(0.25)


def search_web():
    query = input(color("\nSearch query > ", GREEN)).strip()
    if not query:
        return
    url = "https://duckduckgo.com/?q=" + quote_plus(query)
    ok, result = open_url(url)
    print(color(f"[OK] {result}" if ok else f"[ERROR] {result}", GREEN if ok else RED))


def show_history(history):
    print(color("\n              URL HISTORY", BOLD + MAGENTA))
    if not history:
        print(color("No history yet.", YELLOW))
        return
    for index, item in enumerate(history[-30:], 1):
        shade = GREEN if item.get("status") == "opened" else RED
        print(color(f"{index:02}. [{item.get('status', '?')}] ", shade)
              + item.get("url", "")
              + color(f"\n    {item.get('time', '')}", DIM))

    choice = input(color("\nEnter item number to reopen, or Enter to return: ", GREEN)).strip()
    if choice.isdigit():
        number = int(choice)
        recent = history[-30:]
        if 1 <= number <= len(recent):
            url = recent[number - 1].get("url", "")
            valid, normalized, message = validate_url(url)
            if valid:
                ok, result = open_url(normalized)
                print(color(f"[OK] {result}" if ok else f"[ERROR] {result}", GREEN if ok else RED))
                add_history(history, normalized, "opened" if ok else "failed")
            else:
                print(color(message, RED))


def copy_url():
    raw = input(color("\nURL to copy > ", GREEN))
    valid, url, message = validate_url(raw)
    if not valid:
        print(color(f"[!] {message}", RED))
        return

    clipboard = shutil.which("termux-clipboard-set")
    if clipboard:
        try:
            subprocess.run([clipboard], input=url, text=True, check=True, timeout=5)
            print(color("[OK] URL copied to clipboard.", GREEN))
            return
        except (OSError, subprocess.SubprocessError) as error:
            print(color(f"Clipboard error: {error}", RED))
            return
    print(color("Clipboard command unavailable. Here is the normalized URL:", YELLOW))
    print(url)


def clear_history(history):
    confirm = input(color("Delete all SSurl history? [y/N]: ", RED)).strip().lower()
    if confirm in ("y", "yes"):
        history.clear()
        save_history(history)
        print(color("History cleared.", GREEN))
    else:
        print(color("Cancelled.", YELLOW))


def menu():
    history = load_history()
    while True:
        clear_screen()
        header()
        print(color("  [1] Open a URL", GREEN))
        print(color("  [2] Open multiple URLs", GREEN))
        print(color("  [3] Search the web", GREEN))
        print(color("  [4] Validate a URL", GREEN))
        print(color("  [5] Copy a URL", GREEN))
        print(color("  [6] URL history", GREEN))
        print(color("  [7] Clear history", GREEN))
        print(color("  [0] Exit", RED))
        choice = input(color("\n  SSurl >> ", BOLD + CYAN)).strip()

        if choice == "1":
            ask_and_open(history)
            pause()
        elif choice == "2":
            multiple_open(history)
            pause()
        elif choice == "3":
            search_web()
            pause()
        elif choice == "4":
            raw = input(color("\nURL to validate > ", GREEN))
            valid, url, message = validate_url(raw)
            print(color(f"[VALID] {url}" if valid else f"[INVALID] {message}",
                        GREEN if valid else RED))
            pause()
        elif choice == "5":
            copy_url()
            pause()
        elif choice == "6":
            show_history(history)
            pause()
        elif choice == "7":
            clear_history(history)
            pause()
        elif choice == "0":
            print(color("\nSSurl closed. See you!", MAGENTA))
            break
        else:
            print(color("Invalid option.", RED))
            time.sleep(0.8)


if __name__ == "__main__":
    try:
        menu()
    except KeyboardInterrupt:
        print(color("\n\n[!] Interrupted by user.", YELLOW))
        sys.exit(0)
