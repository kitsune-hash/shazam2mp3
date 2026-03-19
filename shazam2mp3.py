#!/usr/bin/env python3
"""
Shazam/Facebook to MP3 downloader.
Reads Shazam links and Facebook video links, extracts or identifies artist/title,
downloads from YouTube via yt-dlp.

Supports:
  - Shazam links: extracts artist/title from page metadata
  - Facebook links (reels, videos): downloads video, identifies song via Shazam
    audio fingerprinting, then downloads proper MP3

Usage:
  python shazam2mp3.py links.txt -o ./music
  python shazam2mp3.py links.txt -o ./music --format flac
  echo "https://www.shazam.com/track/123" | python shazam2mp3.py - -o ./music

Requires: pip install yt-dlp requests shazamio
Also needs ffmpeg installed for audio conversion.
"""

import argparse
import asyncio
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests


def classify_link(url):
    """Classify a URL as 'shazam', 'facebook', or 'unknown'."""
    if "shazam.com" in url:
        return "shazam"
    if any(d in url for d in ("facebook.com", "fb.watch", "fb.com", "instagram.com")):
        return "facebook"
    return "unknown"


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
                    return {"artist": artist, "title": title, "url": url, "source": "shazam"}
        except (json.JSONDecodeError, AttributeError):
            pass

    og_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
    if og_match:
        raw = og_match.group(1).split(":")[0].strip()
        if " - " in raw:
            title, artist = raw.split(" - ", 1)
            return {"artist": artist.strip(), "title": title.strip(), "url": url, "source": "shazam"}

    print(f"  ✗ Could not extract track info from {url}", file=sys.stderr)
    return None


def download_video_audio(url, tmp_dir):
    """Download a Facebook/Instagram video and extract audio for fingerprinting."""
    output_template = str(Path(tmp_dir) / "audio.%(ext)s")
    cmd = [
        "yt-dlp", "-x", "--audio-format", "wav",
        "-o", output_template, "--no-playlist", "--quiet", "--no-warnings", url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"  ✗ yt-dlp error: {result.stderr.strip()}", file=sys.stderr)
            return None
    except subprocess.TimeoutExpired:
        print(f"  ✗ Download timed out for: {url}", file=sys.stderr)
        return None
    except FileNotFoundError:
        print("Error: yt-dlp not found. Install with: pip install yt-dlp", file=sys.stderr)
        sys.exit(1)

    # Find the output file
    for f in Path(tmp_dir).iterdir():
        if f.stem == "audio" and f.suffix:
            audio_path = str(Path(tmp_dir) / "audio.wav")
            if f.suffix != ".wav":
                convert_cmd = ["ffmpeg", "-y", "-i", str(f), "-ac", "1", "-ar", "16000", audio_path]
                subprocess.run(convert_cmd, capture_output=True, timeout=60)
                f.unlink(missing_ok=True)
            else:
                audio_path = str(f)
            if Path(audio_path).exists():
                return audio_path
    return None


async def identify_audio(audio_path):
    """Identify a song from an audio file using Shazam audio fingerprinting."""
    from shazamio import Shazam
    shazam = Shazam()
    result = await shazam.recognize(audio_path)
    if result and "track" in result:
        track = result["track"]
        title = track.get("title")
        artist = track.get("subtitle")
        if title and artist:
            return {"artist": artist, "title": title}
    return None


def process_facebook_link(url, index):
    """Process a Facebook/Instagram video link: download, identify, return track info."""
    with tempfile.TemporaryDirectory(prefix="shazam2mp3_") as tmp_dir:
        print(f"    Downloading video...")
        audio_path = download_video_audio(url, tmp_dir)
        if not audio_path:
            print(f"  ✗ Could not download video from {url}", file=sys.stderr)
            return None

        print(f"    Identifying song via Shazam...")
        info = asyncio.run(identify_audio(audio_path))

        if info:
            print(f"    → Identified: {info['artist']} - {info['title']}")
            return {
                "artist": info["artist"], "title": info["title"],
                "url": url, "source": "facebook-identified",
            }
        else:
            print(f"    ⚠ Could not identify song, will keep extracted audio")
            return {
                "artist": "Unknown", "title": f"unknown_{index:03d}",
                "url": url, "source": "facebook-unidentified",
            }


