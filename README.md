# Nook

Nook is a cross-platform desktop video library manager (Linux, Windows, macOS) designed to organize local files and browse streaming sources in a unified, customizable interface.

---

## Core Features

### Library & Playback
- **Organization:** Responsive grid view, genre filtering, multi-criteria sorting, favorites list, and global search (`Ctrl + F`).
- **Playback Tracking:** Remembers playback positions per episode and launches external players (VLC, MPV, system default) with automated resume flags.
- **File Ingestion:** Automated scene filename cleaning, local `.nfo` metadata parsing, and local artwork detection.
- **Customization:** Virtual renaming (without changing files on disk), custom image uploads for covers, and manual tag assignments.

### Online Streaming & Metadata
- **Site Integration:** Register custom streaming site URLs to search, browse, and stream directly through external players.
- **Library Import:** Add streaming titles into the local database alongside local media.
- **Scrapers:** Automated metadata and cover fetching via TVMaze, AniList, and TMDB.

### Interface
- Light and dark themes with 16 accent color presets.
- Responsive layout with "Continue Watching" carousel and detailed series views.

---

## Key Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Ctrl + F` | Focus global search |
| `Esc` | Clear search / Close modal / Back to library |
| `F5` | Trigger library rescan |
| `Enter` / `Space` | Open selected card or play episode |

---

## Getting Started

### Prerequisites
- Python 3.10+
- PyQt6, requests, Pillow

### Installation
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Usage
- **Run GUI:**
  - Linux/macOS: `./run.sh`
  - Windows: `run.bat`
  - Python: `python3 main.py`
- **Headless Scan:** `./run.sh --scan`
- **Run Tests:** `python -m unittest discover -s tests -v`

---

## Data Storage Locations

- **Linux:** `~/.config/Nook/`
- **Windows:** `%APPDATA%\Nook\`
- **macOS:** `~/Library/Application Support/Nook/`