# Nook — Cross-Platform Local Video Library Manager

**Nook** is a high-performance desktop application (**Linux and Windows**) designed to be your personal video library manager. Inspired by the visual clarity of Steam and modern streaming platforms, Nook is infused with a warm, welcoming aesthetic (soft rounded cards, warm amber and terracotta accents, clean typography, and seamless light/dark mode switching).

---

## Highlights & Features

### 1. UI/UX Design & Theme System
* **Dark Mode:** Rich espresso/charcoal tones (`#1A1614`), soft cream text (`#F7EFE2`), and warm amber accents (`#E5A93C`).
* **Light Mode:** Soft linen/cream backgrounds (`#FAF6F0`), deep espresso text (`#2B231F`), and warm terracotta accents (`#C86D51`).
* **Live Theme Toggle:** Instantly toggle between Light and Dark mode using the top bar button or Settings tab without restarting.
* **Accent Colour Presets:** Pick the secondary colour from 16 presets in Settings → Appearance (Amber, Orange, Coral, Rose, Pink, Magenta, Violet, Indigo, Blue, Sky, Cyan, Teal, Green, Lime, Red, Slate). Hover shades, readable button text and badge tints are derived automatically, and the choice is remembered between launches.
* **Modern Polish:** Rounded corners (`10px`–`16px`), responsive layout scaling, custom-styled scrollbars, and floating toast notifications.

### 2. Library & Navigation
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

### 3. Browse & Stream Online
* **Streaming Site Manager:** Register any streaming site by pasting its base URL in **Settings ➔ Streaming Sites**. Sites are stored in the database, can be renamed (double-click a site or use **Rename Selected**), and can be removed again at any time.
* **Browse Tab:** A dedicated tab with a site selector populated from your configured sites, a search box, and a responsive poster grid of search results. Search adapts to each site: if a site renders results client-side, Nook queries the JSON catalog API it advertises directly (**MMani**, **1Tube**, **AnimeIDHentai**, **Flixbaba**, **Elisworld** and **Miruro** via their catalog APIs), while ordinary HTML sites are tried against the common search URL shapes (`?q=`, `?query=`, `?keyword=`, `?wd=`, `?s=`, …) and common JSON endpoints (`/api/search`) until results are found. For sites behind filters that reject Python's TLS fingerprint, Nook transparently falls back to the system `curl` binary, and unreachable hosts fail fast instead of retrying every URL shape — so a dead site can never freeze the search. Cover art is detected robustly — posters are found whether the site nests the image inside the show link or places it in a sibling element, uses lazy-loading `data-src`/`data-srcset` attributes, a `data-setbg` background, or a CSS `background-image`. Artwork loads automatically for every result and is kept **in memory for display only** — searching never writes poster files to disk. Artwork is only saved permanently when you actually add a show to your library.
* **Latest Shows on Pick:** Selecting a site (or clicking **Show Recent**, or searching with an empty box) loads that site's newest shows — up to 20 to start. A **Show More** button below the grid reveals five more cards per click, fetching the next page from the site only after the current batch has been shown, and disappears once the site has no more results. Where a site exposes a real "latest" feed (1Tube trending, MMani's newest filter, AnimeIDHentai's series archive, Flixbaba's TMDB trending, Elisworld's cartoon archive and Miruro's catalog), Nook uses it directly.
* **Open Without Adding:** Every result has an **Open** button that jumps straight to the show page on the streaming site, so you can preview it without touching your library.
* **Add to Library:** Every result has an **Add to Library** button that imports the show (title, poster, description, tags and episode list) straight into your local Nook library. The closest online metadata match is then applied automatically, so imported shows arrive with a proper title, synopsis, tags and poster. If nothing matches closely enough, the data from the streaming site is kept as-is.
* **Multi-Source Library:** Shows from different sources coexist even when they share a title (e.g. a local `Naruto` folder and a HiAnime `Naruto` stream). Each series carries a small source badge on its card — a folder glyph for local folders, or a site badge for streams. Right-click an imported stream show and choose **Remove from Library** to drop it again (with a confirmation); local folders are managed by the scanner and are not removable this way.

### 4. Smart Filename Cleaning & Local Ingestion
* **Automatic Release Cleaning:** Parses messy scene release names into clean, readable titles:
  * `Spider.Man.2002.1080p.BluRay.x264.mkv` ➔ `Spider-Man (2002)`
  * `Stranger.Things.S01E02.Chapter.Two.720p.mkv` ➔ `S01E02 - Chapter Two`
  * `[SubsPlease] Sousou no Frieren - 05 (1080p) [ABCD1234].mkv` ➔ `Episode 05`
