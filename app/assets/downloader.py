"""Image downloader — saves platform images to local asset library."""
from __future__ import annotations

import hashlib
import mimetypes
from datetime import datetime
from pathlib import Path

import aiohttp

from app.core.config import get_settings
from app.core.logger import logger


async def download_images(
    urls: list[str],
    platform: str,
    content_id: str,
) -> list[str]:
    """Download images and return list of local paths."""
    if not urls:
        return []

    s = get_settings()
    today = datetime.utcnow().strftime("%Y/%m/%d")
    dest_dir = s.assets_path / platform / today
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    async with aiohttp.ClientSession() as session:
        for url in urls:
            try:
                local = await _download_one(session, url, dest_dir, content_id)
                if local:
                    saved.append(local)
            except Exception as e:
                logger.warning(f"Failed to download image {url}: {e}")

    logger.info(f"Downloaded {len(saved)}/{len(urls)} images → {dest_dir}")
    return saved


async def _download_one(
    session: aiohttp.ClientSession,
    url: str,
    dest_dir: Path,
    content_id: str,
) -> str | None:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        if resp.status != 200:
            return None
        data = await resp.read()

    # deterministic filename
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    ext = _guess_ext(resp.headers.get("content-type", ""), url)
    fname = f"{content_id[:12]}_{url_hash}{ext}"
    path = dest_dir / fname
    path.write_bytes(data)
    logger.debug(f"Saved image → {path}")
    return str(path)


def _guess_ext(content_type: str, url: str) -> str:
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
    if ext and ext in (".jpeg", ".jpg", ".png", ".gif", ".webp"):
        return ext
    # fallback: infer from URL
    for candidate in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        if candidate in url.lower():
            return candidate
    return ".jpg"
