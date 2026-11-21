#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSBrowsers - a lightweight, privacy-focused, text-mode web browser.

Standard-library only. Designed for Termux and ordinary Python terminals.
It does not execute JavaScript or load third-party images/scripts/frames.
"""

from __future__ import annotations

import html
import ipaddress
import re
import shlex
import socket
import sys
import textwrap
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import (
    parse_qs, parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit,
)
from urllib.request import (
    HTTPRedirectHandler, HTTPSHandler, Request, build_opener,
)

APP_NAME = "SSBrowsers"
VERSION = "1.0.0"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_LINKS = 100
TIMEOUT_SECONDS = 12

# A compact deny-list for common analytics/ad endpoints. This is not exhaustive.
TRACKER_DOMAINS = {
    "doubleclick.net", "googletagmanager.com", "google-analytics.com",
    "connect.facebook.net", "facebook.net", "analytics.twitter.com",
    "static.ads-twitter.com", "bat.bing.com", "clarity.ms",
    "hotjar.com", "static.hotjar.com", "segment.io", "cdn.segment.com",
    "scorecardresearch.com", "quantserve.com", "adnxs.com",
    " 광고.example.invalid",
}

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid",
    "igshid", "yclid", "gbraid", "wbraid", "vero_id", "oly_anon_id",
    "oly_enc_id", "_hsenc", "_hsmi", "mkt_tok", "ref_src", "ref_url",
}

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"


def paint(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


def clear_screen() -> None:
    print("\033[2J\033[H", end="")


def host_is_private_or_local(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return True
    try:
        return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def host_is_tracker(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain)
               for domain in TRACKER_DOMAINS)


def clean_url(raw_url: str) -> str:
    """Normalize a URL and remove common click/tracking parameters."""
    value = raw_url.strip()
    if not value:
        raise ValueError("URL is empty")
    if value.startswith("//"):
        value = "https:" + value
    elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS web addresses are supported")
    if not parts.hostname:
        raise ValueError("The address does not contain a valid host")
    if parts.username or parts.password:
        raise ValueError("Addresses containing embedded usernames/passwords are blocked")
    host = parts.hostname.lower()
    if host_is_tracker(host):
        raise PermissionError(f"Blocked known tracking domain: {host}")
    kept = []
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        low = key.lower()
        if low.startswith("utm_") or low in TRACKING_PARAMS:
            continue
        kept.append((key, val))
    query = urlencode(kept, doseq=True)
    return urlunsplit((scheme, parts.netloc, parts.path or "/", query, parts.fragment))


class SafeRedirectHandler(HTTPRedirectHandler):
    """Reject redirects to trackers and HTTPS-to-HTTP downgrades."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urlsplit(req.full_url)
        new = urlsplit(urljoin(req.full_url, newurl))
        if old.scheme == "https" and new.scheme != "https":
            raise HTTPError(newurl, code, "Blocked HTTPS downgrade redirect", headers, fp)
        if new.scheme not in {"http", "https"} or not new.hostname:
            raise HTTPError(newurl, code, "Blocked unsafe redirect", headers, fp)
        if host_is_tracker(new.hostname):
            raise HTTPError(newurl, code, "Blocked tracker redirect", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass
class Page:
    url: str
    title: str
    body: str
    links: list[tuple[str, str]] = field(default_factory=list)
    content_type: str = "text/html"
    status: int = 200
    loaded_at: float = field(default_factory=time.time)


class TextPageParser(HTMLParser):
    """Extract readable text and links without executing page content."""
    HIDDEN = {"script", "style", "noscript", "svg", "canvas", "iframe",
              "object", "embed", "template"}
    BLOCKS = {"p", "div", "section", "article", "main", "header", "footer",
              "aside", "li", "ul", "ol", "tr", "table", "blockquote",
              "pre", "address", "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.hidden_depth = 0
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.anchor_stack: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr = dict(attrs)
        if tag in self.HIDDEN:
            self.hidden_depth += 1
            if tag == "title":
                self.title_depth += 1
            return
        if self.hidden_depth:
            return
        if tag == "title":
            self.title_depth += 1
        if tag in self.BLOCKS:
            self.parts.append("\n")
        if tag == "a" and attr.get("href") and len(self.links) < MAX_LINKS:
            self.anchor_stack.append({"href": attr["href"], "text": ""})
        if tag == "img" and attr.get("alt"):
            self.parts.append(f" [Image: {attr['alt']}] ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.HIDDEN:
            self.hidden_depth = max(0, self.hidden_depth - 1)
            return
        if self.hidden_depth:
            return
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        if tag == "a" and self.anchor_stack:
            item = self.anchor_stack.pop()
            label = " ".join(item["text"].split()) or item["href"]
            self.links.append((label[:180], item["href"]))
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.hidden_depth:
            return
        value = data.strip()
        if not value:
            return
        if self.title_depth:
            self.title_parts.append(value)
        self.parts.append(value + " ")
        for item in self.anchor_stack:
            item["text"] += value + " "

    def result(self):
        raw = "".join(self.parts)
        lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in raw.splitlines()]
        cleaned = []
        blank = False
        for line in lines:
            if line:
                cleaned.append(line)
                blank = False
            elif not blank:
                cleaned.append("")
                blank = True
        return "\n".join(cleaned).strip(), " ".join(self.title_parts).strip(), self.links


class PrivacyBrowser:
    def __init__(self):
        self.cookie_jar = CookieJar()  # in-memory only; never written to disk
        self.cookies_enabled = False
        self.history: list[str] = []  # session memory only
        self.bookmarks: list[tuple[str, str]] = []  # session memory only
        self.pages: list[Page] = []
        self.page_index = -1
        self.current: Page | None = None
        self.last_error = ""
        self._make_opener()

    def _make_opener(self):
        from urllib.request import HTTPCookieProcessor
        handlers = [SafeRedirectHandler(), HTTPSHandler()]
        if self.cookies_enabled:
            handlers.append(HTTPCookieProcessor(self.cookie_jar))
        self.opener = build_opener(*handlers)

    def set_cookies(self, enabled: bool):
        self.cookies_enabled = enabled
        if not enabled:
            self.cookie_jar.clear()
        self._make_opener()

    def fetch(self, raw_url: str) -> Page:
        url = clean_url(raw_url)
        parts = urlsplit(url)
        if parts.scheme == "http" and not host_is_private_or_local(parts.hostname or ""):
            raise PermissionError("Plain HTTP is blocked for public websites. Use HTTPS.")
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.8,*/*;q=0.2",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "close",
            # Deliberately no Referer header.
        })
        with self.opener.open(req, timeout=TIMEOUT_SECONDS) as response:
            final_url = response.geturl()
            final_parts = urlsplit(final_url)
            if parts.scheme == "https" and final_parts.scheme != "https":
                raise PermissionError("Blocked an insecure redirect")
            if final_parts.hostname and host_is_tracker(final_parts.hostname):
                raise PermissionError("Blocked a tracking redirect")
            content_type = response.headers.get_content_type().lower()
            if content_type not in {"text/html", "application/xhtml+xml", "text/plain", "application/json"}:
                raise ValueError(f"Unsupported content type: {content_type}. This is a text browser.")
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise ValueError("Page is larger than the 2 MB safety limit")
            charset = response.headers.get_content_charset() or "utf-8"
            decoded = data.decode(charset, errors="replace")
            if content_type in {"text/plain", "application/json"}:
                body = decoded.strip()
                title = final_parts.hostname or "Text page"
                links = []
            else:
                parser = TextPageParser()
                parser.feed(decoded)
                body, title, links = parser.result()
                title = title or final_parts.hostname or "Untitled page"
                safe_links = []
                for label, href in links:
                    try:
                        absolute = clean_url(urljoin(final_url, href))
                    except (ValueError, PermissionError):
                        continue
                    safe_links.append((label, absolute))
                links = safe_links[:MAX_LINKS]
            return Page(final_url, title[:180], body, links, content_type,
                        getattr(response, "status", 200))

    def navigate(self, url: str, add_history: bool = True):
        page = self.fetch(url)
        if self.page_index < len(self.pages) - 1:
            self.pages = self.pages[:self.page_index + 1]
        self.pages.append(page)
        self.page_index = len(self.pages) - 1
        self.current = page
        if add_history:
            self.history.append(page.url)
        return page

    def move_history(self, offset: int):
        target = self.page_index + offset
        if 0 <= target < len(self.pages):
            self.page_index = target
            self.current = self.pages[target]
            return self.current
        return None

    def reload(self):
        if not self.current:
            return None
        old_url = self.current.url
        page = self.fetch(old_url)
        self.pages[self.page_index] = page
        self.current = page
        return page

    def search(self, query: str):
        q = urlencode({"q": query})
        return self.navigate("https://html.duckduckgo.com/html/?" + q)

    def open_link(self, number: int):
        if not self.current:
            raise ValueError("No page is open")
        if number < 1 or number > len(self.current.links):
            raise ValueError(f"Choose a link number from 1 to {len(self.current.links)}")
        label, url = self.current.links[number - 1]
        return self.navigate(url)

    def clear_private_data(self):
        self.cookie_jar.clear()
        self.history.clear()
        self.bookmarks.clear()
        self.pages.clear()
        self.page_index = -1
        self.current = None
        self._make_opener()


def print_banner():
    clear_screen()
    print(paint("╔══════════════════════════════════════════════════════════════╗", CYAN))
    print(paint("║                 S S B R O W S E R S                         ║", BOLD + CYAN))
    print(paint("║        Lightweight • Text Mode • Privacy Focused            ║", DIM))
    print(paint("╚══════════════════════════════════════════════════════════════╝", CYAN))
    print(f"{DIM}v{VERSION} | JavaScript disabled | Third-party resources not loaded | Session-only data{RESET}")
    print(paint("Privacy note: this does NOT make you anonymous or hide your IP address.", YELLOW))
    print("Type 'help' for commands.\n")


def print_page(page: Page):
    clear_screen()
    width = max(50, min(100, shutil_terminal_width() - 2))
    print(paint("─" * width, CYAN))
    print(paint(page.title or "Untitled", BOLD + GREEN))
    print(paint(page.url, DIM))
    print(paint("─" * width, CYAN))
    body = page.body or "[No readable text found. The page may require JavaScript. ]"
    for line in body.splitlines():
        if not line:
            print()
        else:
            print(textwrap.fill(line, width=width, replace_whitespace=False,
                                break_long_words=True, break_on_hyphens=False))
    if page.links:
        print("\n" + paint(f"── LINKS ({len(page.links)}) ──", MAGENTA))
        for i, (label, _) in enumerate(page.links, 1):
            print(f"{paint(f'[{i:02}]', CYAN)} {label[:100]}")
    print(paint("\nCommands: links | go N | back | forward | help", DIM))


def shutil_terminal_width():
    try:
        return __import__("shutil").get_terminal_size((80, 20)).columns
    except Exception:
        return 80


def show_help():
    print("""
SSBrowsers commands
──────────────────────────────────────────────────────────────
  https://example.com   Open a website
  open URL              Open a website
  search WORDS          Search with DuckDuckGo HTML
  go N                  Open link number N from the current page
  links                 Show numbered links
  back / forward        Move through this session's page stack
  reload                Reload the current page
  bookmark              Save current page in temporary bookmarks
  bookmarks             Show temporary bookmarks
  history               Show this session's visited pages
  cookies on|off        Enable or disable in-memory cookies
  clear                 Clear cookies, history, bookmarks and pages
  info                  Show privacy and browser limitations
  help                  Show this help
  quit                  Exit

Privacy defaults
──────────────────────────────────────────────────────────────
  • No browser history or bookmarks are written to disk.
  • Cookies, when enabled, stay in RAM and are cleared on exit.
  • Common tracking query parameters are removed from URLs.
  • Known tracker domains are blocked using a small built-in list.
  • JavaScript, remote images, ads, analytics scripts and frames are not loaded.
  • No Referer header is sent. HTTPS is required for public websites.

Limitations: this is a text-mode reader, not a full graphical browser.
Many modern websites require JavaScript, forms, or interactive features.
The website and your network provider can still see your IP address.
""")


def show_info(browser: PrivacyBrowser):
    print(f"Version: {VERSION}")
    print("Mode: text-only HTTP client")
    print("Cookies:", "enabled (RAM only)" if browser.cookies_enabled else "disabled")
    print("Current-session pages:", len(browser.history))
    print("Temporary bookmarks:", len(browser.bookmarks))
    print("JavaScript: disabled")
    print("Third-party resources: not requested")
    print("HTTPS-only for public sites: enabled")
    print("IP masking / anonymity: NOT provided")


def handle_command(browser: PrivacyBrowser, raw: str) -> bool:
    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        print(paint(f"Input error: {exc}", RED))
        return True
    if not tokens:
        return True
    cmd = tokens[0].lower()
    arg = raw[len(tokens[0]):].strip()
    try:
        if cmd in {"quit", "exit", "q"}:
            return False
        if cmd in {"help", "?"}:
            show_help()
        elif cmd == "info":
            show_info(browser)
        elif cmd == "open":
            if not arg:
                print("Usage: open https://example.com")
            else:
                page = browser.navigate(arg)
                print_page(page)
        elif cmd == "search":
            if not arg:
                print("Usage: search privacy browser")
            else:
                page = browser.search(arg)
                print_page(page)
        elif cmd == "go":
            if not tokens[1:] or not tokens[1].isdigit():
                print("Usage: go 3")
            else:
                print_page(browser.open_link(int(tokens[1])))
        elif cmd == "links":
            if not browser.current or not browser.current.links:
                print("No links on the current page.")
            else:
                for i, (label, url) in enumerate(browser.current.links, 1):
                    print(f"[{i:02}] {label}\n     {url}")
        elif cmd == "back":
            page = browser.move_history(-1)
            print_page(page) if page else print("No previous page.")
        elif cmd == "forward":
            page = browser.move_history(1)
            print_page(page) if page else print("No next page.")
        elif cmd == "reload":
            page = browser.reload()
            print_page(page) if page else print("No page to reload.")
        elif cmd == "bookmark":
            if browser.current:
                item = (browser.current.title, browser.current.url)
                if item not in browser.bookmarks:
                    browser.bookmarks.append(item)
                print(paint("Saved for this session only.", GREEN))
            else:
                print("Open a page first.")
        elif cmd == "bookmarks":
            if not browser.bookmarks:
                print("No temporary bookmarks.")
            for i, (title, url) in enumerate(browser.bookmarks, 1):
                print(f"[{i}] {title} — {url}")
        elif cmd == "history":
            if not browser.history:
                print("No session history.")
            for i, url in enumerate(browser.history, 1):
                print(f"[{i}] {url}")
        elif cmd == "cookies":
            if len(tokens) != 2 or tokens[1].lower() not in {"on", "off"}:
                print("Usage: cookies on|off")
            else:
                enabled = tokens[1].lower() == "on"
                browser.set_cookies(enabled)
                print(paint("Cookies " + ("enabled (RAM only)." if enabled else "disabled and cleared."), GREEN))
        elif cmd == "clear":
            browser.clear_private_data()
            print(paint("Session data cleared.", GREEN))
        elif cmd.startswith("https://") or cmd.startswith("http://") or "." in tokens[0]:
            print_page(browser.navigate(raw))
        else:
            print("Unknown command. Type 'help'.")
    except (ValueError, PermissionError) as exc:
        print(paint(f"Blocked / invalid: {exc}", YELLOW))
    except HTTPError as exc:
        print(paint(f"HTTP error {exc.code}: {exc.reason}", RED))
    except URLError as exc:
        print(paint(f"Network error: {exc.reason}", RED))
    except (TimeoutError, socket.timeout):
        print(paint("Connection timed out.", RED))
    except Exception as exc:
        print(paint(f"Unexpected error: {type(exc).__name__}: {exc}", RED))
    return True


def main():
    browser = PrivacyBrowser()
    print_banner()
    while True:
        try:
            prompt = paint("SSBrowsers", CYAN) + paint(" > ", BOLD)
            command = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nClosing SSBrowsers. Temporary session data will be discarded.")
            break
        if not handle_command(browser, command):
            print("Closing SSBrowsers. Temporary session data will be discarded.")
            break


if __name__ == "__main__":
    main()
