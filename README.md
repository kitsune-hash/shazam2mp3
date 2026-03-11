# shazam2mp3

Download MP3s from Shazam links. Extracts artist/title from Shazam pages and downloads audio from YouTube via [yt-dlp](https://github.com/yt-dlp/yt-dlp).

Perfect for converting a list of Shazam discoveries into a USB-ready music collection.

## Install

```bash
pip install yt-dlp requests
```

You'll also need [ffmpeg](https://ffmpeg.org/download.html) installed.

## Usage

```bash
# Create a text file with Shazam links (one per line)
# Can be copy-pasted directly from chat messages — extra text is ignored
cat > links.txt << EOL
https://www.shazam.com/track/58153086
https://www.shazam.com/track/52615880?referrer=share
EOL

# Download all as MP3
python shazam2mp3.py links.txt -o ./music

# Preview what would be downloaded
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
| `--dry-run` | Extract track info without downloading | — |
| `--delay` | Delay between Shazam requests (seconds) | `1.0` |

## How it works

1. Fetches each Shazam page and extracts artist/title from JSON-LD metadata
2. Searches YouTube for the best match via yt-dlp
3. Downloads and converts to the desired audio format

## License

MIT
