import asyncio
import json
import httpx
import logging
from pathlib import Path
from datetime import datetime, timezone
from TikTokApi import TikTokApi

# ── Config ────────────────────────────────────────────────────────────────────
CONFIG_FILE = Path("config.json")
STATE_FILE = Path("state.json")
IMAGES_DIR = Path("images")
LOG_FILE = Path("tikscrap.log")

FOLLOWING_OF = "vuant01"  # whose following list to track
FETCH_COUNT = 10  # posts to fetch per user per run

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────
def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"following": [], "seen_ids": [], "posts": []}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def download_image(client: httpx.AsyncClient, url: str, dest: Path):
    """Download a single image; skip if already on disk."""
    if dest.exists():
        return
    try:
        r = await client.get(url, timeout=30, follow_redirects=True)
        r.raise_for_status()
        dest.write_bytes(r.content)
        log.info(f"  ↓ saved {dest.name}")
    except Exception as e:
        log.warning(f"  ✗ failed to download {url}: {e}")


# ── Core tasks ────────────────────────────────────────────────────────────────
# async def refresh_following(api: TikTokApi) -> list[str]:
#     """Fetch the accounts that FOLLOWING_OF follows."""
#     log.info(f"Fetching following list of @{FOLLOWING_OF} ...")
#     usernames = []
#     try:
#         user = api.user(username=FOLLOWING_OF)
#         async for account in user.following(count=100):
#             data = account.as_dict
#             username = (
#                 data.get("uniqueId")
#                 or data.get("user", {}).get("uniqueId")
#                 or data.get("username")
#             )
#             if username:
#                 usernames.append(username)
#     except Exception as e:
#         log.error(f"Could not fetch following list: {e}")
#     log.info(f"Found {len(usernames)} accounts in following list.")
#     return usernames


async def fetch_user_photo_posts(
    api: TikTokApi,
    http: httpx.AsyncClient,
    username: str,
    seen_ids: set,
) -> list[dict]:
    """Fetch up to FETCH_COUNT photo posts from a user, skipping seen ones."""
    new_posts = []
    log.info(f"Checking @{username} ...")
    try:
        user = api.user(username=username)
        async for video in user.videos(count=FETCH_COUNT):
            data = video.as_dict
            post_id = data.get("id")
            post_title = data.get("desc")

            if not post_id or post_id in seen_ids:
                continue

            if "imagePost" not in data:
                continue  # not a photo/slideshow post

            images_meta = data["imagePost"].get("images", [])
            image_urls = [
                img["imageURL"]["urlList"][0]
                for img in images_meta
                if img.get("imageURL", {}).get("urlList")
            ]

            if not image_urls:
                continue

            # Download images
            post_dir = IMAGES_DIR / username / post_id
            post_dir.mkdir(parents=True, exist_ok=True)

            tasks = [
                download_image(http, url, post_dir / f"{i}.jpeg")
                for i, url in enumerate(image_urls)
            ]
            await asyncio.gather(*tasks)

            post_record = {
                "id": post_id,
                "author": username,
                "title": post_title,
                "fetched_at": now_iso(),
                "image_urls": image_urls,
                "local_dir": str(post_dir),
            }
            new_posts.append(post_record)
            seen_ids.add(post_id)
            log.info(f"  ✔ new photo post {post_id} ({len(image_urls)} images)")

    except Exception as e:
        log.error(f"Error fetching @{username}: {e}")

    return new_posts


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    log.info("═" * 50)
    log.info("tikscrap run started")

    config = load_config()
    ms_token = config["MS_TOKEN"]

    state = load_state()
    seen_ids = set(state.get("seen_ids", []))

    IMAGES_DIR.mkdir(exist_ok=True)

    async with TikTokApi() as api:
        await api.create_sessions(ms_tokens=[ms_token], num_sessions=1)

        # 1. Refresh following list
        # following = await refresh_following(api)
        following = config.get("following", [])
        if not following:
            log.warning("Following list is empty — using cached list from state.")
            following = state.get("following", [])
        state["following"] = following

        # 2. Fetch photo posts from each followed account
        async with httpx.AsyncClient() as http:
            for username in following:
                new_posts = await fetch_user_photo_posts(api, http, username, seen_ids)
                state["posts"].extend(new_posts)

    # 3. Persist state
    state["seen_ids"] = list(seen_ids)
    save_state(state)

    total_new = sum(1 for p in state["posts"] if p["fetched_at"][:10] == now_iso()[:10])
    log.info(f"Done. {total_new} new photo post(s) found today.")
    log.info("═" * 50)


if __name__ == "__main__":
    asyncio.run(main())
