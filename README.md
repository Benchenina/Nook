# ☕ Nook — Cross-Platform Cozy Local Video Library Manager

**Nook** is a high-performance desktop application (**Linux and Windows**) designed to be your cozy personal video library manager. Inspired by the visual clarity of Steam and modern streaming platforms, Nook is infused with a warm, welcoming aesthetic (soft rounded cards, warm amber and terracotta accents, clean typography, and seamless light/dark mode switching).

---

## 🌟 Highlights & Features

### 🎨 1. Cozy UI/UX Design & Theme System
* **Cozy Dark Mode:** Rich espresso/charcoal tones (`#1A1614`), soft cream text (`#F7EFE2`), and warm amber accents (`#E5A93C`).
* **Cozy Light Mode:** Soft linen/cream backgrounds (`#FAF6F0`), deep espresso text (`#2B231F`), and warm terracotta accents (`#C86D51`).
* **Live Theme Toggle:** Instantly toggle between Light and Dark mode using the top bar button or Settings tab without restarting.
* **Modern Polish:** Rounded corners (`10px`–`16px`), responsive layout scaling, custom-styled scrollbars, and floating toast notifications.

### 📚 2. Library & Navigation
* **Library Tab:**
  * **Continue Watching Carousel:** Top carousel featuring recently played episodes with progress bars and 1-click **Resume** buttons.
  * **Responsive Grid:** Rectangular poster cards with fixed aspect ratios that automatically wrap and adjust to window width.
  * **Filter Bar:** Filter cards by genre/tag chips (`All`, `Anime`, `Sci-Fi`, etc.) with one click.
  * **Sort Options:** Sort by **A-Z**, **Z-A**, **Recently Added**, **Most Watched**, or **Recently Watched**.
  * **Global Instant Search (`Ctrl+F`):** Live filtering as you type.
* **Favorites Tab:** Quick-access view showing all series marked with a heart.
* **Series Detail View:**
  * Hero banner with poster, editable title, tags, synopsis, and overall completion progress.
  * Toggle between **Detailed List View** (with progress bars, timestamps, and file sizes) and **Thumbnail Grid View**.
  * Episode watch checkmarks and resume playback buttons.
* **Settings Tab:** Complete app configuration center.

### 🔍 3. Smart Filename Cleaning & Local Ingestion
* **Automatic Release Cleaning:** Parses messy scene release names into clean, readable titles:
  * `Spider.Man.2002.1080p.BluRay.x264.mkv` ➔ `Spider-Man (2002)`
  * `Stranger.Things.S01E02.Chapter.Two.720p.mkv` ➔ `S01E02 - Chapter Two`
  * `[SubsPlease] Sousou no Frieren - 05 (1080p) [ABCD1234].mkv` ➔ `Episode 05`
* **Local Artwork & .NFO Support:** Automatically detects `poster.jpg`, `cover.png`, `folder.jpg`, and Kodi/Plex-style `tvshow.nfo` or `movie.nfo` files for plot summaries and genres.
* **Public Online Scrapers:**
  * **TVMaze API:** Search and import official show summaries and poster art without requiring any API keys.
  * **AniList GraphQL API:** Search and import anime descriptions and high-res cover art without requiring any API keys.
  * **TheMovieDB (TMDB):** Optional provider with custom API key support.

### ⏱️ 4. Watch Tracking & Playback Memory
* **Timestamp Resume:** Remembers playback timestamps per episode so you can resume exactly where you left off.
* **Cross-Platform Launcher:**
  * **Linux:** Uses `xdg-open` or custom player executables (MPV, VLC, Celluloid, SMPlayer).
  * **Windows:** Uses `os.startfile` or custom player binaries.
  * **Resume Arguments:** Automatically passes `--start=SS` (MPV) or `--start-time=SS` (VLC) when resuming with custom players.

### 🛠️ 5. Series Customization Modal
Right-click any series card or click **Customize** in the detail view to:
1. **Virtual Rename:** Change the display title inside the database without touching your physical files on disk.
2. **Custom Cover Art:** Upload custom image files (`.jpg`, `.png`, `.webp`), automatically copied and managed safely in the app data directory.
3. **Custom Tags / Genres:** Assign custom categories.
4. **Favorite & Visibility:** Toggle favorites and hide/unhide series from the main grid.

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Ctrl + F` | Focus and select the global search bar |
| `Esc` | Return to Library from Detail view / Clear search / Close dialogs |
| `F5` | Quick library rescan |
| `Enter` / `Space` | Open selected series card or play episode |

---

## 📂 Project Architecture

```
/home/meheni/Music/Nook/
├── main.py                     # Application entry point
├── run.sh                      # Linux/macOS launcher script
├── run.bat                     # Windows launcher script
├── requirements.txt            # Python dependencies
├── nook/
│   ├── database.py             # SQLite persistence, schema & covers storage
│   ├── scanner.py              # File scanner, regex title cleaner & .nfo parser
│   ├── player.py               # Cross-platform media player launcher
│   ├── scraper.py              # TVMaze, AniList & TMDB online metadata fetchers
│   ├── styles.py               # Cozy Dark & Cozy Light QSS themes
│   └── ui/
│       ├── main_window.py      # Top navigation bar & stacked tab views
│       ├── library_view.py     # Series grid, tag filtering & carousel container
│       ├── series_card.py      # Steam/Netflix style poster card with context menus
│       ├── series_detail.py    # Series episode browser (List & Grid modes)
│       ├── recently_watched.py # Continue watching episode carousel
│       ├── settings_view.py    # Settings panel, directory manager, player config
│       ├── customization_modal.py # Virtual rename, custom cover & tags modal
│       ├── scraper_dialog.py   # Online search & metadata import dialog
│       └── widgets/
│           ├── flow_layout.py  # Responsive wrapping layout
│           ├── poster_widget.py# Rounded poster renderer & cozy placeholder
│           └── toast.py        # Floating notification widget
└── tests/
    └── test_nook.py            # Unit & GUI integration test suite
```

---

## 🚀 Getting Started

### Prerequisites
* Python 3.10+
* PyQt6, requests, Pillow

### Installation
```bash
# Clone or navigate to the project directory
cd /home/meheni/Music/Nook

# Create virtual environment & install dependencies
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

### Launching Nook
```bash
# On Linux / macOS:
./run.sh

# On Windows:
run.bat

# Or directly with Python:
python3 main.py
```

### Headless CLI Scan
```bash
./run.sh --scan
```

### Running Tests
```bash
./.venv/bin/python -m unittest discover -s tests -v
```

---

## 💾 Application Data Paths

* **Linux:** `~/.config/Nook/` (`nook.db` and managed `covers/`)
* **Windows:** `%APPDATA%\Nook\` (`nook.db` and managed `covers/`)
* **macOS:** `~/Library/Application Support/Nook/`
