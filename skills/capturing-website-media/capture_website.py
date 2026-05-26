"""Capture screenshots and videos of a website.

Usage:
    python capture_website.py <url> [options]

See README / SKILL.md for full flag reference, or run with --help.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    sync_playwright,
)

DEFAULT_VIEWPORT = (1920, 1080)
DEFAULT_PAGE_DURATION = 8
DEFAULT_MAX_PAGES = 8
NETWORKIDLE_TIMEOUT_MS = 8_000
NAV_TIMEOUT_MS = 30_000

CONSENT_SELECTORS = [
    'button:has-text("Accept all")',
    'button:has-text("Accept All")',
    'button:has-text("Accept")',
    'button:has-text("I agree")',
    'button:has-text("Got it")',
    'button:has-text("Allow all")',
    '[aria-label*="accept" i]',
    '[id*="accept" i][role="button"]',
]


@dataclass
class PageRecord:
    index: int
    slug: str
    url: str
    title: str
    screenshot: str | None = None
    recording: str | None = None
    error: str | None = None


@dataclass
class Manifest:
    source_url: str
    captured_at: str
    depth: int
    viewport: list[int]
    page_duration_seconds: float
    site_tour: str | None = None
    pages: list[PageRecord] = field(default_factory=list)


def slugify(text: str, fallback: str = "page") -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or fallback


def normalize_url(raw: str) -> str:
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = "https://" + raw
    return raw


def strip_fragment(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def same_origin(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)


def host_slug(url: str) -> str:
    return slugify(urlparse(url).netloc, fallback="site")


def dismiss_consent(page: Page) -> None:
    for selector in CONSENT_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=500):
                locator.click(timeout=1_000)
                page.wait_for_timeout(400)
                return
        except PlaywrightError:
            continue


def wait_for_page_ready(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_TIMEOUT_MS)
    except PlaywrightError:
        pass
    page.wait_for_timeout(800)


def smooth_scroll(page: Page, duration_seconds: float) -> None:
    """Scroll from top to bottom then back to top over duration_seconds."""
    half = max(0.5, duration_seconds / 2)
    page.evaluate(
        """
        ([downMs, upMs]) => new Promise(resolve => {
            const startY = 0;
            const endY = Math.max(document.body.scrollHeight - window.innerHeight, 0);
            if (endY <= 0) { setTimeout(resolve, downMs + upMs); return; }
            const phase = (from, to, ms) => new Promise(done => {
                const start = performance.now();
                const step = (now) => {
                    const t = Math.min(1, (now - start) / ms);
                    const eased = t < 0.5 ? 2*t*t : -1 + (4 - 2*t)*t;
                    window.scrollTo(0, from + (to - from) * eased);
                    if (t < 1) requestAnimationFrame(step); else done();
                };
                requestAnimationFrame(step);
            });
            phase(startY, endY, downMs).then(() => phase(endY, startY, upMs)).then(resolve);
        });
        """,
        [half * 1000, half * 1000],
    )


def discover_links(page: Page, base_url: str, max_pages: int,
                   include: list[str], exclude: list[str]) -> list[str]:
    """Return same-origin URLs from nav/header (or fallback to all anchors)."""
    primary = page.evaluate(
        """
        () => {
            const scopes = [
                ...document.querySelectorAll('header a[href]'),
                ...document.querySelectorAll('nav a[href]'),
            ];
            // Fallback: anchors visible in the top 200px
            if (scopes.length === 0) {
                document.querySelectorAll('a[href]').forEach(a => {
                    const r = a.getBoundingClientRect();
                    if (r.top >= 0 && r.top < 200) scopes.push(a);
                });
            }
            return Array.from(new Set(scopes.map(a => a.href).filter(Boolean)));
        }
        """
    )
    if not primary:
        primary = page.evaluate(
            "() => Array.from(new Set([...document.querySelectorAll('a[href]')].map(a => a.href)))"
        )

    seen_paths: set[str] = set()
    result: list[str] = []
    base_path = urlparse(base_url).path.rstrip("/") or "/"
    seen_paths.add(base_path)

    for href in primary:
        url = strip_fragment(href)
        if not url.startswith(("http://", "https://")):
            continue
        if not same_origin(url, base_url):
            continue
        path = urlparse(url).path or "/"
        if path in seen_paths:
            continue
        if include and not any(pat in path for pat in include):
            continue
        if exclude and any(pat in path for pat in exclude):
            continue
        seen_paths.add(path)
        result.append(url)
        if len(result) >= max_pages:
            break
    return result


def capture_page(
    browser: Browser,
    url: str,
    out_dir: Path,
    viewport: tuple[int, int],
    page_duration: float,
    take_screenshot: bool,
    take_video: bool,
    dismiss_banner: bool,
) -> tuple[str, str | None, str | None]:
    """Capture one page. Returns (title, screenshot_rel, video_rel)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    width, height = viewport
    context_kwargs: dict = {
        "viewport": {"width": width, "height": height},
        "device_scale_factor": 1,
    }
    if take_video:
        context_kwargs["record_video_dir"] = str(out_dir)
        context_kwargs["record_video_size"] = {"width": width, "height": height}

    context: BrowserContext = browser.new_context(**context_kwargs)
    page = context.new_page()
    screenshot_rel: str | None = None
    video_rel: str | None = None
    title = url

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        wait_for_page_ready(page)
        if dismiss_banner:
            dismiss_consent(page)
        title = (page.title() or url).strip()

        if take_screenshot:
            shot_path = out_dir / "screenshot.png"
            page.screenshot(path=str(shot_path), full_page=True)
            screenshot_rel = shot_path.name

        if take_video:
            smooth_scroll(page, page_duration)
        else:
            page.wait_for_timeout(int(page_duration * 1000))
    finally:
        video_obj = page.video if take_video else None
        context.close()
        if video_obj:
            try:
                raw = Path(video_obj.path())
                final = out_dir / "recording.webm"
                if raw.exists() and raw != final:
                    shutil.move(str(raw), str(final))
                video_rel = final.name if final.exists() else None
            except PlaywrightError:
                video_rel = None
    return title, screenshot_rel, video_rel