def download_facebook_audio_direct(url, output_dir, filename, audio_format="mp3"):
    """Download audio directly from a Facebook video (for unidentified tracks)."""
    output_template = str(Path(output_dir) / f"{filename}.%(ext)s")
    cmd = [
        "yt-dlp", "-x", "--audio-format", audio_format, "--audio-quality", "0",
        "-o", output_template, "--no-playlist", "--quiet", "--no-warnings", url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def download_track(artist, title, output_dir, audio_format="mp3"):
    """Download a track from YouTube using yt-dlp."""
    query = f"{artist} - {title}"
    output_template = str(Path(output_dir) / f"{artist} - {title}.%(ext)s")
    cmd = [
        "yt-dlp", "--default-search", "ytsearch", "-x",
        "--audio-format", audio_format, "--audio-quality", "0",
        "-o", output_template, "--no-playlist", "--quiet", "--no-warnings",
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
    """Read links from file or stdin. Supports Shazam, Facebook, and Instagram URLs."""
    if source == "-":
        lines = sys.stdin.read().splitlines()
    else:
        lines = Path(source).read_text().splitlines()

    links = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url_match = re.search(r"https?://\S+", line)
        if url_match:
            url = url_match.group(0)
            link_type = classify_link(url)
            if link_type != "unknown":
                links.append({"url": url, "type": link_type})
            else:
                print(f"  ⚠ Skipping unknown link type: {url}", file=sys.stderr)
    return links


def main():
    parser = argparse.ArgumentParser(description="Download MP3s from Shazam & Facebook links")
    parser.add_argument("input", help="Text file with links (one per line), or - for stdin")
    parser.add_argument("-o", "--output", default="./music", help="Output directory (default: ./music)")
    parser.add_argument("-f", "--format", default="mp3", choices=["mp3", "flac", "ogg", "m4a"],
                        help="Audio format (default: mp3)")
    parser.add_argument("--dry-run", action="store_true", help="Extract/identify track info only, don't download")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests (default: 1s)")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    links = read_links(args.input)
    if not links:
        print("No supported links found in input.", file=sys.stderr)
        sys.exit(1)

    shazam_count = sum(1 for l in links if l["type"] == "shazam")
    fb_count = sum(1 for l in links if l["type"] == "facebook")
    print(f"Found {len(links)} links ({shazam_count} Shazam, {fb_count} Facebook/Instagram)")
    print(f"Output: {output_dir.resolve()}")
    print(f"Format: {args.format}")
    print()

    tracks = []
    failed_extract = []
    unidentified = []
    unknown_counter = 0

    print("Extracting track info...")
    for i, link in enumerate(links, 1):
        url = link["url"]
        link_type = link["type"]
        print(f"  [{i}/{len(links)}] ({link_type}) {url}")

        if link_type == "shazam":
            info = extract_track_info(url)
            if info:
                print(f"    → {info['artist']} - {info['title']}")
                tracks.append(info)
            else:
                failed_extract.append(url)
        elif link_type == "facebook":
            unknown_counter += 1
            info = process_facebook_link(url, unknown_counter)
            if info:
                if info["source"] == "facebook-identified":
                    tracks.append(info)
                else:
                    unidentified.append(info)
            else:
                failed_extract.append(url)

        if i < len(links):
            time.sleep(args.delay)

    identified = len(tracks)
    print(f"\nIdentified {identified}/{len(links)} tracks")
    if unidentified:
        print(f"Unidentified (will save raw audio): {len(unidentified)}")

    if args.dry_run:
        print("\nDry run — tracks found:")
        for t in tracks:
            print(f"  [{t['source']}] {t['artist']} - {t['title']}")
        if unidentified:
            print(f"\nUnidentified ({len(unidentified)}):")
            for u in unidentified:
                print(f"  {u['url']}")
        return

    # Download identified tracks from YouTube
    failed_download = []
    if tracks:
        print("\nDownloading identified tracks...\n")
        for i, track in enumerate(tracks, 1):
            query = f"{track['artist']} - {track['title']}"
            print(f"  [{i}/{len(tracks)}] {query}")
            ok = download_track(track["artist"], track["title"], output_dir, args.format)
            if ok:
                print(f"    ✓ Downloaded")
            else:
                failed_download.append(query)
                print(f"    ✗ Failed")

    # Save raw audio for unidentified tracks
    if unidentified:
        print("\nSaving unidentified tracks (raw audio from video)...\n")
        for i, track in enumerate(unidentified, 1):
            filename = track["title"]
            print(f"  [{i}/{len(unidentified)}] {track['url']} → {filename}.{args.format}")
            ok = download_facebook_audio_direct(track["url"], output_dir, filename, args.format)
            if ok:
                print(f"    ✓ Saved")
            else:
                failed_download.append(filename)
                print(f"    ✗ Failed")

    # Summary
    total_success = len(tracks) + len(unidentified) - len(failed_download)
    print(f"\n{'='*50}")
    print(f"Done! {total_success}/{len(links)} tracks downloaded to {output_dir.resolve()}")
    if identified:
        print(f"  ✓ {identified} identified via Shazam metadata or audio fingerprint")
    if unidentified:
        saved = len(unidentified) - sum(1 for f in failed_download if f.startswith("unknown_"))
        print(f"  ⚠ {saved} saved as raw audio (could not identify)")
    if failed_extract:
        print(f"\nFailed to extract/download ({len(failed_extract)}):")
        for link in failed_extract:
            print(f"  {link}")
    if failed_download:
        print(f"\nFailed to download ({len(failed_download)}):")
        for q in failed_download:
            print(f"  {q}")


if __name__ == "__main__":
    main()
