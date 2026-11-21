#!/usr/bin/env python3
"""IpPortChecker - a small, rate-limited TCP port checker for private networks."""

from __future__ import annotations

import ipaddress
import os
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional, Tuple

APP_NAME = "IpPortChecker"
VERSION = "1.0.0"
TIMEOUT_SECONDS = 0.45
MAX_WORKERS = 32
MAX_PORTS_PER_SCAN = 1000

# Only private/local IPv4 destinations are accepted.
ALLOWED_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")
)

class Colors:
    enabled = sys.stdout.isatty() and os.environ.get("TERM", "") != "dumb"
    RESET = "\033[0m" if enabled else ""
    BOLD = "\033[1m" if enabled else ""
    CYAN = "\033[96m" if enabled else ""
    BLUE = "\033[94m" if enabled else ""
    GREEN = "\033[92m" if enabled else ""
    YELLOW = "\033[93m" if enabled else ""
    RED = "\033[91m" if enabled else ""
    DIM = "\033[2m" if enabled else ""


def banner() -> None:
    c = Colors
    print(c.CYAN + c.BOLD + r"""
  ___      ____             __       ____                 __
 /  _/___ / __/___  _______/ /____  / __/________ ______/ /____
 / // __ `/ /_/ _ \/ ___/ __  / _ \/ /_/ ___/ __ `/ ___/ __/ _ \
/ // /_/ / __/  __/ /  / /_/ /  __/ __/ /  / /_/ / /__/ /_/  __/
___/\__,_/_/  \___/_/   \__,_/\___/_/ /_/   \__,_/\___/\__/\___/
""" + c.RESET)
    print(f"{c.BOLD}{APP_NAME}{c.RESET}  {c.DIM}v{VERSION} | Private-network TCP checker{c.RESET}")
    print(f"{c.DIM}{'-' * 68}{c.RESET}")


def ask_target() -> str:
    raw = input(f"{Colors.BLUE}Give Me Address {Colors.DIM}[192.168.1.1]{Colors.RESET}: ").strip()
    try:
        address = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise ValueError("Please enter a valid IPv4 address, for example 192.168.1.1.") from exc

    if not isinstance(address, ipaddress.IPv4Address):
        raise ValueError("This version supports IPv4 addresses only.")
    if not any(address in network for network in ALLOWED_NETWORKS):
        raise ValueError("Only private/local IPv4 addresses are allowed (10.x, 172.16-31.x, 192.168.x, or 127.x).")
    return str(address)


def ask_port_range() -> Tuple[int, int]:
    raw = input(f"{Colors.BLUE}Checked Port {Colors.DIM}[1,1000]{Colors.RESET}: ").strip()
    parts = raw.split(",")
    if len(parts) != 2:
        raise ValueError("Enter the first and last port separated by a comma, e.g. 1,1000.")
    try:
        first, last = (int(part.strip()) for part in parts)
    except ValueError as exc:
        raise ValueError("Ports must be whole numbers.") from exc
    if not (1 <= first <= 65535 and 1 <= last <= 65535):
        raise ValueError("Port numbers must be between 1 and 65535.")
    if first > last:
        raise ValueError("The first port cannot be greater than the last port.")
    if last - first + 1 > MAX_PORTS_PER_SCAN:
        raise ValueError(f"A scan is limited to {MAX_PORTS_PER_SCAN} ports at a time.")
    return first, last


def check_tcp_port(host: str, port: int) -> Tuple[int, bool]:
    """Return (port, is_open) using a normal TCP connection attempt."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(TIMEOUT_SECONDS)
            return port, sock.connect_ex((host, port)) == 0
    except OSError:
        return port, False


def service_name(port: int) -> str:
    try:
        return socket.getservbyport(port, "tcp")
    except OSError:
        return "unknown"


def save_report(host: str, first: int, last: int, opened: list[int], elapsed: float) -> Optional[str]:
    answer = input(f"\n{Colors.YELLOW}Save report to a .txt file? [y/N]: {Colors.RESET}").strip().lower()
    if answer not in ("y", "yes"):
        return None

    filename = f"IpPortChecker_{host}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    lines = [
        f"{APP_NAME} v{VERSION}",
        f"Target: {host}",
        f"TCP ports checked: {first}-{last}",
        f"Open ports: {len(opened)}",
        f"Elapsed seconds: {elapsed:.2f}",
        "",
        "OPEN PORTS:",
    ]
    lines.extend(f"{port}/tcp  OPEN  ({service_name(port)})" for port in opened)
    with open(filename, "w", encoding="utf-8") as report:
        report.write("\n".join(lines) + "\n")
    return filename


def run_scan(host: str, first: int, last: int) -> None:
    ports = range(first, last + 1)
    total = len(ports)
    opened: list[int] = []
    completed = 0
    started = time.monotonic()

    print(f"\n{Colors.DIM}Target: {host} | TCP: {first}-{last} | Workers: {MAX_WORKERS}{Colors.RESET}")
    print(f"{Colors.YELLOW}Checking ports...{Colors.RESET}\n")

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(check_tcp_port, host, port) for port in ports]
            for future in as_completed(futures):
                port, is_open = future.result()
                completed += 1
                if is_open:
                    opened.append(port)
                    name = service_name(port)
                    print(f"{Colors.GREEN}[OK] {port}/tcp OPEN{Colors.RESET}  {Colors.DIM}({name}){Colors.RESET}")
                if completed % 25 == 0 or completed == total:
                    width = 24
                    filled = int(width * completed / total)
                    bar = "█" * filled + "░" * (width - filled)
                    print(f"\r{Colors.CYAN}[{bar}] {completed}/{total}{Colors.RESET}", end="", flush=True)
        print()
    except KeyboardInterrupt:
        print(f"\n{Colors.RED}Scan interrupted by user.{Colors.RESET}")
        return

    elapsed = time.monotonic() - started
    opened.sort()
    print(f"\n{Colors.DIM}{'-' * 68}{Colors.RESET}")
    print(f"{Colors.BOLD}SCAN COMPLETE{Colors.RESET}")
    print(f"Target       : {host}")
    print(f"Ports checked: {total}")
    print(f"Open ports   : {len(opened)}")
    print(f"Time         : {elapsed:.2f} seconds")
    if not opened:
        print(f"{Colors.YELLOW}No open TCP ports found in this range.{Colors.RESET}")
    else:
        print(f"{Colors.GREEN}Open: {', '.join(map(str, opened))}{Colors.RESET}")

    report = save_report(host, first, last, opened, elapsed)
    if report:
        print(f"{Colors.GREEN}Report saved: {report}{Colors.RESET}")


def main() -> int:
    banner()
    print("Use this only on your own device/network or with explicit permission.\n")
    try:
        host = ask_target()
        first, last = ask_port_range()
        permission = input(f"\n{Colors.YELLOW}Do you own this device/network or have permission? [y/N]: {Colors.RESET}").strip().lower()
        if permission not in ("y", "yes"):
            print(f"{Colors.RED}Cancelled. Authorization is required.{Colors.RESET}")
            return 0
        run_scan(host, first, last)
    except (ValueError, EOFError) as exc:
        print(f"\n{Colors.RED}Input error: {exc}{Colors.RESET}")
        return 2
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Cancelled.{Colors.RESET}")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
