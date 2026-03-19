#!/usr/bin/env python3
"""
Shazam/Facebook/YouTube to MP3 downloader.
Reads Shazam links, Facebook/Instagram video links, and YouTube links.
Extracts or identifies artist/title, downloads from YouTube via yt-dlp.

Supports:
  - Shazam links: extracts artist/title from page metadata or chat context
  - Facebook links (reels, videos): downloads video, identifies song via Shazam
    audio fingerprinting, then downloads proper MP3
  - YouTube links: downloads audio directly
  - Chat file parsing: reads WhatsApp/Telegram chat exports, extracts links
    and uses surrounding text for metadata (e.g. "Title par Artist <shazam-url>")

Usage:
  python shazam2mp3.py links.txt -o ./music
  python shazam2mp3.py --chat-file conversation.txt -o ./music
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
    """Classify a URL as 'shazam', 'facebook', 'youtube', or 'unknown'."""
    if "shazam.com" in url:
        return "shazam"
    if any(d in url for d in ("facebook.com", "fb.watch", "fb.com", "instagram.com")):
        return "facebook"
    if any(d in url for d in ("youtube.com", "youtu.be")):
        return "youtube"
    return "unknown"


def sanitize_filename(name):
    """Remove characters that are invalid in filenames."""
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()


def parse_chat_file(filepath):
    """Parse a WhatsApp/Telegram chat export and extract links with context metadata.
    
    Recognizes patterns like:
      - "Title par Artist https://www.shazam.com/track/..."  (metadata before link)
      - "[timestamp] Name: Title par Artist https://..."      (WhatsApp format)
      - "[timestamp] Name: https://..."                       (link only)
    
    Returns deduplicated list of {url, type, artist?, title?}
    """
    text = Path(filepath).read_text(encoding='utf-8')
    lines = text.splitlines()
    
    entries = []
    seen_urls = set()
    
    # Pattern: "Title par Artist URL" or just "URL"
    # The "par" pattern is French Shazam sharing format
    shazam_with_meta = re.compile(
        r'(.+?)\s+par\s+(.+?)\s+(https?://(?:www\.)?shazam\.com/\S+)'
    )
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Strip WhatsApp/Telegram timestamp prefix: [HH:MM, DD/MM/YYYY] Name: 
        cleaned = re.sub(r'^\[[\d:,/ ]+\]\s*[^:]+:\s*', '', line)
        
        # Try "Title par Artist <shazam-url>" pattern
        m = shazam_with_meta.search(cleaned)
        if m:
            title = m.group(1).strip()
            artist = m.group(2).strip()
            url = m.group(3).strip()
            
            if url not in seen_urls:
                seen_urls.add(url)
                entries.append({
                    "url": url, "type": "shazam",
                    "artist": artist, "title": title,
                    "source": "chat-metadata"
                })
            continue
        
        # Extract all URLs from the line
        urls = re.findall(r'https?://\S+', cleaned)
        for url in urls:
            if url in seen_urls:
                continue
            
            link_type = classify_link(url)
            if link_type != "unknown":
                seen_urls.add(url)
                entries.append({"url": url, "type": link_type})
    
    return entries


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


def extract_facebook_metadata(url):
    """Try to extract track info from Facebook video metadata via yt-dlp."""
    cmd = ["yt-dlp", "--dump-json", "--no-download", "--quiet", "--no-warnings", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        data = json.loads(result.stdout)

        # Check for explicit track/artist metadata (Facebook music tags)
        track = data.get("track")
        artist = data.get("artist") or data.get("creator") or data.get("uploader")
        if track and artist:
            return {"artist": artist, "title": track}

        # Check title for "Artist - Title" or "Title by Artist" patterns
        title = data.get("title", "")
        description = data.get("description", "")

        # Try common patterns in title/description
        for text in [title, description]:
            if not text:
                continue
            # "Artist - Title" pattern
            m = re.match(r"^(.+?)\s*[-–]\s*(.+)$", text.strip())
            if m and len(m.group(1)) < 60 and len(m.group(2)) < 80:
                return {"artist": m.group(1).strip(), "title": m.group(2).strip()}

        # If we have a meaningful title (not just "Facebook" or generic), return it
        if title and len(title) > 3 and title.lower() not in ("facebook", "reel", "video"):
            return {"artist": data.get("uploader", "Unknown"), "title": title, "partial": True}

        return None
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None


def process_facebook_link(url, index, cookies_file=None):
    """Process a Facebook/Instagram video link: extract metadata, identify, return track info."""

    # Step 1: Try to get metadata without downloading
    print(f"    Checking video metadata...")
    meta = extract_facebook_metadata(url)
    if meta and not meta.get("partial"):
        print(f"    → Found in metadata: {meta['artist']} - {meta['title']}")
        return {
            "artist": meta["artist"], "title": meta["title"],
            "url": url, "source": "facebook-metadata",
        }
    if meta and meta.get("partial"):
        print(f"    ℹ Partial metadata: {meta.get('title', '?')} (will verify via fingerprint)")

    # Step 2: Download audio and fingerprint via Shazam
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
        elif meta and meta.get("partial"):
            # Use partial metadata as fallback
            print(f"    ⚠ Shazam failed, using partial metadata")
            return {
                "artist": meta["artist"], "title": meta["title"],
                "url": url, "source": "facebook-partial",
            }
        else:
            print(f"    ⚠ Could not identify song, will keep extracted audio")
            return {
                "artist": "Unknown", "title": f"unknown_{index:03d}",
                "url": url, "source": "facebook-unidentified",
            }


def download_youtube(url, output_dir, audio_format="mp3"):
    """Download audio from a YouTube link."""
    # First get the title
    cmd = ["yt-dlp", "--dump-json", "--no-download", "--quiet", "--no-warnings", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            title = data.get("title", "unknown")
        else:
            title = "unknown"
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        title = "unknown"

    filename = sanitize_filename(title)
    output_template = str(Path(output_dir) / f"{filename}.%(ext)s")
    cmd = [
        "yt-dlp", "-x", "--audio-format", audio_format, "--audio-quality", "0",
        "-o", output_template, "--no-playlist", "--quiet", "--no-warnings", url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0, title
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, title


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
    filename = sanitize_filename(f"{artist} - {title}")
    output_template = str(Path(output_dir) / f"{filename}.%(ext)s")
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
    """Read links from file or stdin. Supports Shazam, Facebook, Instagram, and YouTube URLs."""
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
    parser = argparse.ArgumentParser(description="Download MP3s from Shazam, Facebook & YouTube links")
    parser.add_argument("input", nargs='?', default=None,
                        help="Text file with links (one per line), or - for stdin")
    parser.add_argument("--chat-file", default=None,
                        help="WhatsApp/Telegram chat export file (parses links + metadata)")
    parser.add_argument("-o", "--output", default="./music", help="Output directory (default: ./music)")
    parser.add_argument("-f", "--format", default="mp3", choices=["mp3", "flac", "ogg", "m4a"],
                        help="Audio format (default: mp3)")
    parser.add_argument("--dry-run", action="store_true", help="Extract/identify track info only, don't download")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests (default: 1s)")
    parser.add_argument("--cookies", default=None,
                        help="Path to cookies.txt file (needed for Facebook login-walled content)")
    args = parser.parse_args()

    if not args.input and not args.chat_file:
        parser.error("Either input file or --chat-file is required")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse input
    if args.chat_file:
        entries = parse_chat_file(args.chat_file)
    else:
        entries = read_links(args.input)

    if not entries:
        print("No supported links found in input.", file=sys.stderr)
        sys.exit(1)

    # Count by type
    shazam_count = sum(1 for e in entries if e["type"] == "shazam")
    fb_count = sum(1 for e in entries if e["type"] == "facebook")
    yt_count = sum(1 for e in entries if e["type"] == "youtube")
    pre_identified = sum(1 for e in entries if e.get("source") == "chat-metadata")
    
    print(f"Found {len(entries)} unique links ({shazam_count} Shazam, {fb_count} Facebook/Instagram, {yt_count} YouTube)")
    if pre_identified:
        print(f"  → {pre_identified} Shazam tracks already identified from chat metadata (skipping web fetch)")
    print(f"Output: {output_dir.resolve()}")
    print(f"Format: {args.format}")
    print()

    tracks = []
    youtube_tracks = []
    failed_extract = []
    unidentified = []
    unknown_counter = 0

    print("Extracting track info...")
    for i, entry in enumerate(entries, 1):
        url = entry["url"]
        link_type = entry["type"]
        print(f"  [{i}/{len(entries)}] ({link_type}) {url}")

        if link_type == "shazam":
            # Check if we already have metadata from chat parsing
            if entry.get("source") == "chat-metadata":
                print(f"    → From chat: {entry['artist']} - {entry['title']}")
                tracks.append(entry)
            else:
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
                if info["source"] in ("facebook-identified", "facebook-metadata"):
                    tracks.append(info)
                else:
                    unidentified.append(info)
            else:
                failed_extract.append(url)

        elif link_type == "youtube":
            youtube_tracks.append({"url": url, "type": "youtube"})
            print(f"    → YouTube link (will download directly)")

        if i < len(entries):
            time.sleep(args.delay)

    identified = len(tracks)
    print(f"\nIdentified {identified}/{len(entries)} tracks")
    if youtube_tracks:
        print(f"YouTube direct downloads: {len(youtube_tracks)}")
    if unidentified:
        print(f"Unidentified (will save raw audio): {len(unidentified)}")

    if args.dry_run:
        print("\nDry run — tracks found:")
        for t in tracks:
            src = t.get('source', '?')
            print(f"  [{src}] {t['artist']} - {t['title']}")
        if youtube_tracks:
            print(f"\nYouTube ({len(youtube_tracks)}):")
            for yt in youtube_tracks:
                print(f"  {yt['url']}")
        if unidentified:
            print(f"\nUnidentified ({len(unidentified)}):")
            for u in unidentified:
                print(f"  {u['url']}")
        return

    # Download identified tracks from YouTube search
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

    # Download YouTube links directly
    if youtube_tracks:
        print("\nDownloading YouTube tracks...\n")
        for i, yt in enumerate(youtube_tracks, 1):
            print(f"  [{i}/{len(youtube_tracks)}] {yt['url']}")
            ok, title = download_youtube(yt["url"], output_dir, args.format)
            if ok:
                print(f"    ✓ Downloaded: {title}")
            else:
                failed_download.append(yt["url"])
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
    total_items = len(tracks) + len(youtube_tracks) + len(unidentified)
    total_success = total_items - len(failed_download)
    print(f"\n{'='*50}")
    print(f"Done! {total_success}/{len(entries)} tracks downloaded to {output_dir.resolve()}")
    if identified:
        print(f"  ✓ {identified} identified via metadata/fingerprint")
    if youtube_tracks:
        yt_ok = len(youtube_tracks) - sum(1 for f in failed_download if f.startswith("http"))
        print(f"  ✓ {yt_ok} downloaded from YouTube")
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
