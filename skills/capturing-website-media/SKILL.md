---
name: capturing-website-media
description: Use when capturing screenshots and screen recordings of a website's pages given just a URL — landing page only, or auto-discovered main pages from the top nav. Produces full-page PNGs, per-page WEBM clips with scroll animation to show transitions/parallax, and an optional full-site tour video.
---

# Capturing Website Media

## Overview

Given a URL, capture media of a website for demos, design reviews, marketing, or archival:

- **Full-page PNG** of each captured page
- **Short WEBM clip** per page showing scroll animation (reveals motion, parallax, scroll-triggered animations)
- **Long WEBM tour** that navigates the whole site end-to-end

Driven by Playwright (Python, Chromium). All capture options live in one script: `capture_website.py`.

## When to Use

- "Grab screenshots of my site"
- "Record a demo video of the site"
- "Capture every main page of a site as PNG + video"
- Building case-study pages, investor decks, marketing assets, or design audits
- You want depth control: just the landing page, or all main nav pages

**Not for:** Authenticated flows (no login support in this skill), single-page Playwright automation tasks (use `agent-browser` instead), or pixel-perfect baseline diffing (use Percy/Chromatic).

## Quick Reference

```bash
# Landing page only — saves to ./roscodetech.com_website_media
python capture_website.py https://roscodetech.com --depth 0

# Pick the parent folder; creates ./Desktop/roscodetech.com_website_media inside it
python capture_website.py https://roscodetech.com --depth 1 --into ~/Desktop

# Fully explicit output path (overrides naming + --into)
python capture_website.py https://roscodetech.com --depth 1 --output "D:/captures/run-A"

# Replace an existing output dir instead of suffixing a timestamp
python capture_website.py https://roscodetech.com --depth 1 --into ~/Desktop --overwrite

# Skip the tour, just per-page assets
python capture_website.py https://example.com --depth 1 --no-tour

# Watch it run live
python capture_website.py https://example.com --depth 1 --headed
```

**Default output folder:** `<host>_website_media` (e.g. `roscodetech.com_website_media`), created in the **current working directory** unless you pass `--into` or `--output`. If the target already exists and is non-empty, a `-<timestamp>` suffix is appended automatically (or pass `--overwrite` to replace it).

| Flag | Default | What it does |
|------|---------|--------------|
| `url` (positional) | — | URL to capture. Scheme added if missing. |
| `--depth {0,1}` | `1` | `0` = landing only; `1` = landing + main nav pages |
| `--into PARENT_DIR` | cwd | Parent directory; creates `<host>_website_media` inside it |
| `--output PATH` | — | Full explicit output path (overrides `--into` and default naming) |
| `--overwrite` | off | Delete target dir first if it already exists and is non-empty |
| `--screenshots-only` | off | Skip videos |
| `--videos-only` | off | Skip screenshots |
| `--no-tour` | off | Skip the full-site tour video (depth 1 only) |
| `--page-duration SEC` | `8` | Seconds of recording per page |
| `--viewport WxH` | `1920x1080` | Browser viewport size |
| `--max-pages N` | `8` | Cap on pages discovered at depth 1 |
| `--headed` | off | Show the browser window |
| `--include-path PAT` | — | Repeatable. Only include discovered URLs whose path contains this substring |
| `--exclude-path PAT` | — | Repeatable. Drop discovered URLs whose path contains this substring |

## Output Layout

```
roscodetech.com_website_media/
  manifest.json              # machine-readable index of everything captured
  pages/
    00-home/
      screenshot.png         # full-page PNG
      recording.webm         # ~8s scroll animation
    01-products/
      screenshot.png
      recording.webm
    ...
  site-tour.webm             # longer multi-page tour (depth 1 only, unless --no-tour)
```

## How Page Discovery Works (depth = 1)

The script visits the landing page, then collects same-origin links from these locations in priority order:

1. `<header> a[href]`
2. `<nav> a[href]`
3. Anchors in the top 200px of the page (sticky nav fallback)

It dedupes by path, drops `#fragments`, mailto/tel/external hosts, then caps at `--max-pages`. Use `--include-path` / `--exclude-path` to constrain.

If discovery returns nothing (e.g. nav rendered late, unusual markup), the script falls back to all same-origin anchors found anywhere on the page.

## Per-Page Capture Sequence

For each page, the script:

1. Opens a fresh browser context with `record_video_dir` set (one video file per page).
2. Navigates and waits for `networkidle` (or 8s, whichever first).
3. Pauses briefly so above-the-fold animations play.
4. Takes a full-page screenshot.
5. Smoothly scrolls top → bottom → top over `--page-duration` seconds, capturing parallax / scroll-triggered animations.
6. Closes the context, which finalizes the WEBM.

The site tour uses one long-lived context that visits each page sequentially.

## Common Issues

| Problem | Fix |
|---------|-----|
| `playwright._impl._errors.Error: Executable doesn't exist` | Run `python -m playwright install chromium` once. |
| WEBM won't play in QuickTime / Premiere | Convert: `ffmpeg -i recording.webm -c:v libx264 -pix_fmt yuv420p recording.mp4`. |
| Discovery picks wrong links | Use `--include-path` / `--exclude-path`, or fall back to `--depth 0` and list URLs manually in a follow-up run. |
| Hangs on slow site | `networkidle` waits up to 8s, then proceeds. If still slow, lower expectations on completeness; consider running with `--headed` to watch. |
| Sticky cookie banner covers screenshots | Pass `--dismiss-banner` (the script auto-clicks common consent buttons by aria-label). |
| Auth required | Out of scope — use `agent-browser` or Playwright directly. |

## First-Time Setup

```bash
pip install playwright
python -m playwright install chromium
```

## Implementation

The full implementation is in `capture_website.py` in this skill's directory. Run with `--help` for the live flag list.
