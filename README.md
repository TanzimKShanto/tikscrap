# tikscrap

Automated TikTok content scraper that fetches photo posts and reposts them to Facebook and Instagram.

## Features

- **TikTok Scraper**: Fetches photo posts (slideshows) from followed accounts
- **Auto-Poster**: Reposts content to Facebook and Instagram via Meta Graph API
- **Web Dashboard**: FastAPI-based UI for monitoring and configuration
- **HTMX Enabled**: Reactive UI without JavaScript framework overhead

## Project Structure

```
tikscrap/
├── main.py              # TikTok scraper
├── poster.py           # Facebook + Instagram poster
├── config.json         # Credentials and settings
├── state.json          # Runtime state (posts, seen IDs)
├── tikscrap.log        # Log file
├── images/            # Downloaded images
│   └── {username}/
│       └── {post_id}/
├── web/
│   ├── app.py         # FastAPI dashboard
│   └── templates/    # Jinja2 templates
└── venv/            # Python virtual environment
```

## Prerequisites

- Python 3.14+
- Chromium browser (for Playwright)

## Setup

```bash
# Clone and enter project
cd ~/projects/tikscrap

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install TikTokApi playwright httpx fastapi uvicorn jinja2 python-multipart itsdangerous

# Install Playwright browser
python -m playwright install chromium
```

## Configuration

Edit `config.json` with your credentials:

```json
{
  "MS_TOKEN": "your_tiktok_ms_token",
  "FB_TOKEN": "your_meta_system_user_token",
  "FB_PAGE_ID": "945560738650895",
  "IG_USER_ID": "your_instagram_user_id",
  "BASE_URL": "http://your-server:8000",
  "following": ["username1", "username2"],
  "dashboard": {
    "username": "admin",
    "password": "yourpassword"
  }
}
```

### Getting Credentials

- **MS_TOKEN**: Extract from TikTok browser cookies
- **FB_TOKEN**: Meta system user token (never expires)
- **FB_PAGE_ID**: Your Facebook Page ID
- **IG_USER_ID**: Your Instagram Business Account ID

## Usage

### Run Scraper (daily)

```bash
python main.py
```

### Run Poster (every 3 hours)

```bash
python poster.py
```

### Run Web Dashboard

```bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000` in your browser.

## Web Dashboard

| Route | Description |
|-------|-------------|
| `/` | Dashboard with stats and quick actions |
| `/posts` | View all posts, filter by status, manually post |
| `/following` | Manage followed accounts |
| `/logs` | View system logs |
| `/settings` | Update credentials |
| `/login` | Authentication |

## Systemd Setup (Production)

### Scraper (daily at midnight)

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

### Poster (every 3 hours)

```ini
# /etc/systemd/system/tikscrap-poster.timer
[Timer]
OnCalendar=*-*-* 00,03,06,09,12,15,18,21:00:00
```

### Web Dashboard (always-on)

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

## Tech Stack

- **TikTokApi**: Unofficial TikTok API
- **Playwright**: Browser automation
- **FastAPI**: Web framework
- **Jinja2**: Templating
- **HTMX**: Reactive UI
- **Tailwind CSS**: Styling
- **Meta Graph API**: Facebook & Instagram posting

## License

MIT