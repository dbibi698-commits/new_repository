#!/usr/bin/env python3
"""Browser sample — Playwright diye browser kholo, URL-e jao, click koro.

FULL PROCESS (Mark-er Browser Setup wizard-eo ei step-gulo ache):
    1. PC-te Python install koro (python.org, "Add Python to PATH" tick dao)
    2. CMD-te chalao:  pip install playwright
    3. Tarpor chalao:  playwright install
       (browser download hoy ~150 MB — Chromium/Firefox/WebKit)
    4. Ei file-ta chalao:  python browser_sample.py
       ba nijer URL/selector diye:
           python browser_sample.py --url https://example.com --selector "a"

Ki kore ei code-ta:
    sync_playwright() -> Chromium launch koro
        (channel="chrome" hole TOMAR nijer Chrome khulbe — login-gulo
        thakbe; na thakle download kora Chromium headless cholbe)
    -> page.goto(URL)      -> oi page-e jao
    -> page.click(selector) -> selector diye element-e click koro
    -> type koro           -> search box-e lekho (jodi thake)
    -> screenshot nao      -> browser_sample.png
    -> browser.close()     -> browser bondho koro

Selector mane: page-er kon element-e click korbe tar thikana.
Udahoron: "a" (prothom link), "button", "#search", ".btn-primary",
"text=Log in".
"""
from __future__ import annotations

import argparse
import os
import sys

# Default URL / selector — Mark-er wizard theke bodlano jay.
DEFAULT_URL = "https://example.com"
DEFAULT_SELECTOR = "a"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Playwright browser sample — kholo, jao, click koro.")
    parser.add_argument("--url", default=DEFAULT_URL,
                        help="Kon URL-e jabe (default: %(default)s)")
    parser.add_argument("--selector", default=DEFAULT_SELECTOR,
                        help="Kon element-e click korbe, CSS selector "
                             "(default: %(default)s)")
    parser.add_argument("--headless", action="store_true",
                        help="Browser na dekhiye background-e chalao")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright install kora nei. Age chalao:")
        print("    pip install playwright")
        print("    playwright install")
        return 1

    with sync_playwright() as p:
        # 1. Browser launch koro — age tomar nijer Chrome try koro
        #    (channel="chrome" hole tomar login/profile thakbe),
        #    na parle download kora Chromium use koro.
        browser = None
        try:
            browser = p.chromium.launch(channel="chrome",
                                        headless=args.headless)
            print("Chrome khullam — tomar nijer Chrome (login thakbe).")
        except Exception as e:
            print(f"Nijer Chrome khola gelo na ({e}) — "
                  "download kora Chromium diye khulchi.")
            browser = p.chromium.launch(headless=True)
            print("Download kora Chromium khullam (headless).")

        page = browser.new_page()

        # 2. URL-e jao.
        print(f"Jacchi: {args.url}")
        page.goto(args.url, wait_until="domcontentloaded")
        print(f"Pouche gelam: {page.url} — title: {page.title()!r}")

        # 3. Selector diye element-e click koro.
        print(f"Click korchi: {args.selector!r}")
        page.click(args.selector, timeout=15000)
        print(f"Click holo: {args.selector!r} — ekhon URL: {page.url}")

        # 4. Jodi search box thake, tate type koro (na thakle skip).
        search = page.query_selector('input[type="search"], input[name="q"]')
        if search is not None:
            search.fill("hello playwright")
            print("Search box-e type korlam: 'hello playwright'")

        # 5. Screenshot nao — ki dekhlam tar proof.
        shot = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "browser_sample.png")
        page.screenshot(path=shot)
        print(f"Screenshot nilam: {shot}")

        # 6. Browser bondho koro.
        browser.close()
        print("Browser bondho — sample sesh. ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
