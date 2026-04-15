# tikscrap — Project Requirements Document

## Overview

**tikscrap** is a Python-based automation tool that:
1. Scrapes photo posts (slideshows) from a set of TikTok channels daily
2. Saves post metadata and downloads images to disk
3. Automatically reposts fetched content to Facebook and Instagram
4. Provides a web dashboard (FastAPI) to configure and monitor everything

---

## Project Structure

```
tikscrap/
├── main.py              # TikTok scraper — runs once daily via systemd
├── poster.py            # Facebook + Instagram poster — runs after scraper
├── config.json          # All credentials and settings (never commit this)
├── state.json           # Auto-generated runtime state (seen IDs, posts, etc.)
├── tikscrap.log         # Auto-generated log file
├── images/              # Downloaded images, organised by username/post_id
│   └── {username}/
│       └── {post_id}/
│           ├── 0.jpg
│           └── 1.jpg
├── web/
│   ├── app.py           # FastAPI dashboard
│   └── templates/       # Jinja2 HTML templates
└── venv/                # Python virtual environment (not committed)
```

---

## Config File Schema (`config.json`)

```json
{
  "MS_TOKEN": "tiktok ms_token cookie value",
  "FB_TOKEN": "meta system user token (never expires)",
  "FB_PAGE_ID": "945560738650895",
  "IG_USER_ID": "17841446967517618",
  "following": [
    "username1",
    "username2"
  ]
}
```

### Credential Notes
- `MS_TOKEN` — extracted from TikTok browser cookies; may expire and need manual refresh
- `FB_TOKEN` — Meta **system user token** (not long-lived page token); never expires
- `FB_PAGE_ID` — Facebook Page: **manime** (`945560738650895`)
- `IG_USER_ID` — Instagram Business Account linked to the Facebook Page (`17841446967517618`)
- `following` — manually maintained list of TikTok usernames to monitor

---

## Module 1: `main.py` — TikTok Scraper

### Purpose
Fetch new photo posts from every channel in `config.following` and save them.

### Behaviour
- Reads `following` list from `config.json` (manually maintained)
- For each username, fetches the latest **10 posts** from TikTok
- Skips posts that are **not photo/slideshow** type (i.e. no `imagePost` field in response)
- Skips posts whose ID is already in `state.seen_ids`
- Downloads all images from new photo posts into `images/{username}/{post_id}/`
- Saves post metadata to `state.posts`
- Updates `state.seen_ids` with newly processed post IDs

### State File Schema (`state.json`)
```json
{
  "following": ["user1", "user2"],
  "seen_ids": ["7123456789", "7987654321"],
  "posts": [
    {
      "id": "7123456789",
      "author": "user1",
      "title": "post description/caption here",
      "fetched_at": "2025-03-28T00:00:00+00:00",
      "image_urls": ["https://..."],
      "local_dir": "images/user1/7123456789",
      "posted_fb": false,
      "posted_ig": false
    }
  ]
}
```

### Key Fields per Post
| Field | Source | Notes |
|---|---|---|
| `id` | `data["id"]` | TikTok post ID |
| `author` | username string | TikTok username |
| `title` | `data.get("desc")` | Post caption/description |
| `image_urls` | `data["imagePost"]["images"][n]["imageURL"]["urlList"][0]` | CDN URLs |
| `local_dir` | `images/{author}/{id}` | Local folder path |
| `posted_fb` | bool | Set to `true` after successful FB post |
| `posted_ig` | bool | Set to `true` after successful IG post |

### Dependencies
- `TikTokApi` (unofficial, uses Playwright/Chromium under the hood)
- `playwright` (with Chromium installed via `python -m playwright install chromium`)
- `httpx` (async image downloading)

### Scheduling
Run via **systemd timer** once per day. Not a long-running daemon.

---

## Module 2: `poster.py` — Facebook + Instagram Publisher

