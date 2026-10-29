"""Capture T&T's store-locator GraphQL responses.

Two ways in, same output (data/raw/<date>.json, the untouched responses):
- `tnt scrape` loads the page once in Playwright and records network
  responses. If Akamai serves a block page it stops; it never retries with
  a different fingerprint.
- `tnt import <file>` reads a HAR or JSON saved from your own browser's
  DevTools, for when automated access is refused.
"""

import base64
import json
from datetime import date
from pathlib import Path

URL = "https://www.tntsupermarket.com/eng/store-location"
RAW_DIR = Path("data/raw")


class Blocked(RuntimeError):
    pass


def _raw_path(day: date | None = None) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    return RAW_DIR / f"{(day or date.today()).isoformat()}.json"


def _save(captures: list[dict], source: str) -> Path:
    if not captures:
        raise RuntimeError("no GraphQL responses captured; nothing saved")
    path = _raw_path()
    path.write_text(json.dumps({"source": source, "captures": captures}, indent=1, ensure_ascii=False))
    return path


def scrape(postal_prefix: str = "V5K") -> Path:
    from playwright.sync_api import sync_playwright

    captures: list[dict] = []

    def on_response(resp):
        if "graphql" not in resp.url.lower():
            return
        try:
            body = resp.json()
        except Exception:
            return
        captures.append({
            "url": resp.url,
            "status": resp.status,
            "request": resp.request.post_data,
            "response": body,
        })

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("response", on_response)
        resp = page.goto(URL, wait_until="networkidle", timeout=60_000)
        if resp is None or resp.status in (403, 429) or "Access Denied" in page.title():
            browser.close()
            raise Blocked(f"blocked by the site (HTTP {resp.status if resp else '?'}); stopping, not retrying")

        if not captures:
            # The locator may only query after a search. One search, then stop.
            box = page.get_by_placeholder("postal", exact=False)
            if box.count():
                box.first.fill(postal_prefix)
                box.first.press("Enter")
                page.wait_for_timeout(5_000)
        browser.close()
    return _save(captures, f"playwright:{URL}")


def import_capture(path: Path) -> Path:
    """Import a DevTools HAR ("Save all as HAR") or a copied JSON response."""
    data = json.loads(path.read_text())
    captures = []
    if "log" in data:  # HAR
        for entry in data["log"]["entries"]:
            req, resp = entry["request"], entry["response"]
            content = resp.get("content", {})
            text = content.get("text")
            if text and content.get("encoding") == "base64":
                text = base64.b64decode(text).decode()
            if "graphql" in req["url"].lower() and text:
                captures.append({
                    "url": req["url"],
                    "status": resp["status"],
                    "request": (req.get("postData") or {}).get("text"),
                    "response": json.loads(text),
                })
    else:
        captures.append({"url": None, "status": 200, "request": None, "response": data})
    return _save(captures, f"import:{path.name}")
