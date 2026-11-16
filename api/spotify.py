#!/usr/bin/env python3
"""Build a stylized SVG of the current or last Spotify track."""

from __future__ import annotations

import argparse
import os
import random
import sys
import xml.sax.saxutils
from base64 import b64encode
from http.server import BaseHTTPRequestHandler
from io import BytesIO
from pathlib import Path

import requests
from colorthief import ColorThief
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_SECRET_ID = os.getenv("SPOTIFY_SECRET_ID")
SPOTIFY_REFRESH_TOKEN = os.getenv("SPOTIFY_REFRESH_TOKEN")

REFRESH_TOKEN_URL = "https://accounts.spotify.com/api/token"
NOW_PLAYING_URL = "https://api.spotify.com/v1/me/player/currently-playing"
RECENTLY_PLAYING_URL = "https://api.spotify.com/v1/me/player/recently-played?limit=10"

DEFAULT_BAR_PALETTE = ((29, 185, 84), (32, 189, 255), (171, 102, 255), (84, 51, 255))
DEFAULT_SONG_PALETTE = ((234, 234, 234), (29, 185, 84))
SPOTIFY_ICON = (
    "M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 "
    "17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122"
    "-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32"
    ".42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98"
    "-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141"
    "C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 "
    "8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 "
    "4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02"
    ".599-1.559.3z"
)


def _esc(value: str) -> str:
    return xml.sax.saxutils.escape(value or "")


def _rgb(color: tuple[int, int, int]) -> str:
    return f"rgb({color[0]},{color[1]},{color[2]})"


def refresh_access_token() -> str:
    if not all([SPOTIFY_CLIENT_ID, SPOTIFY_SECRET_ID, SPOTIFY_REFRESH_TOKEN]):
        raise RuntimeError(
            "Missing SPOTIFY_CLIENT_ID, SPOTIFY_SECRET_ID or SPOTIFY_REFRESH_TOKEN"
        )
    auth = b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_SECRET_ID}".encode()).decode("ascii")
    response = requests.post(
        REFRESH_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": SPOTIFY_REFRESH_TOKEN,
        },
        headers={"Authorization": f"Basic {auth}"},
        timeout=30,
    )
    payload = response.json()
    if "access_token" not in payload:
        raise RuntimeError(f"Spotify token refresh failed: {payload}")
    return payload["access_token"]


def spotify_get(url: str, token: str) -> tuple[int, dict | None]:
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code == 204:
        return 204, None
    if response.status_code == 401:
        token = refresh_access_token()
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.status_code == 204:
            return 204, None
    response.raise_for_status()
    return response.status_code, response.json()


def load_track() -> tuple[dict, str]:
    token = refresh_access_token()
    status, data = spotify_get(NOW_PLAYING_URL, token)
    if status == 200 and data and data.get("item"):
        return data["item"], "Vibing to"
    _, recent = spotify_get(RECENTLY_PLAYING_URL, token)
    items = (recent or {}).get("items") or []
    if not items:
        raise RuntimeError("No currently playing or recently played tracks")
    item = random.choice(items)["track"]
    return item, "Recently played"


def load_image_b64(url: str) -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return b64encode(response.content).decode("ascii")


def palettes_from_image(url: str) -> tuple[list, list]:
    try:
        content = requests.get(url, timeout=30).content
        thief = ColorThief(BytesIO(content))
        bar = thief.get_palette(4) or list(DEFAULT_BAR_PALETTE)
        song = thief.get_palette(2) or list(DEFAULT_SONG_PALETTE)
        while len(bar) < 4:
            bar.append(DEFAULT_BAR_PALETTE[len(bar)])
        while len(song) < 2:
            song.append(DEFAULT_SONG_PALETTE[len(song)])
        return bar[:4], song[:2]
    except Exception:
        return list(DEFAULT_BAR_PALETTE), list(DEFAULT_SONG_PALETTE)


def render_bars(bar_palette: list) -> str:
    bars = []
    x = 128
    for index in range(18):
        duration = round(random.uniform(0.45, 1.1), 2)
        delay = round(random.uniform(0, 0.8), 2)
        color = _rgb(bar_palette[index % len(bar_palette)])
        bars.append(
            f'<rect x="{x}" y="104" width="3" height="12" rx="1" fill="{color}">'
            f'<animate attributeName="height" values="3;14;3" dur="{duration}s" '
            f'begin="{delay}s" repeatCount="indefinite"/>'
            f'<animate attributeName="y" values="113;102;113" dur="{duration}s" '
            f'begin="{delay}s" repeatCount="indefinite"/>'
            "</rect>"
        )
        x += 6
    return "\n".join(bars)


def render_svg(track: dict, status: str) -> str:
    images = track.get("album", {}).get("images") or []
    image_url = images[1]["url"] if len(images) > 1 else (images[0]["url"] if images else "")
    cover = load_image_b64(image_url) if image_url else ""
    bar_palette, song_palette = palettes_from_image(image_url) if image_url else (
        list(DEFAULT_BAR_PALETTE),
        list(DEFAULT_SONG_PALETTE),
    )

    song = _esc(track.get("name") or "Unknown track")
    artist = _esc((track.get("artists") or [{}])[0].get("name") or "Unknown artist")
    cover_tag = (
        f'<image href="data:image/jpeg;base64,{cover}" x="16" y="16" width="100" '
        'height="100" clip-path="url(#cover)" preserveAspectRatio="xMidYMid slice"/>'
        if cover
        else '<rect x="16" y="16" width="100" height="100" rx="8" fill="#222"/>'
    )

    return f"""<svg width="480" height="133" viewBox="0 0 480 133" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="title" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="{_rgb(song_palette[0])}"/>
      <stop offset="100%" stop-color="{_rgb(song_palette[1])}"/>
    </linearGradient>
    <clipPath id="cover">
      <rect x="16" y="16" width="100" height="100" rx="8"/>
    </clipPath>
  </defs>
  <rect width="480" height="133" rx="8" fill="#181414"/>
  {cover_tag}
  <path transform="translate(444,14) scale(0.9)" fill="#1DB954" d="{SPOTIFY_ICON}"/>
  <text x="132" y="36" fill="#8f8f8f" font-size="12" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{_esc(status)}</text>
  <text x="132" y="64" fill="url(#title)" font-size="22" font-weight="700" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{song}</text>
  <text x="132" y="90" fill="#c8c8c8" font-size="16" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{artist}</text>
  {render_bars(bar_palette)}
</svg>
"""


def fallback_svg(message: str = "Spotify is quiet right now") -> str:
    return f"""<svg width="480" height="133" viewBox="0 0 480 133" xmlns="http://www.w3.org/2000/svg">
  <rect width="480" height="133" rx="8" fill="#181414"/>
  <path transform="translate(24,42) scale(2)" fill="#1DB954" d="{SPOTIFY_ICON}"/>
  <text x="100" y="62" fill="#f2f2f2" font-size="20" font-weight="700" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">Don't forget to METAL</text>
  <text x="100" y="88" fill="#1DB954" font-size="14" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{_esc(message)}</text>
</svg>
"""


def build_svg() -> str:
    try:
        track, status = load_track()
        return render_svg(track, status)
    except Exception as err:
        print(f"Spotify card fallback: {err}", file=sys.stderr)
        return fallback_svg()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        svg = build_svg().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Cache-Control", "s-maxage=60, stale-while-revalidate")
        self.send_header("Content-Length", str(len(svg)))
        self.end_headers()
        self.wfile.write(svg)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="assets/spotify.svg")
    args = parser.parse_args()
    svg = build_svg()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