### Purpose
Iterate over posts in `state.json` where `posted_fb` or `posted_ig` is `false` and publish them.

### Facebook Posting Flow
Facebook supports multi-image posts natively:
```
POST /v19.0/{PAGE_ID}/feed
  → message: post title/caption
  → attached_media: [{ media_fbid: ... }, ...]
  (upload each image first via /PAGE_ID/photos?published=false)
```

### Instagram Posting Flow
Instagram carousel requires 3 steps:
```
1. For each image:
   POST /v19.0/{IG_USER_ID}/media
     → image_url: public CDN or hosted URL
     → is_carousel_item: true
   → returns container_id per image

2. POST /v19.0/{IG_USER_ID}/media
     → media_type: CAROUSEL
     → children: [container_id1, container_id2, ...]
     → caption: post title

3. POST /v19.0/{IG_USER_ID}/media_publish
     → creation_id: carousel_container_id
```

### Important Notes
- Instagram requires **publicly accessible image URLs** for upload (local file paths won't work)
- Two options: use the original TikTok CDN URLs (may expire), or self-host images temporarily
- After posting, update `state.json` → set `posted_fb: true` / `posted_ig: true`
- Use `FB_TOKEN` for both Facebook and Instagram (system user token covers both)

### API Version
Use `v19.0` or later for all Meta Graph API calls.

### Dependencies
- `httpx` (async HTTP calls to Meta Graph API)

---

## Module 3: `web/app.py` — Dashboard

### Purpose
A local web UI to monitor and configure the scraper/poster.

### Stack
- **FastAPI** — backend framework
- **Jinja2** — HTML templating (no separate frontend build step)
- **HTMX** — reactive UI without JavaScript framework overhead

### Pages / Features (Planned)
| Route | Purpose |
|---|---|
| `GET /` | Dashboard — show recent posts, posting status |
| `GET /posts` | List all fetched posts with images and status |
| `GET /config` | View/edit `following` list and credentials |
| `POST /config` | Save config changes |
| `POST /posts/{id}/post-now` | Manually trigger posting for a specific post |
| `GET /logs` | Tail of `tikscrap.log` |

### Running
```bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

---

## Environment Setup

```bash
# Clone/enter project
cd ~/projects/tikscrap

# Create and activate venv
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install TikTokApi playwright httpx fastapi uvicorn jinja2 python-multipart

# Install Playwright browser
python -m playwright install chromium
```

### Systemd Services

**Scraper (daily timer):**
```ini
# /etc/systemd/system/tikscrap.service
[Unit]
Description=TikTok Photo Scraper
After=network.target

[Service]
User=tanxim
WorkingDirectory=/home/tanxim/projects/tikscrap
ExecStart=/home/tanxim/projects/tikscrap/venv/bin/python main.py

# /etc/systemd/system/tikscrap.timer
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
```

**Poster (every 3 hours, 8x daily):**
```ini
# /etc/systemd/system/tikscrap-poster.service
[Unit]
Description=TikTok Photo Poster
After=network.target

[Service]
User=tanxim
WorkingDirectory=/home/tanxim/projects/tikscrap
ExecStart=/home/tanxim/projects/tikscrap/venv/bin/python poster.py

# /etc/systemd/system/tikscrap-poster.timer
[Unit]
Description=Run tikscrap poster every 3 hours

[Timer]
OnCalendar=*-*-* 00,03,06,09,12,15,18,21:00:00
Persistent=true

[Install]
WantedBy=timers.target
```
Fires at: 00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 — 8 times per day.
`poster.py` picks **one unposted item per run**, posts it to FB + IG, marks it as posted, and exits.

**Web dashboard (always-on):**
```ini
# /etc/systemd/system/tikscrap-web.service
[Unit]
Description=tikscrap Web Dashboard
After=network.target

[Service]
User=tanxim
WorkingDirectory=/home/tanxim/projects/tikscrap
ExecStart=/home/tanxim/projects/tikscrap/venv/bin/uvicorn web.app:app --host 0.0.0.0 --port 8000
Restart=always
```

---

## Server

- **Provider:** Hetzner
- **RAM:** 4GB (sufficient — Playwright uses ~200–400MB)
- **OS:** Arch Linux
- **Python:** 3.14 (venvs must be recreated after system Python upgrades)

---

## Web Interface Plan

### Auth
- Credentials stored in `config.json` under `dashboard.username` and `dashboard.password`
- On login → set a signed cookie using `itsdangerous`
- Session expires after 24 hours
- Every protected route has a `get_current_user` dependency — redirects to `/login` if cookie missing/invalid
- Logout clears the cookie and redirects to `/login`

```json
"dashboard": {
  "username": "admin",
  "password": "yourpassword"
}
```

---

### Routes

| Route | Method | Page | Purpose |
|---|---|---|---|
| `/login` | GET | Login | Username + password form |
| `/login` | POST | Login | Validate credentials, set session cookie |
| `/logout` | GET | — | Clear session, redirect to `/login` |
| `/` | GET | Dashboard | Overview — stats, recent activity |
| `/posts` | GET | Posts | All fetched posts with images + posting status |
| `/posts/{id}/post-now` | POST | — | Manually trigger FB + IG post for one item |
| `/following` | GET | Following | View + edit the following list in `config.json` |
| `/following/add` | POST | — | Add a username |
| `/following/remove` | POST | — | Remove a username |
| `/logs` | GET | Logs | Tail of `tikscrap.log`, auto-refreshes |
| `/settings` | GET | Settings | Update credentials and config values |
| `/settings` | POST | — | Save settings to `config.json` |
| `/run/fetch` | POST | — | Manually trigger `main.py` |
| `/run/poster` | POST | — | Manually trigger `poster.py` |

---

### Pages

**Dashboard (`/`)**
- Total posts fetched
- Posts pending (not yet posted to FB or IG)
- Posts fully posted today
- Last fetch time and last post time
- Two buttons — Run Fetch Now / Run Poster Now

**Posts (`/posts`)**
- Grid of cards, one per post
- Each card shows: thumbnail of first image, author, title (truncated), date fetched, FB status, IG status
- Post Now button on cards that aren't fully posted
- Filter tabs — All / Pending / Posted

**Following (`/following`)**
- List of current usernames from `config.following`
- Remove button next to each username
- Input field + Add button at the top

**Logs (`/logs`)**
- Last 100 lines of `tikscrap.log`
- Auto-refreshes every 10 seconds via HTMX
- Color coded — INFO grey, ERROR red, WARNING yellow

**Settings (`/settings`)**
- Form fields for: `MS_TOKEN`, `FB_TOKEN`, `FB_PAGE_ID`, `IG_USER_ID`, `BASE_URL`
- Token fields hidden by default with a toggle to reveal
- Change dashboard username and password
- Save button writes directly to `config.json`

---

### Tech Stack (inside FastAPI)
- **Jinja2** — HTML templates
- **HTMX** — auto-refresh logs, dynamic actions without writing JavaScript
- **itsdangerous** — signed session cookies
- **aiofiles** — async static file serving
- No separate JS framework

### Additional Dependencies
```bash
pip install itsdangerous jinja2 aiofiles python-multipart
```

---

## Known Limitations / Gotchas

| Issue | Detail |
|---|---|
| TikTok `ms_token` expiry | Expires periodically; must be refreshed manually from browser cookies |
| TikTok API instability | `TikTokApi` is unofficial and may break after TikTok updates |
| Instagram image hosting | IG carousel upload requires publicly accessible URLs |
| Arch + venv | After `pacman -Syu` upgrades Python, venvs must be deleted and recreated |
| Playwright on Arch | Not officially supported; uses Ubuntu fallback build — functional but shows BEWARE warnings |
| Rate limiting | Avoid polling TikTok more than once per day per channel |