* **Local Artwork & .NFO Support:** Automatically detects `poster.jpg`, `cover.png`, `folder.jpg`, and Kodi/Plex-style `tvshow.nfo` or `movie.nfo` files for plot summaries and genres.
* **Public Online Scrapers:**
  * **TVMaze API:** Search and import official show summaries and poster art without requiring any API keys.
  * **AniList GraphQL API:** Search and import anime descriptions and high-res cover art without requiring any API keys.
  * **TheMovieDB (TMDB):** Optional provider with custom API key support.
  * **Automatic Matching For New Folders:** When a scan finds a folder it has never seen before, Nook searches the online providers and applies the closest title match (plus synopsis, tags and poster). Folders with no close match are left exactly as they were scanned. A locally supplied poster or `.nfo` is never overwritten. This can be toggled off in **Settings ➔ Online Metadata Providers**.

### 5. Watch Tracking & Playback Memory
* **Timestamp Resume:** Remembers playback timestamps per episode so you can resume exactly where you left off.
* **Cross-Platform Launcher:**
  * **Linux:** Uses `xdg-open` or custom player executables (MPV, VLC, Celluloid, SMPlayer).
  * **Windows:** Uses `os.startfile` or custom player binaries.
  * **Resume Arguments:** Automatically passes `--start=SS` (MPV) or `--start-time=SS` (VLC) when resuming with custom players.
  * **Network Streams:** Online episodes store their stream URL directly, and Nook hands it to VLC/MPV or the system handler untouched, so HLS (`.m3u8`) and direct links play just like local files.

### 6. Series Customization Modal
Right-click any series card or click **Customize** in the detail view to:
1. **Virtual Rename:** Change the display title inside the database without touching your physical files on disk.
2. **Custom Cover Art:** Upload custom image files (`.jpg`, `.png`, `.webp`), automatically copied and managed safely in the app data directory.
3. **Custom Tags / Genres:** Assign custom categories.
4. **Favorite & Visibility:** Toggle favorites and hide/unhide series from the main grid.

---

## Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Ctrl + F` | Focus and select the global search bar |
| `Esc` | Return to Library from Detail view / Clear search / Close dialogs |
| `F5` | Quick library rescan |
| `Enter` / `Space` | Open selected series card or play episode |

---

## Project Architecture

```
/home/meheni/Music/Nook/
├── main.py                     # Application entry point
├── run.sh                      # Linux/macOS launcher script
├── run.bat                     # Windows launcher script
├── requirements.txt            # Python dependencies
├── nook/
│   ├── database.py             # SQLite persistence, schema & covers storage
│   ├── scanner.py              # File scanner, regex title cleaner & .nfo parser
│   ├── player.py               # Cross-platform media player launcher (files & URLs)
│   ├── scraper.py              # TVMaze, AniList & TMDB online metadata fetchers
│   ├── streaming.py            # Streaming site providers, search & episode parsing
│   ├── styles.py               # Cozy Dark & Cozy Light QSS themes
│   └── ui/
│       ├── main_window.py      # Top navigation bar & stacked tab views
│       ├── library_view.py     # Series grid, tag filtering & carousel container
│       ├── browse_view.py      # Browse tab: search & import streaming shows
│       ├── series_card.py      # Steam/Netflix style poster card with context menus
│       ├── series_detail.py    # Series episode browser (List & Grid modes)
│       ├── recently_watched.py # Continue watching episode carousel
│       ├── settings_view.py    # Settings panel, directory manager, player config
│       ├── customization_modal.py # Virtual rename, custom cover & tags modal
│       ├── scraper_dialog.py   # Online search & metadata import dialog
│       ├── icons.py            # Hand-drawn vector icon set (no external assets)
│       └── widgets/
│           ├── flow_layout.py  # Responsive wrapping layout
│           ├── poster_widget.py# Rounded poster renderer & cozy placeholder
│           └── toast.py        # Floating notification widget
└── tests/
    └── test_nook.py            # Unit & GUI integration test suite
```

---

## Getting Started

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

## Application Data Paths

* **Linux:** `~/.config/Nook/` (`nook.db` and managed `covers/`)
* **Windows:** `%APPDATA%\Nook\` (`nook.db` and managed `covers/`)
* **macOS:** `~/Library/Application Support/Nook/`
