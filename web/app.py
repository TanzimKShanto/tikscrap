import asyncio
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

import httpx
from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


CONFIG_FILE = Path(__file__).parent.parent / "config.json"
STATE_FILE = Path(__file__).parent.parent / "state.json"
LOG_FILE = Path(__file__).parent.parent / "tikscrap.log"
IMAGES_DIR = Path(__file__).parent.parent / "images"

SECRET_KEY = "tikscrap-secret-key-change-in-production"
SESSION_MAX_AGE = 24 * 60 * 60

app = FastAPI()
# === Templates setup (Fixed) ===
templates_path = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

# Fix for "unhashable type: 'dict'" error
templates.env.cache = {}  # Reset cache
templates.env.autoescape = True
templates.env.globals["url_for"] = app.url_path_for
serializer = URLSafeTimedSerializer(SECRET_KEY)

IMAGES_DIR.mkdir(exist_ok=True)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

API_VERSION = "v19.0"


# ── Helpers ───────────────────────────────────────────────────────────────────


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"following": [], "seen_ids": [], "posts": []}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Auth ──────────────────────────────────────────────────────────────────────


def get_session_user(request: Request) -> str | None:
    cookie = request.cookies.get("session")
    if not cookie:
        return None
    try:
        return serializer.loads(cookie, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def require_auth(request: Request) -> str:
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return user


# ── Auth routes ───────────────────────────────────────────────────────────────


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    config = load_config()
    dashboard = config.get("dashboard", {})
    if username == dashboard.get("username", "admin") and password == dashboard.get(
        "password", "admin"
    ):
        cookie = serializer.dumps(username)
        response = RedirectResponse("/", status_code=302)
        response.set_cookie("session", cookie, max_age=SESSION_MAX_AGE, httponly=True)
        return response
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Invalid credentials"}
    )


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session")
    return response


# ── Dashboard ─────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, user: str = Depends(require_auth)):
    state = load_state()
    posts = state.get("posts", [])

    total_posts = len(posts)
    pending = sum(1 for p in posts if not p.get("posted_fb") or not p.get("posted_ig"))
    today = datetime.now().strftime("%Y-%m-%d")
    posted_today = sum(
        1
        for p in posts
        if p.get("posted_fb")
        and p.get("posted_ig")
        and p.get("posted_at", "").startswith(today)
    )

    last_fetch = None
    last_post = None
    for p in reversed(posts):
        if last_fetch is None:
            last_fetch = p.get("fetched_at")
        if last_post is None and p.get("posted_fb") and p.get("posted_ig"):
            last_post = p.get("posted_at")
        if last_fetch and last_post:
            break

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "total_posts": total_posts,
            "pending": pending,
            "posted_today": posted_today,
            "last_fetch": last_fetch,
            "last_post": last_post,
        },
    )


# ── Posts ─────────────────────────────────────────────────────────────────────


@app.get("/posts", response_class=HTMLResponse)
def posts_page(
    request: Request,
    filter: str = "all",
    page: int = 1,
    user: str = Depends(require_auth),
):
    state = load_state()
    posts = state.get("posts", [])
    config = load_config()
    base_url = config.get("BASE_URL", "")

    if filter == "pending":
        posts = [p for p in posts if not p.get("posted_fb") or not p.get("posted_ig")]
    elif filter == "posted":
        posts = [p for p in posts if p.get("posted_fb") and p.get("posted_ig")]

    posts = sorted(posts, key=lambda p: p.get("fetched_at", ""), reverse=True)

    POSTS_PER_PAGE = 20
    total_posts = len(posts)
    total_pages = (total_posts + POSTS_PER_PAGE - 1) // POSTS_PER_PAGE
    start = (page - 1) * POSTS_PER_PAGE
    end = start + POSTS_PER_PAGE
    paginated_posts = posts[start:end]

    for p in paginated_posts:
        if p.get("image_urls"):
            p["thumbnail"] = f"{base_url}/images/{p['author']}/{p['id']}/0.jpg"

    return templates.TemplateResponse(
        "posts.html",
        {
            "request": request,
            "user": user,
            "posts": paginated_posts,
            "filter": filter,
            "page": page,
            "total_pages": total_pages,
            "total_posts": total_posts,
            "page_range": list(range(1, total_pages + 1)),
        },
    )


