#!/usr/bin/env python3
"""
Shazam to MP3 downloader.
Reads Shazam links, extracts artist/title, downloads from YouTube via yt-dlp.

Usage:
  python shazam2mp3.py links.txt -o ./music
  python shazam2mp3.py links.txt -o ./music --format flac
  echo "https://www.shazam.com/track/123" | python shazam2mp3.py - -o ./music

Requires: pip install yt-dlp requests
Also needs ffmpeg installed for audio conversion.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests


def extract_track_info(url):
    """Extract artist and title from a Shazam URL."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ✗ Failed to fetch {url}: {e}", file=sys.stderr)
        return None

    html = resp.text

    # Try JSON-LD first (most reliable)
    for match in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL
    ):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and data.get("@type") == "MusicRecording":
                title = data.get("name")
                artist = data.get("byArtist")
                if isinstance(artist, dict):
                    artist = artist.get("name")
                if title and artist:
                    return {"artist": artist, "title": title, "url": url}
        except (json.JSONDecodeError, AttributeError):
            pass

    # Fallback: og:title (format: "Title - Artist: ...")
    og_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
    if og_match:
        raw = og_match.group(1).split(":")[0].strip()
        if " - " in raw:
            title, artist = raw.split(" - ", 1)
            return {"artist": artist.strip(), "title": title.strip(), "url": url}

    print(f"  ✗ Could not extract track info from {url}", file=sys.stderr)
    return None


def download_track(artist, title, output_dir, audio_format="mp3"):
    """Download a track from YouTube using yt-dlp."""
    query = f"{artist} - {title}"
    output_template = str(Path(output_dir) / f"{artist} - {title}.%(ext)s")

    cmd = [
        "yt-dlp",
        "--default-search", "ytsearch",
        "-x",
        "--audio-format", audio_format,
        "--audio-quality", "0",
        "-o", output_template,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        f"ytsearch:{query}",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return True
        print(f"  ✗ yt-dlp error: {result.stderr.strip()}", file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print(f"  ✗ Download timed out for: {query}", file=sys.stderr)
        return False
    except FileNotFoundError:
        print("Error: yt-dlp not found. Install with: pip install yt-dlp", file=sys.stderr)
        sys.exit(1)


def read_links(source):
    """Read Shazam links from file or stdin."""
    if source == "-":
        lines = sys.stdin.read().splitlines()
    else:
        lines = Path(source).read_text().splitlines()

    links = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url_match = re.search(r"https?://\S*shazam\S+", line)
        if url_match:
            links.append(url_match.group(0))
        elif "shazam.com" in line:
            links.append(line)
    return links


def main():
    parser = argparse.ArgumentParser(description="Download MP3s from Shazam links")
    parser.add_argument("input", help="Text file with Shazam links (one per line), or - for stdin")
    parser.add_argument("-o", "--output", default="./music", help="Output directory (default: ./music)")
    parser.add_argument("-f", "--format", default="mp3", choices=["mp3", "flac", "ogg", "m4a"],
                        help="Audio format (default: mp3)")
    parser.add_argument("--dry-run", action="store_true", help="Extract track info only, don't download")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests (default: 1s)")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    links = read_links(args.input)
    if not links:
        print("No Shazam links found in input.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(links)} Shazam links")
    print(f"Output: {output_dir.resolve()}")
    print(f"Format: {args.format}")
    print()

    tracks = []
    failed_extract = []
    failed_download = []

    # Phase 1: Extract track info
    print("Extracting track info...")
    for i, link in enumerate(links, 1):
        print(f"  [{i}/{len(links)}] {link}")
        info = extract_track_info(link)
        if info:
            print(f"    → {info['artist']} - {info['title']}")
            tracks.append(info)
        else:
            failed_extract.append(link)
        if i < len(links):
            time.sleep(args.delay)

    print(f"\nExtracted {len(tracks)}/{len(links)} tracks")

    if args.dry_run:
        print("\nDry run — tracks found:")
        for t in tracks:
            print(f"  {t['artist']} - {t['title']}")
        return

    # Phase 2: Download
    print("\nDownloading...\n")
    for i, track in enumerate(tracks, 1):
        query = f"{track['artist']} - {track['title']}"
        print(f"  [{i}/{len(tracks)}] {query}")
        ok = download_track(track["artist"], track["title"], output_dir, args.format)
        if ok:
            print(f"    ✓ Downloaded")
        else:
            failed_download.append(query)
            print(f"    ✗ Failed")

    # Summary
    downloaded = len(tracks) - len(failed_download)
    print(f"\n{'='*50}")
    print(f"Done! {downloaded}/{len(links)} tracks downloaded to {output_dir.resolve()}")
    if failed_extract:
        print(f"\nFailed to extract ({len(failed_extract)}):")
        for link in failed_extract:
            print(f"  {link}")
    if failed_download:
        print(f"\nFailed to download ({len(failed_download)}):")
        for q in failed_download:
            print(f"  {q}")


if __name__ == "__main__":
    main()
