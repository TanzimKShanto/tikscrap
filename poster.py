import asyncio
import json
import httpx
import logging
from pathlib import Path
from datetime import datetime, timezone

CONFIG_FILE = Path("config.json")
STATE_FILE = Path("state.json")
LOG_FILE = Path("tikscrap.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

API_VERSION = "v25.0"


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_state() -> dict:
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def upload_photo_to_facebook(
    client: httpx.AsyncClient,
    page_id: str,
    access_token: str,
    image_url: str,
) -> str | None:
    url = f"https://graph.facebook.com/{API_VERSION}/{page_id}/photos"
    params = {
        "url": image_url,
        "published": "false",
        "access_token": access_token,
    }
    try:
        r = await client.post(url, params=params, timeout=60)
        r.raise_for_status()
        media_id = r.json().get("id")
        log.info(f"  ↑ FB uploaded: {media_id}")
        return media_id
    except Exception as e:
        log.error(f"  ✗ FB upload failed: {e}")
        return None


async def post_to_facebook(
    client: httpx.AsyncClient,
    page_id: str,
    access_token: str,
    message: str,
    media_ids: list[str],
) -> str | None:
    url = f"https://graph.facebook.com/{API_VERSION}/{page_id}/feed"
    attached_media = [{"media_fbid": mid} for mid in media_ids]
    data = {
        "message": message,
        "attached_media": json.dumps(attached_media),
        "access_token": access_token,
    }
    try:
        r = await client.post(url, data=data, timeout=60)
        r.raise_for_status()
        post_id = r.json().get("id")
        log.info(f"  ✔ FB posted: {post_id}")
        return post_id
    except Exception as e:
        log.error(f"  ✗ FB post failed: {e}")
        return None


async def upload_to_instagram(
    client: httpx.AsyncClient,
    ig_user_id: str,
    access_token: str,
    image_url: str,
    retries: int = 3,
) -> str | None:
    for attempt in range(retries):
        if attempt > 0:
            wait = attempt * 5
            log.info(f"  ↻ IG retry {attempt}/{retries - 1}, waiting {wait}s...")
            await asyncio.sleep(wait)

        url = f"https://graph.facebook.com/{API_VERSION}/{ig_user_id}/media"
        params = {
            "image_url": image_url,
            "is_carousel_item": "true",
            "access_token": access_token,
        }
        try:
            r = await client.post(url, params=params, timeout=60)
            if r.status_code == 200:
                container_id = r.json().get("id")
                log.info(f"  ↑ IG uploaded carousel item: {container_id}")
                return container_id
            log.warning(f"  ↻ IG attempt {attempt + 1} failed: {r.status_code}")
        except Exception as e:
            log.warning(f"  ↻ IG attempt {attempt + 1} exception: {e}")

    log.error(f"  ✗ IG upload failed after {retries} attempts")
    return None


async def create_instagram_carousel(
    client: httpx.AsyncClient,
    ig_user_id: str,
    access_token: str,
    container_ids: list[str],
    caption: str,
) -> str | None:
    url = f"https://graph.facebook.com/{API_VERSION}/{ig_user_id}/media"
    params = {
        "media_type": "CAROUSEL",
        "children": ",".join(container_ids),
        "caption": caption,
        "access_token": access_token,
    }
    try:
        r = await client.post(url, params=params, timeout=60)
        r.raise_for_status()
        carousel_id = r.json().get("id")
        log.info(f"  ↑ IG carousel created: {carousel_id}")
        return carousel_id
    except Exception as e:
        log.error(f"  ✗ IG carousel failed: {e}")
        return None


async def publish_instagram_carousel(
    client: httpx.AsyncClient,
    ig_user_id: str,
    access_token: str,
    creation_id: str,
) -> str | None:
    url = f"https://graph.facebook.com/{API_VERSION}/{ig_user_id}/media_publish"
    params = {
        "creation_id": creation_id,
        "access_token": access_token,
    }
    try:
        r = await client.post(url, params=params, timeout=60)
        r.raise_for_status()
        post_id = r.json().get("id")
        log.info(f"  ✔ IG posted: {post_id}")
        return post_id
    except Exception as e:
        log.error(f"  ✗ IG publish failed: {e}")
        return None


async def post_to_instagram(
    client: httpx.AsyncClient,
    ig_user_id: str,
    access_token: str,
    image_urls: list[str],
    caption: str,
) -> str | None:
    container_ids = []
    for url in image_urls:
        container_id = await upload_to_instagram(client, ig_user_id, access_token, url)
        if not container_id:
            return None
        container_ids.append(container_id)
        await asyncio.sleep(1.5)

    # Wait for Meta to finish processing containers before creating carousel
    log.info("  ⏳ waiting for IG containers to be ready...")
    await asyncio.sleep(8)

    carousel_id = await create_instagram_carousel(
        client, ig_user_id, access_token, container_ids, caption
    )
    if not carousel_id:
        return None

    return await publish_instagram_carousel(
        client, ig_user_id, access_token, carousel_id
    )


async def main():
    log.info("═" * 50)
    log.info("poster run started")

    config = load_config()
    state = load_state()

    fb_token = config["FB_TOKEN"]
    fb_page_id = config["FB_PAGE_ID"]
    ig_user_id = config["IG_USER_ID"]

    unposted = [
        p for p in state["posts"] if not p.get("posted_fb") or not p.get("posted_ig")
    ]

    if not unposted:
        log.info("No unposted items found.")
        log.info("═" * 50)
        return

    post = unposted[0]
    post_id = post["id"]
    author = post["author"]
    title = post.get("title", "")
    title = f"{title}\n\nPost Credit: @{author} - TikTok"
    BASE_URL = config["BASE_URL"]
    # image_urls = post.get("image_urls", [])
    image_urls = [
        f"{BASE_URL}/images/{post['author']}/{post['id']}/{i}.jpeg"
        for i in range(len(post["image_urls"]))
    ]

    log.info(f'Processing post {post_id} by @{author} — "{title[:60]}"')

    async with httpx.AsyncClient() as client:
        fb_posted = post.get("posted_fb", False)
        ig_posted = post.get("posted_ig", False)

        if image_urls and not fb_posted:
            log.info("Posting to Facebook...")
            media_ids = []
            for url in image_urls:
                media_id = await upload_photo_to_facebook(
                    client, fb_page_id, fb_token, url
                )
                if media_id:
                    media_ids.append(media_id)

            if media_ids:
                fb_result = await post_to_facebook(
                    client, fb_page_id, fb_token, title, media_ids
                )
                fb_posted = bool(fb_result)

        if image_urls and not ig_posted:
            log.info("Posting to Instagram...")
            ig_result = await post_to_instagram(
                client, ig_user_id, fb_token, image_urls, title
            )
            ig_posted = bool(ig_result)

    for p in state["posts"]:
        if p["id"] == post_id:
            p["posted_fb"] = fb_posted
            p["posted_ig"] = ig_posted
            if fb_posted and ig_posted:
                p["posted_at"] = now_iso()
            break

    save_state(state)

    log.info(f"Done. FB: {fb_posted}, IG: {ig_posted}")
    log.info("═" * 50)


if __name__ == "__main__":
    asyncio.run(main())
