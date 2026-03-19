# shazam2mp3

Download MP3s from **Shazam links** and **Facebook/Instagram videos**. Extracts or identifies artist/title and downloads audio from YouTube via [yt-dlp](https://github.com/yt-dlp/yt-dlp).

Perfect for converting a mixed bag of Shazam discoveries and Facebook music reels into a USB-ready music collection.

## How it works

- **Shazam links:** Fetches the page and extracts artist/title from JSON-LD metadata, then downloads from YouTube
- **Facebook/Instagram links:** Downloads the video, identifies the song via Shazam audio fingerprinting ([shazamio](https://github.com/dotenv-org/shazamio)), then downloads the proper MP3 from YouTube
- **Unidentified tracks:** If Shazam can't recognize the audio (obscure songs, live recordings), saves the raw audio extracted from the video

## Install

```bash
pip install yt-dlp requests shazamio
```

You'll also need [ffmpeg](https://ffmpeg.org/download.html) installed.

## Usage

```bash
# Create a text file with links (one per line)
# Supports Shazam, Facebook, and Instagram URLs
# Can be copy-pasted directly from chat messages - extra text is ignored
cat > links.txt << EOL
https://www.shazam.com/track/58153086
https://www.facebook.com/reel/1234567890
https://fb.watch/abc123/
https://www.shazam.com/track/52615880?referrer=share
EOL

# Download all as MP3
python shazam2mp3.py links.txt -o ./music

# Preview what would be downloaded (identifies without downloading)
python shazam2mp3.py links.txt --dry-run

# Download as FLAC
python shazam2mp3.py links.txt -o ./music --format flac

# Pipe links from stdin
cat links.txt | python shazam2mp3.py - -o ./music
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-o, --output` | Output directory | `./music` |
| `-f, --format` | Audio format (`mp3`, `flac`, `ogg`, `m4a`) | `mp3` |
| `--dry-run` | Extract track info without downloading | - |
| `--delay` | Delay between requests (seconds) | `1.0` |

## Supported link types

| Source | How it works |
|--------|-------------|
| `shazam.com/track/...` | Extracts metadata from page |
| `facebook.com/reel/...` | Downloads video, identifies via audio fingerprint |
| `fb.watch/...` | Same as Facebook |
| `instagram.com/reel/...` | Same as Facebook |

## License

MIT
