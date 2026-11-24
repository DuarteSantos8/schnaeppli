"""Authenticated, signed image proxy.

Listing photos are served from our own origin so the browser never contacts
marketplace CDNs (privacy, strict CSP). Only URLs the server itself signed when
it emitted a listing are served, so this can't be used as an open proxy or to
reach internal addresses (safe_http also blocks those). Images are downscaled
and re-encoded as WebP, which also strips EXIF/metadata.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
from collections import OrderedDict
from functools import lru_cache
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.deps import current_user
from app.core.safe_http import fetch_image
from app.core.security import secret_box
from app.models import User

router = APIRouter(tags=["images"])
WIDTHS = (160, 320, 480, 640, 960, 1280)


class _ByteLRU:
    """Small in-process cache of resized images, bounded by total bytes.

    Without it every new tab or device re-downloads the original from the
    marketplace and re-encodes it, which is most of what made the feed feel slow.
    """

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.size = 0
        self.items: OrderedDict[str, bytes] = OrderedDict()

    def get(self, key: str) -> bytes | None:
        v = self.items.get(key)
        if v is not None:
            self.items.move_to_end(key)
        return v

    def put(self, key: str, value: bytes) -> None:
        if len(value) > self.max_bytes // 8:
            return
        old = self.items.pop(key, None)
        if old is not None:
            self.size -= len(old)
        self.items[key] = value
        self.size += len(value)
        while self.size > self.max_bytes:
            _, v = self.items.popitem(last=False)
            self.size -= len(v)


_cache = _ByteLRU(48 * 1024 * 1024)
_inflight: dict[str, asyncio.Future[bytes | None]] = {}


@lru_cache
def _key() -> bytes:
    # Derived from the current encryption key; a separate purpose string keeps it distinct.
    k = next(iter(secret_box()._keys.values()))
    return hmac.new(k, b"schnaeppli-image-proxy-v1", hashlib.sha256).digest()


def sign(url: str) -> str:
    return hmac.new(_key(), url.encode(), hashlib.sha256).hexdigest()[:32]


def proxied(url: str | None) -> str | None:
    if not url or not url.startswith("https://"):
        return None
    return f"/api/img?u={quote(url, safe='')}&s={sign(url)}"


def _resize(data: bytes, width: int) -> bytes:
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        if im.width > width:
            im.thumbnail((width, width * 4))
        out = io.BytesIO()
        im.save(out, "WEBP", quality=80, method=4)
        return out.getvalue()


async def _load(u: str, width: int) -> bytes:
    got = await fetch_image(u, max_bytes=8_000_000)
    if got is None:
        raise HTTPException(404, "Image unavailable")
    try:
        body = await asyncio.to_thread(_resize, got[0], width)
    except Exception as e:  # corrupt or unsupported image
        raise HTTPException(415, "Unsupported image") from e
    _cache.put(f"{width}:{sign(u)}", body)
    return body


@router.get("/api/img")
async def image(
    u: str = Query(max_length=2000),
    s: str = Query(max_length=64),
    w: int = Query(640),
    user: User = Depends(current_user),
):
    if not hmac.compare_digest(sign(u), s):
        raise HTTPException(404, "Not found")
    width = min(WIDTHS, key=lambda x: abs(x - w))
    key = f"{width}:{s}"
    body = _cache.get(key)
    if body is None:
        if key in _inflight:  # the same photo is already being fetched for another card
            body = await asyncio.shield(_inflight[key])
        else:
            fut: asyncio.Future[bytes | None] = asyncio.get_running_loop().create_future()
            _inflight[key] = fut
            try:
                body = await _load(u, width)
                fut.set_result(body)
            except BaseException:
                fut.set_result(None)
                raise
            finally:
                _inflight.pop(key, None)
        if body is None:
            raise HTTPException(404, "Image unavailable")
    return Response(
        body,
        media_type="image/webp",
        headers={
            "Cache-Control": "private, max-age=604800, immutable",
            "Content-Security-Policy": "default-src 'none'",
        },
    )
