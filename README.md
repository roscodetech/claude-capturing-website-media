# claude-capturing-website-media

Capture screenshots and screen recordings of any public website given just a URL — a Claude Code plugin.

## What it does

The `capturing-website-media` skill turns a URL into a packaged folder of demo-ready media:

- **Full-page PNG** of each captured page
- **Short WEBM clip** per page showing scroll animation (reveals motion, parallax, scroll-triggered animations)
- **Long WEBM tour** that navigates the whole site end-to-end
- **`manifest.json`** machine-readable index of everything captured

Driven by Playwright + headless Chromium. Two depth modes:

- `--depth 0` — landing page only
- `--depth 1` — landing + auto-discovered main nav pages (default)

## Install

```bash
claude plugin add github.com/roscodetech/claude-capturing-website-media
```

Local development install:

```bash
claude plugin add "file://C:/ROSCODE TECH/Utility Apps/claude-capturing-website-media"
```

Or clone directly into your user-level skills directory (no plugin manifest needed):

```bash
git clone https://github.com/roscodetech/claude-capturing-website-media ~/.claude/skills/capturing-website-media-plugin
```

## Prerequisites

Python 3.10+ and Playwright with Chromium:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Usage

Just ask — the skill triggers on capture requests:

```
Grab screenshots and a video of roscodetech.com
Record a demo of every main page of skinvest.ai
```

Or invoke the script directly:

```bash
# Landing page only — saves to ./roscodetech.com_website_media
python skills/capturing-website-media/capture_website.py https://roscodetech.com --depth 0

# Landing + main nav pages, into a chosen parent folder
python skills/capturing-website-media/capture_website.py https://roscodetech.com --depth 1 --into ~/Desktop

# Skip the full-site tour, just per-page assets
python skills/capturing-website-media/capture_website.py https://example.com --depth 1 --no-tour

# Watch it run live
python skills/capturing-website-media/capture_website.py https://example.com --depth 1 --headed
```

Run with `--help` for the full flag list.

## Output layout

```
roscodetech.com_website_media/
  manifest.json              # machine-readable index
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

## When to use it

- Building case-study pages, investor decks, or marketing assets
- Design audits and before/after comparisons
- Archiving a site state before a redesign
- Generating demo footage for a launch post

**Not for:** authenticated flows (no login support), single-page Playwright automation (use `agent-browser`), or pixel-perfect baseline diffing (use Percy/Chromatic).

## How page discovery works (depth = 1)

The script visits the landing page, then collects same-origin links from these locations in priority order:

1. `<header> a[href]`
2. `<nav> a[href]`
3. Anchors in the top 200px of the page (sticky nav fallback)

It dedupes by path, drops `#fragments`, `mailto:`/`tel:`/external hosts, then caps at `--max-pages` (default 8). Use `--include-path` / `--exclude-path` to constrain. If discovery returns nothing, the script falls back to all same-origin anchors found anywhere on the page.

## Per-page capture sequence

For each page:

1. Open a fresh browser context with `record_video_dir` set (one video file per page).
2. Navigate and wait for `networkidle` (or 8s, whichever first).
3. Brief pause so above-the-fold animations play.
4. Take a full-page screenshot.
5. Smooth scroll top → bottom → top over `--page-duration` seconds (default 8).
6. Close the context, which finalizes the WEBM.

The site tour uses one long-lived context that visits each page sequentially.

## Common issues

| Problem | Fix |
|---------|-----|
| `playwright._impl._errors.Error: Executable doesn't exist` | Run `python -m playwright install chromium` once. |
| WEBM won't play in QuickTime / Premiere | Convert: `ffmpeg -i recording.webm -c:v libx264 -pix_fmt yuv420p recording.mp4` |
| Discovery picks wrong links | Use `--include-path` / `--exclude-path`, or fall back to `--depth 0` and run multiple times with explicit URLs. |
| Sticky cookie banner covers screenshots | Pass `--dismiss-banner` (the script auto-clicks common consent buttons by aria-label). |
| Auth required | Out of scope — use `agent-browser` or Playwright directly. |

## Layout

```
claude-capturing-website-media/
├── .claude-plugin/
│   └── plugin.json
├── skills/
│   └── capturing-website-media/
│       ├── SKILL.md             # Read by Claude Code; tells the agent how to invoke
│       └── capture_website.py   # The full Playwright capture script
├── README.md
├── LICENSE
├── requirements.txt
└── .gitignore
```

## License

MIT — see [LICENSE](LICENSE). © 2026 Roscoe Kerby.
