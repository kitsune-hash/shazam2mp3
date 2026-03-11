# shazam2mp3

Download MP3s from Shazam links. Extracts artist/title from Shazam pages and downloads via [spotdl](https://github.com/spotDL/spotify-downloader) (Spotify matching + YouTube audio).

Perfect for converting a list of Shazam discoveries into a USB-ready music collection.

## Install

```bash
pip install spotdl yt-dlp requests beautifulsoup4
```

You'll also need [ffmpeg](https://ffmpeg.org/download.html) installed.

## Usage

```bash
# Create a text file with Shazam links (one per line)
cat > links.txt << EOL
https://www.shazam.com/track/58153086
https://www.shazam.com/track/123456789
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
2. Uses `spotdl` to find the track on Spotify and download the audio from YouTube
3. Tags the MP3 with proper metadata (artist, title, album, artwork)

## License

MIT