def run_site_tour(
    browser: Browser,
    urls: list[str],
    out_dir: Path,
    viewport: tuple[int, int],
    page_duration: float,
    dismiss_banner: bool,
) -> str | None:
    if not urls:
        return None
    width, height = viewport
    context = browser.new_context(
        viewport={"width": width, "height": height},
        record_video_dir=str(out_dir),
        record_video_size={"width": width, "height": height},
    )
    page = context.new_page()
    video_obj = page.video
    try:
        for i, url in enumerate(urls):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                wait_for_page_ready(page)
                if i == 0 and dismiss_banner:
                    dismiss_consent(page)
                smooth_scroll(page, page_duration)
            except PlaywrightError as e:
                print(f"  tour: skipped {url} ({e.__class__.__name__})", file=sys.stderr)
                continue
    finally:
        context.close()

    if video_obj is None:
        return None
    try:
        raw = Path(video_obj.path())
        final = out_dir / "site-tour.webm"
        if raw.exists() and raw != final:
            shutil.move(str(raw), str(final))
        return final.name if final.exists() else None
    except PlaywrightError:
        return None


def derive_slug(index: int, url: str, title: str) -> str:
    path = urlparse(url).path.strip("/")
    base = slugify(path.replace("/", "-")) if path else slugify(title, fallback="home")
    if not path and base == "page":
        base = "home"
    return f"{index:02d}-{base or 'page'}"


def resolve_output_dir(
    url: str,
    output: str | None,
    into: str | None,
    timestamp: str,
    no_timestamp: bool,
) -> Path:
    """Determine where to write captures.

    Priority:
      1. --output PATH        → use exactly as given (no timestamp appended)
      2. --into PARENT        → create <host>_website_media-<timestamp> inside PARENT
      3. neither              → create <host>_website_media-<timestamp> in current working dir

    The default folder name uses the URL's host plus a timestamp so every run
    is unique. Pass --no-timestamp to drop the suffix.
    """
    if output:
        return Path(output)
    host = urlparse(url).netloc or host_slug(url)
    folder_name = f"{host}_website_media"
    if not no_timestamp:
        folder_name = f"{folder_name}-{timestamp}"
    parent = Path(into).expanduser() if into else Path.cwd()
    return parent / folder_name