@app.post("/posts/{post_id}/post-now")
async def post_now(post_id: str, user: str = Depends(require_auth)):
    state = load_state()
    config = load_config()

    target = next((p for p in state["posts"] if p["id"] == post_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Post not found")

    base_url = config.get("BASE_URL", "")
    fb_token = config["FB_TOKEN"]
    fb_page_id = config["FB_PAGE_ID"]
    ig_user_id = config["IG_USER_ID"]

    author = target["author"]
    title = target.get("title", "")
    caption = f"{title}\n\nCredited by @{author} - TikTok"
    image_urls = [
        f"{base_url}/images/{author}/{post_id}/{i}.jpg"
        for i in range(len(target.get("image_urls", [])))
    ]

    async with httpx.AsyncClient() as client:
        # Facebook
        if not target.get("posted_fb"):
            media_ids = []
            for url in image_urls:
                r = await client.post(
                    f"https://graph.facebook.com/{API_VERSION}/{fb_page_id}/photos",
                    params={"url": url, "published": "false", "access_token": fb_token},
                    timeout=60,
                )
                if r.status_code == 200:
                    media_ids.append(r.json().get("id"))

            if media_ids:
                r = await client.post(
                    f"https://graph.facebook.com/{API_VERSION}/{fb_page_id}/feed",
                    data={
                        "message": caption,
                        "attached_media": json.dumps(
                            [{"media_fbid": mid} for mid in media_ids]
                        ),
                        "access_token": fb_token,
                    },
                    timeout=60,
                )
                target["posted_fb"] = r.status_code == 200

        # Instagram
        if not target.get("posted_ig"):
            container_ids = []
            for url in image_urls:
                r = await client.post(
                    f"https://graph.facebook.com/{API_VERSION}/{ig_user_id}/media",
                    params={
                        "image_url": url,
                        "is_carousel_item": "true",
                        "access_token": fb_token,
                    },
                    timeout=60,
                )
                if r.status_code == 200:
                    container_ids.append(r.json().get("id"))

            if container_ids:
                await asyncio.sleep(5)  # wait for containers to be ready

                r = await client.post(
                    f"https://graph.facebook.com/{API_VERSION}/{ig_user_id}/media",
                    params={
                        "media_type": "CAROUSEL",
                        "children": ",".join(container_ids),
                        "caption": caption,
                        "access_token": fb_token,
                    },
                    timeout=60,
                )
                if r.status_code == 200:
                    carousel_id = r.json().get("id")
                    r = await client.post(
                        f"https://graph.facebook.com/{API_VERSION}/{ig_user_id}/media_publish",
                        params={"creation_id": carousel_id, "access_token": fb_token},
                        timeout=60,
                    )
                    target["posted_ig"] = r.status_code == 200

    if target.get("posted_fb") and target.get("posted_ig"):
        target["posted_at"] = datetime.now().isoformat()

    save_state(state)
    return RedirectResponse("/posts", status_code=302)


# ── Following ─────────────────────────────────────────────────────────────────


@app.get("/following", response_class=HTMLResponse)
def following_page(request: Request, user: str = Depends(require_auth)):
    config = load_config()
    following = config.get("following", [])
    return templates.TemplateResponse(
        "following.html",
        {
            "request": request,
            "user": user,
            "following": following,
        },
    )


@app.post("/following/add")
def following_add(
    username: str = Form(...),
    user: str = Depends(require_auth),
):
    username = username.strip()
    if username:
        config = load_config()
        config.setdefault("following", [])
        if username not in config["following"]:
            config["following"].append(username)
            save_config(config)
    return RedirectResponse("/following", status_code=302)


@app.post("/following/remove")
def following_remove(
    username: str = Form(...),
    user: str = Depends(require_auth),
):
    config = load_config()
    if username in config.get("following", []):
        config["following"].remove(username)
        save_config(config)
    return RedirectResponse("/following", status_code=302)


# ── Logs ──────────────────────────────────────────────────────────────────────


@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, user: str = Depends(require_auth)):
    logs = []
    if LOG_FILE.exists():
        with open(LOG_FILE) as f:
            logs = [line.rstrip() for line in f.readlines()[-100:]]
    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "user": user,
            "logs": logs,
        },
    )


# ── Settings ──────────────────────────────────────────────────────────────────


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: str = Depends(require_auth)):
    config = load_config()
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "config": config,
        },
    )


@app.post("/settings")
def settings_save(
    ms_token: str = Form(""),
    fb_token: str = Form(""),
    fb_page_id: str = Form(""),
    ig_user_id: str = Form(""),
    base_url: str = Form(""),
    dashboard_username: str = Form(""),
    dashboard_password: str = Form(""),
    user: str = Depends(require_auth),
):
    config = load_config()

    if ms_token:
        config["MS_TOKEN"] = ms_token
    if fb_token:
        config["FB_TOKEN"] = fb_token
    if fb_page_id:
        config["FB_PAGE_ID"] = fb_page_id
    if ig_user_id:
        config["IG_USER_ID"] = ig_user_id
    if base_url:
        config["BASE_URL"] = base_url

    if dashboard_username or dashboard_password:
        config.setdefault("dashboard", {})
        if dashboard_username:
            config["dashboard"]["username"] = dashboard_username
        if dashboard_password:
            config["dashboard"]["password"] = dashboard_password

    save_config(config)
    return RedirectResponse("/settings", status_code=302)


# ── Manual triggers ───────────────────────────────────────────────────────────


@app.post("/run/fetch")
def run_fetch(user: str = Depends(require_auth)):
    subprocess.Popen([sys.executable, str(Path(__file__).parent.parent / "main.py")])
    return RedirectResponse("/", status_code=302)


@app.post("/run/poster")
def run_poster(user: str = Depends(require_auth)):
    subprocess.Popen([sys.executable, str(Path(__file__).parent.parent / "poster.py")])
    return RedirectResponse("/", status_code=302)