def capture(args: argparse.Namespace) -> int:
    url = normalize_url(args.url)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_root = resolve_output_dir(url, args.output, args.into, timestamp, args.no_timestamp)
    if out_root.exists() and any(out_root.iterdir()):
        if args.overwrite:
            shutil.rmtree(out_root)
        else:
            stamped = out_root.with_name(f"{out_root.name}-{timestamp}")
            print(f"Output dir {out_root} not empty — using {stamped.name} instead "
                  f"(pass --overwrite to replace).")
            out_root = stamped
    out_root.mkdir(parents=True, exist_ok=True)
    pages_root = out_root / "pages"

    take_screenshot = not args.videos_only
    take_video = not args.screenshots_only
    viewport = tuple(int(x) for x in args.viewport.lower().split("x"))
    if len(viewport) != 2:
        raise SystemExit(f"--viewport must be WxH, got {args.viewport!r}")

    manifest = Manifest(
        source_url=url,
        captured_at=timestamp,
        depth=args.depth,
        viewport=list(viewport),
        page_duration_seconds=float(args.page_duration),
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)

        # Phase 1: discover pages
        urls_to_capture: list[str] = [url]
        if args.depth >= 1:
            print(f"Discovering links from {url} ...")
            disco_ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]})
            disco_page = disco_ctx.new_page()
            try:
                disco_page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                wait_for_page_ready(disco_page)
                if args.dismiss_banner:
                    dismiss_consent(disco_page)
                discovered = discover_links(
                    disco_page, url, args.max_pages, args.include_path or [], args.exclude_path or []
                )
                urls_to_capture.extend(discovered)
                print(f"  found {len(discovered)} sub-page(s)")
            finally:
                disco_ctx.close()

        # Phase 2: per-page capture
        for i, page_url in enumerate(urls_to_capture):
            slug = derive_slug(i, page_url, "home" if i == 0 else f"page{i}")
            page_dir = pages_root / slug
            print(f"[{i+1}/{len(urls_to_capture)}] {page_url}")
            record = PageRecord(index=i, slug=slug, url=page_url, title=page_url)
            try:
                title, shot, video = capture_page(
                    browser=browser,
                    url=page_url,
                    out_dir=page_dir,
                    viewport=viewport,
                    page_duration=float(args.page_duration),
                    take_screenshot=take_screenshot,
                    take_video=take_video,
                    dismiss_banner=args.dismiss_banner,
                )
                # Refine slug from real title now that we have it
                better_slug = derive_slug(i, page_url, title)
                if better_slug != slug:
                    better_dir = pages_root / better_slug
                    if not better_dir.exists():
                        page_dir.rename(better_dir)
                        page_dir = better_dir
                        slug = better_slug
                record.slug = slug
                record.title = title
                record.screenshot = f"pages/{slug}/{shot}" if shot else None
                record.recording = f"pages/{slug}/{video}" if video else None
            except PlaywrightError as e:
                record.error = f"{e.__class__.__name__}: {e}"
                print(f"  ERROR: {record.error}", file=sys.stderr)
            manifest.pages.append(record)

        # Phase 3: site tour
        if args.depth >= 1 and not args.no_tour and take_video and len(urls_to_capture) > 1:
            print("Recording site tour ...")
            tour_rel = run_site_tour(
                browser=browser,
                urls=urls_to_capture,
                out_dir=out_root,
                viewport=viewport,
                page_duration=float(args.page_duration),
                dismiss_banner=args.dismiss_banner,
            )
            manifest.site_tour = tour_rel

        browser.close()

    manifest_path = out_root / "manifest.json"
    manifest_path.write_text(
        json.dumps({**asdict(manifest), "pages": [asdict(p) for p in manifest.pages]}, indent=2)
    )
    print(f"\nDone. Output: {out_root.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Capture screenshots and videos of a website given a URL.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("url", help="Website URL (scheme added if missing)")
    p.add_argument("--depth", type=int, choices=[0, 1], default=1,
                   help="0 = landing only; 1 = landing + main nav pages")
    p.add_argument("--into", metavar="PARENT_DIR",
                   help="Parent directory in which to create <host>_website_media")
    p.add_argument("--output", metavar="PATH",
                   help="Full output path (overrides --into and the default name)")
    p.add_argument("--overwrite", action="store_true",
                   help="Delete the output dir first if it already exists and is non-empty")
    p.add_argument("--no-timestamp", action="store_true",
                   help="Drop the timestamp suffix from the default folder name")
    p.add_argument("--screenshots-only", action="store_true")
    p.add_argument("--videos-only", action="store_true")
    p.add_argument("--no-tour", action="store_true", help="Skip full-site tour video")
    p.add_argument("--page-duration", type=float, default=DEFAULT_PAGE_DURATION,
                   help="Seconds of recording per page")
    p.add_argument("--viewport", default=f"{DEFAULT_VIEWPORT[0]}x{DEFAULT_VIEWPORT[1]}",
                   help="Viewport size as WxH")
    p.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                   help="Cap on pages discovered at depth 1")
    p.add_argument("--headed", action="store_true", help="Show browser window")
    p.add_argument("--include-path", action="append", metavar="SUBSTR",
                   help="Only include discovered URLs whose path contains this substring (repeatable)")
    p.add_argument("--exclude-path", action="append", metavar="SUBSTR",
                   help="Drop discovered URLs whose path contains this substring (repeatable)")
    p.add_argument("--dismiss-banner", action="store_true", default=True,
                   help="Auto-click common consent buttons before capture")
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.screenshots_only and args.videos_only:
        raise SystemExit("--screenshots-only and --videos-only are mutually exclusive")
    return capture(args)


if __name__ == "__main__":
    raise SystemExit(main())
