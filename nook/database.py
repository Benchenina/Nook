"""Database persistence and OS application data storage for Nook.

Cross-platform data storage:
- Windows: %APPDATA%/Nook
- Linux: $XDG_CONFIG_HOME/Nook or ~/.config/Nook
- macOS: ~/Library/Application Support/Nook
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_app_dir() -> Path:
    """Return OS-specific application data directory for Nook."""
    system = platform.system()
    if system == "Windows":
        app_data = os.environ.get("APPDATA")
        if app_data:
            base = Path(app_data)
        else:
            base = Path.home() / "AppData" / "Roaming"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        # Linux and other Unixes
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            base = Path(xdg_config)
        else:
            base = Path.home() / ".config"

    nook_dir = base / "Nook"
    nook_dir.mkdir(parents=True, exist_ok=True)
    return nook_dir


def get_covers_dir() -> Path:
    """Return managed covers storage directory."""
    covers_dir = get_app_dir() / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    return covers_dir


def get_db_path() -> Path:
    """Return SQLite database path."""
    return get_app_dir() / "nook.db"


# Remote / synthetic references (http(s) streams and the `scheme://` URIs used
# for online series, e.g. ``hianime://naruto-1``) must never be run through
# ``Path.resolve()`` - doing so would mangle the URI into a local path.
_REMOTE_REF_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def is_remote_reference(value: str) -> bool:
    """Return True for URLs / synthetic stream references."""
    return bool(_REMOTE_REF_RE.match((value or "").strip()))


def _normalize_media_path(value: str) -> str:
    """Absolutise local paths while leaving URLs untouched."""
    value = (value or "").strip()
    if is_remote_reference(value):
        return value
    return str(Path(value).resolve())


from contextlib import contextmanager


class Database:
    """SQLite Database manager for Nook."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_db_path()
        self.init_db()

    @contextmanager
    def get_connection(self):
        """Create, yield, and safely close a configured sqlite3 connection."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

            # Root directories table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS root_directories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Streaming sites configured by the user (name + base URL)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS streaming_sites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    base_url TEXT UNIQUE NOT NULL,
                    source_type TEXT NOT NULL DEFAULT '',
                    enabled INTEGER DEFAULT 1,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Series table
            #
            # ``source_type``/``source_id`` form a composite identifier so the
            # very same show title can exist once per source (a local folder and
            # a HiAnime stream of "Naruto" are two independent rows). Local
            # series keep ``source_type='local'`` and an empty ``source_id``;
            # the ``folder_path`` unique constraint still guards local folders.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS series (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    root_id INTEGER,
                    folder_path TEXT UNIQUE NOT NULL,
                    folder_name TEXT NOT NULL,
                    display_title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    custom_cover_path TEXT DEFAULT '',
                    detected_cover_path TEXT DEFAULT '',
                    is_favorite INTEGER DEFAULT 0,
                    is_hidden INTEGER DEFAULT 0,
                    has_seasons INTEGER DEFAULT 0,
                    source_type TEXT NOT NULL DEFAULT 'local',
                    source_id TEXT NOT NULL DEFAULT '',
                    source_url TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_scanned TIMESTAMP,
                    view_count INTEGER DEFAULT 0,
                    last_watched_at TIMESTAMP,
                    FOREIGN KEY (root_id) REFERENCES root_directories (id) ON DELETE SET NULL
                );
            """)

            # Episodes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id INTEGER NOT NULL,
                    file_path TEXT UNIQUE NOT NULL,
                    file_name TEXT NOT NULL,
                    clean_title TEXT NOT NULL,
                    season_number INTEGER DEFAULT 0,
                    episode_number INTEGER DEFAULT 0,
                    file_size INTEGER DEFAULT 0,
                    duration_seconds INTEGER DEFAULT 0,
                    watched INTEGER DEFAULT 0,
                    playback_position INTEGER DEFAULT 0,
                    last_watched_at TIMESTAMP,
                    play_count INTEGER DEFAULT 0,
                    season_name TEXT DEFAULT '',
                    FOREIGN KEY (series_id) REFERENCES series (id) ON DELETE CASCADE
                );
            """)

            # Migration: ensure season_name exists on existing databases
            ep_columns = [col["name"] for col in cursor.execute("PRAGMA table_info(episodes);").fetchall()]
            if "season_name" not in ep_columns:
                cursor.execute("ALTER TABLE episodes ADD COLUMN season_name TEXT DEFAULT '';")

            # Migration: ensure series columns exist on existing databases
            series_columns = [col["name"] for col in cursor.execute("PRAGMA table_info(series);").fetchall()]
            series_migrations = {
                "has_seasons": "INTEGER DEFAULT 0",
                "source_type": "TEXT NOT NULL DEFAULT 'local'",
                "source_id": "TEXT NOT NULL DEFAULT ''",
                "source_url": "TEXT DEFAULT ''",
            }
            for column, ddl in series_migrations.items():
                if column not in series_columns:
                    cursor.execute(f"ALTER TABLE series ADD COLUMN {column} {ddl};")

            # Create helpful indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_series_hidden ON series (is_hidden);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_series_fav ON series (is_favorite);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_series_source_type ON series (source_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_series ON episodes (series_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_last_watched ON episodes (last_watched_at);")

            # Composite identifier for imported streaming shows: the same
            # (source_type, source_id) pair must never be imported twice, while
            # local series (empty source_id) stay governed by folder_path.
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_series_source
                ON series (source_type, source_id) WHERE source_id != '';
            """)

            # Seed default settings if empty
            defaults = {
                "theme": "dark",
                "show_recently_watched": "true",
                "media_player_mode": "system",
                "media_player_path": "",
                "preferred_scraper": "tvmaze",
                "tmdb_api_key": "",
                "auto_scrape_new_series": "true",
                "detail_view_mode": "list",  # 'list' or 'grid'
                "card_size": "medium"
            }
            for k, v in defaults.items():
                cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?);", (k, v))

            conn.commit()

    # ---------------------------------------------------------
    # Settings Operations
    # ---------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        with self.get_connection() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?;", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value;
            """, (key, str(value)))
            conn.commit()

    def get_all_settings(self) -> Dict[str, str]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT key, value FROM settings;").fetchall()
            return {row["key"]: row["value"] for row in rows}

    # ---------------------------------------------------------
    # Root Directory Operations
    # ---------------------------------------------------------
    def get_root_directories(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM root_directories ORDER BY added_at ASC;").fetchall()
            return [dict(row) for row in rows]

    def add_root_directory(self, path_str: str) -> Optional[int]:
        normalized = str(Path(path_str).resolve())
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO root_directories (path) VALUES (?);", (normalized,))
                conn.commit()
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT id FROM root_directories WHERE path = ?;", (normalized,)).fetchone()
                return row["id"] if row else None

    def remove_root_directory(self, root_id: int) -> None:
        with self.get_connection() as conn:
            # Delete series under this root
            conn.execute("DELETE FROM series WHERE root_id = ?;", (root_id,))
            conn.execute("DELETE FROM root_directories WHERE id = ?;", (root_id,))
            conn.commit()

    # ---------------------------------------------------------
    # Series Operations
    # ---------------------------------------------------------
    def upsert_series(
        self,
        root_id: Optional[int],
        folder_path: str,
        folder_name: str,
        display_title: str,
        detected_cover_path: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
        has_seasons: bool = False,
        source_type: str = "local",
        source_id: str = "",
        source_url: str = "",
    ) -> int:
        norm_path = _normalize_media_path(folder_path)
        tags_json = json.dumps(tags or [])
        now = datetime.now().isoformat()
        source_type = (source_type or "local").strip() or "local"
        source_id = (source_id or "").strip()
        source_url = (source_url or "").strip()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if source_type != "local" and source_id:
                # Streaming series are keyed by their composite identifier.
                existing = cursor.execute(
                    "SELECT id FROM series WHERE source_type = ? AND source_id = ?;",
                    (source_type, source_id),
                ).fetchone()
            else:
                existing = cursor.execute(
                    "SELECT id FROM series WHERE folder_path = ?;", (norm_path,)
                ).fetchone()

            if existing:
                series_id = existing["id"]
                # Update folder metadata without overwriting virtual renames if set
                cursor.execute("""
                    UPDATE series
                    SET root_id = ?,
                        folder_name = ?,
                        source_type = ?,
                        source_id = ?,
                        source_url = CASE WHEN ? != '' THEN ? ELSE source_url END,
                        detected_cover_path = CASE WHEN detected_cover_path = '' THEN ? ELSE detected_cover_path END,
                        description = CASE WHEN description = '' THEN ? ELSE description END,
                        has_seasons = ?,
                        last_scanned = ?
                    WHERE id = ?;
                """, (
                    root_id, folder_name, source_type, source_id, source_url, source_url,
                    detected_cover_path, description, 1 if has_seasons else 0, now, series_id
                ))
            else:
                cursor.execute("""
                    INSERT INTO series (
                        root_id, folder_path, folder_name, display_title,
                        description, detected_cover_path, tags, has_seasons,
                        source_type, source_id, source_url, created_at, last_scanned
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    root_id, norm_path, folder_name, display_title,
                    description, detected_cover_path, tags_json, 1 if has_seasons else 0,
                    source_type, source_id, source_url, now, now
                ))
                series_id = cursor.lastrowid
            conn.commit()
            return series_id

    def get_all_series(
        self,
        include_hidden: bool = False,
        only_favorites: bool = False,
        tag: Optional[str] = None,
        search_query: Optional[str] = None,
        sort_by: str = "title"  # 'title', 'recent_added', 'most_watched', 'recent_watched'
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT s.*,
                COUNT(e.id) AS episode_count,
                SUM(CASE WHEN e.watched = 1 THEN 1 ELSE 0 END) AS watched_count,
                MAX(e.last_watched_at) AS latest_episode_watched
            FROM series s
            LEFT JOIN episodes e ON s.id = e.series_id
            WHERE 1=1
        """
        params: List[Any] = []

        if not include_hidden:
            query += " AND s.is_hidden = 0"
        if only_favorites:
            query += " AND s.is_favorite = 1"
        if search_query:
            query += " AND (s.display_title LIKE ? OR s.folder_name LIKE ?)"
            params.extend([f"%{search_query}%", f"%{search_query}%"])

        query += " GROUP BY s.id"

        # Sorting logic
        if sort_by == "title":
            query += " ORDER BY s.display_title COLLATE NOCASE ASC"
        elif sort_by == "title_desc":
            query += " ORDER BY s.display_title COLLATE NOCASE DESC"
        elif sort_by == "recent_added":
            query += " ORDER BY s.created_at DESC"
        elif sort_by == "most_watched":
            query += " ORDER BY s.view_count DESC, watched_count DESC"
        elif sort_by == "recent_watched":
            query += " ORDER BY COALESCE(s.last_watched_at, '1970-01-01') DESC, s.created_at DESC"
        else:
            query += " ORDER BY s.display_title COLLATE NOCASE ASC"

        with self.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                try:
                    item["tags_list"] = json.loads(item.get("tags") or "[]")
                except Exception:
                    item["tags_list"] = []
                # Filter by tag if requested
                if tag and tag.lower() != "all":
                    if not any(t.lower() == tag.lower() for t in item["tags_list"]):
                        continue
                results.append(item)
            return results

    def series_exists(self, folder_path: str) -> bool:
        """Return True when a series row already exists for this folder."""
        norm_path = str(Path(folder_path).resolve())
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM series WHERE folder_path = ?;", (norm_path,)
            ).fetchone()
            return row is not None

    def get_series_by_id(self, series_id: int) -> Optional[Dict[str, Any]]:
        query = """
            SELECT s.*,
                COUNT(e.id) AS episode_count,
                SUM(CASE WHEN e.watched = 1 THEN 1 ELSE 0 END) AS watched_count
            FROM series s
            LEFT JOIN episodes e ON s.id = e.series_id
            WHERE s.id = ?
            GROUP BY s.id;
        """
        with self.get_connection() as conn:
            row = conn.execute(query, (series_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            try:
                item["tags_list"] = json.loads(item.get("tags") or "[]")
            except Exception:
                item["tags_list"] = []
            return item

    def get_all_tags(self) -> List[str]:
        """Return unique list of all tags currently in use."""
        tags_set = set()
        with self.get_connection() as conn:
            rows = conn.execute("SELECT tags FROM series WHERE is_hidden = 0;").fetchall()
            for r in rows:
                try:
                    loaded = json.loads(r["tags"] or "[]")
                    for t in loaded:
                        if t.strip():
                            tags_set.add(t.strip())
                except Exception:
                    pass
        return sorted(list(tags_set))

    def update_series_customization(
        self,
        series_id: int,
        display_title: Optional[str] = None,
        custom_cover_path: Optional[str] = None,
        tags: Optional[List[str]] = None,
        is_favorite: Optional[bool] = None,
        is_hidden: Optional[bool] = None,
        description: Optional[str] = None
    ) -> None:
        updates = []
        params = []
        if display_title is not None:
            updates.append("display_title = ?")
            params.append(display_title.strip())
        if custom_cover_path is not None:
            updates.append("custom_cover_path = ?")
            params.append(custom_cover_path)
        if tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(tags))
        if is_favorite is not None:
            updates.append("is_favorite = ?")
            params.append(1 if is_favorite else 0)
        if is_hidden is not None:
            updates.append("is_hidden = ?")
            params.append(1 if is_hidden else 0)
        if description is not None:
            updates.append("description = ?")
            params.append(description)

        if not updates:
            return

        params.append(series_id)
        with self.get_connection() as conn:
            conn.execute(f"UPDATE series SET {', '.join(updates)} WHERE id = ?;", params)
            conn.commit()

    def set_series_favorite(self, series_id: int, is_favorite: bool) -> None:
        self.update_series_customization(series_id, is_favorite=is_favorite)

    def set_series_hidden(self, series_id: int, is_hidden: bool) -> None:
        self.update_series_customization(series_id, is_hidden=is_hidden)

    def delete_series(self, series_id: int) -> None:
        """Delete a series (and its episodes) plus any managed cover artwork.

        Episodes are removed automatically via the foreign-key cascade. Cover
        files are only unlinked when they live in Nook's managed covers folder,
        so artwork that belongs to a real media folder is never touched.
        """
        series = self.get_series_by_id(series_id)
        with self.get_connection() as conn:
            conn.execute("DELETE FROM series WHERE id = ?;", (series_id,))
            conn.commit()

        if not series:
            return
        covers_dir = get_covers_dir()
        for key in ("custom_cover_path", "detected_cover_path"):
            raw_path = (series.get(key) or "").strip()
            if not raw_path:
                continue
            try:
                path = Path(raw_path)
                if path.exists() and covers_dir in path.resolve().parents:
                    path.unlink()
            except Exception:
                pass

    # ---------------------------------------------------------
    # Streaming Site & Stream Series Operations
    # ---------------------------------------------------------
    def add_streaming_site(self, base_url: str, name: str = "") -> Optional[int]:
        """Register (or update) a streaming site from a base URL.

        The site slug and display name are derived from the URL when no
        explicit ``name`` is supplied. Returns the row id, or ``None`` when the
        URL could not be parsed.
        """
        # Imported lazily to avoid a circular import at module load time.
        from nook.streaming import normalize_site_url, site_display_name, site_slug

        normalized = normalize_site_url(base_url)
        if not normalized:
            return None
        slug = site_slug(base_url)
        display = (name or "").strip() or site_display_name(base_url, slug)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            existing = cursor.execute(
                "SELECT id FROM streaming_sites WHERE base_url = ?;", (normalized,)
            ).fetchone()
            if existing:
                cursor.execute(
                    "UPDATE streaming_sites SET name = ?, source_type = ? WHERE id = ?;",
                    (display, slug, existing["id"]),
                )
                site_id = existing["id"]
            else:
                cursor.execute(
                    "INSERT INTO streaming_sites (name, base_url, source_type) VALUES (?, ?, ?);",
                    (display, normalized, slug),
                )
                site_id = cursor.lastrowid
            conn.commit()
            return site_id

    def get_streaming_sites(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM streaming_sites ORDER BY added_at ASC, id ASC;"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_streaming_site_by_id(self, site_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM streaming_sites WHERE id = ?;", (site_id,)
            ).fetchone()
            return dict(row) if row else None

    def remove_streaming_site(self, site_id: int) -> None:
        with self.get_connection() as conn:
            conn.execute("DELETE FROM streaming_sites WHERE id = ?;", (site_id,))
            conn.commit()

    def rename_streaming_site(self, site_id: int, name: str) -> None:
        """Change the display name of a configured streaming site."""
        display = (name or "").strip()
        if not display:
            return
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE streaming_sites SET name = ? WHERE id = ?;",
                (display, site_id),
            )
            conn.commit()

    def get_series_by_source(self, source_type: str, source_id: str) -> Optional[Dict[str, Any]]:
        """Look up an imported streaming series by its composite identifier."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM series WHERE source_type = ? AND source_id = ?;",
                (source_type, source_id),
            ).fetchone()
            return dict(row) if row else None

    def add_streaming_series(
        self,
        source_type: str,
        source_id: str,
        title: str,
        source_url: str = "",
        poster_path: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
        episodes: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """Import an online show into the library as a *stream* series.

        The show is stored under a synthetic ``<source>://<id>`` folder path so
        it never collides with local folders, and its episodes keep the remote
        stream/page URL as their ``file_path`` so the player can open them.
        """
        source_type = (source_type or "stream").strip() or "stream"
        source_id = (source_id or "").strip()
        title = (title or "Untitled").strip() or "Untitled"
        folder_path = f"{source_type}://{source_id or title}"
        season_numbers = set()
        for ep in episodes or []:
            try:
                season_numbers.add(int(ep.get("season_number") or 1))
            except (TypeError, ValueError):
                season_numbers.add(1)
        has_seasons = len(season_numbers) > 1

        series_id = self.upsert_series(
            root_id=None,
            folder_path=folder_path,
            folder_name=title,
            display_title=title,
            detected_cover_path=poster_path,
            description=description,
            tags=tags,
            has_seasons=has_seasons,
            source_type=source_type,
            source_id=source_id,
            source_url=source_url,
        )

        for ep in episodes or []:
            media_url = (ep.get("url") or source_url or "").strip()
            if not media_url:
                continue
            title_text = (ep.get("title") or "").strip() or "Episode"
            self.upsert_episode(
                series_id=series_id,
                file_path=media_url,
                file_name=title_text,
                clean_title=title_text,
                season_number=int(ep.get("season_number") or 1),
                episode_number=int(ep.get("number") or 0),
                season_name=(ep.get("season_name") or "Season 1"),
            )
        return series_id

    # ---------------------------------------------------------
    # Episode Operations
    # ---------------------------------------------------------
    def upsert_episode(
        self,
        series_id: int,
        file_path: str,
        file_name: str,
        clean_title: str,
        season_number: int = 0,
        episode_number: int = 0,
        file_size: int = 0,
        duration_seconds: int = 0,
        season_name: str = ""
    ) -> int:
        # Stream URLs must be stored verbatim rather than path-resolved.
        norm_path = _normalize_media_path(file_path)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            existing = cursor.execute("SELECT id FROM episodes WHERE file_path = ?;", (norm_path,)).fetchone()
            if existing:
                ep_id = existing["id"]
                cursor.execute("""
                    UPDATE episodes
                    SET series_id = ?,
                        file_name = ?,
                        clean_title = ?,
                        season_number = ?,
                        episode_number = ?,
                        file_size = ?,
                        duration_seconds = CASE WHEN ? > 0 THEN ? ELSE duration_seconds END,
                        season_name = CASE WHEN ? != '' THEN ? ELSE season_name END
                    WHERE id = ?;
                """, (
                    series_id, file_name, clean_title, season_number,
                    episode_number, file_size, duration_seconds, duration_seconds,
                    season_name, season_name, ep_id
                ))
            else:
                cursor.execute("""
                    INSERT INTO episodes (
                        series_id, file_path, file_name, clean_title,
                        season_number, episode_number, file_size, duration_seconds, season_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    series_id, norm_path, file_name, clean_title,
                    season_number, episode_number, file_size, duration_seconds, season_name
                ))
                ep_id = cursor.lastrowid
            conn.commit()
            return ep_id

    def get_episodes_for_series(self, series_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM episodes
                WHERE series_id = ?
                ORDER BY
                    CASE WHEN season_number = 0 THEN 9999 ELSE season_number END ASC,
                    season_name ASC,
                    CASE WHEN episode_number = 0 THEN 9999 ELSE episode_number END ASC,
                    file_name ASC;
            """, (series_id,)).fetchall()
            return [dict(r) for r in rows]

    def mark_season_watched(self, series_id: int, season_name: str, watched: bool = True) -> None:
        now = datetime.now().isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE episodes
                SET watched = ?,
                    last_watched_at = CASE WHEN ? = 1 THEN ? ELSE last_watched_at END
                WHERE series_id = ? AND (season_name = ? OR (? = '' AND (season_name IS NULL OR season_name = '')));
            """, (1 if watched else 0, 1 if watched else 0, now, series_id, season_name, season_name))
            conn.commit()

    def mark_episodes_watched(self, episode_ids: List[int], watched: bool = True) -> None:
        """Mark an explicit set of episodes watched/unwatched.

        Used by season headers so that grouping never depends on
        season_name matching (legacy rows may have an empty season_name).
        """
        if not episode_ids:
            return
        now = datetime.now().isoformat()
        placeholders = ",".join("?" for _ in episode_ids)
        with self.get_connection() as conn:
            conn.execute(f"""
                UPDATE episodes
                SET watched = ?,
                    last_watched_at = CASE WHEN ? = 1 THEN ? ELSE last_watched_at END
                WHERE id IN ({placeholders});
            """, [1 if watched else 0, 1 if watched else 0, now] + list(episode_ids))
            conn.commit()

    def get_episode_by_id(self, episode_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM episodes WHERE id = ?;", (episode_id,)).fetchone()
            return dict(row) if row else None

    def remove_episode_from_history(self, episode_id: int) -> None:
        """Drop an episode from Continue Watching without touching watch state."""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE episodes SET last_watched_at = NULL WHERE id = ?;",
                (episode_id,)
            )
            conn.commit()

    def get_recently_watched_episodes(self, limit: int = 8) -> List[Dict[str, Any]]:
        """Return recently watched episodes with series information."""
        query = """
            SELECT e.*,
                   s.display_title AS series_title,
                   s.custom_cover_path AS series_custom_cover,
                   s.detected_cover_path AS series_detected_cover
            FROM episodes e
            JOIN series s ON e.series_id = s.id
            WHERE e.last_watched_at IS NOT NULL
              AND s.is_hidden = 0
            ORDER BY e.last_watched_at DESC
            LIMIT ?;
        """
        with self.get_connection() as conn:
            rows = conn.execute(query, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def update_episode_progress(
        self,
        episode_id: int,
        playback_position: int,
        watched: Optional[bool] = None,
        duration_seconds: Optional[int] = None,
        increment_play_count: bool = False
    ) -> None:
        now = datetime.now().isoformat()
        with self.get_connection() as conn:
            # Fetch episode
            ep = conn.execute("SELECT series_id, duration_seconds, watched, play_count FROM episodes WHERE id = ?;", (episode_id,)).fetchone()
            if not ep:
                return

            series_id = ep["series_id"]
            dur = duration_seconds if duration_seconds and duration_seconds > 0 else ep["duration_seconds"]

            # If playback position is >= 90% of duration, mark as watched automatically if duration known
            is_watched = watched
            if is_watched is None:
                if dur > 0 and playback_position >= (dur * 0.9):
                    is_watched = True
                else:
                    is_watched = bool(ep["watched"])

            play_count = ep["play_count"] + (1 if increment_play_count else 0)

            conn.execute("""
                UPDATE episodes
                SET playback_position = ?,
                    watched = ?,
                    duration_seconds = ?,
                    last_watched_at = ?,
                    play_count = ?
                WHERE id = ?;
            """, (playback_position, 1 if is_watched else 0, dur, now, play_count, episode_id))

            # Update series view count & last_watched_at
            conn.execute("""
                UPDATE series
                SET last_watched_at = ?,
                    view_count = view_count + ?
                WHERE id = ?;
            """, (now, 1 if increment_play_count else 0, series_id))

            conn.commit()

    def toggle_episode_watched(self, episode_id: int, watched: Optional[bool] = None) -> bool:
        """Toggle or set watched status for an episode."""
        with self.get_connection() as conn:
            ep = conn.execute("SELECT watched FROM episodes WHERE id = ?;", (episode_id,)).fetchone()
            if not ep:
                return False
            new_state = (not bool(ep["watched"])) if watched is None else watched
            now = datetime.now().isoformat()
            conn.execute("""
                UPDATE episodes
                SET watched = ?,
                    last_watched_at = CASE WHEN ? = 1 THEN ? ELSE last_watched_at END
                WHERE id = ?;
            """, (1 if new_state else 0, 1 if new_state else 0, now, episode_id))
            conn.commit()
            return new_state

    def mark_all_episodes_watched(self, series_id: int, watched: bool = True) -> None:
        now = datetime.now().isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE episodes
                SET watched = ?,
                    last_watched_at = CASE WHEN ? = 1 THEN ? ELSE last_watched_at END
                WHERE series_id = ?;
            """, (1 if watched else 0, 1 if watched else 0, now, series_id))
            conn.commit()

    def cleanup_missing_episodes(self, series_id: int, active_file_paths: List[str]) -> int:
        norm_paths = [_normalize_media_path(p) for p in active_file_paths]
        with self.get_connection() as conn:
            if not norm_paths:
                cursor = conn.execute("DELETE FROM episodes WHERE series_id = ?;", (series_id,))
            else:
                placeholders = ",".join("?" for _ in norm_paths)
                cursor = conn.execute(
                    f"DELETE FROM episodes WHERE series_id = ? AND file_path NOT IN ({placeholders});",
                    [series_id] + norm_paths
                )
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count

    def cleanup_missing_series(self, root_id: int, active_folder_paths: List[str]) -> int:
        norm_paths = [_normalize_media_path(p) for p in active_folder_paths]
        with self.get_connection() as conn:
            if not norm_paths:
                cursor = conn.execute("DELETE FROM series WHERE root_id = ?;", (root_id,))
            else:
                placeholders = ",".join("?" for _ in norm_paths)
                cursor = conn.execute(
                    f"DELETE FROM series WHERE root_id = ? AND folder_path NOT IN ({placeholders});",
                    [root_id] + norm_paths
                )
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count

    # ---------------------------------------------------------
    # Managed Cover Image Storage
    # ---------------------------------------------------------
    def save_cover_image(self, source_path_or_bytes: Any, prefix: str = "cover") -> str:
        """Safely store an image inside the managed covers directory.

        Returns the absolute path to the saved file.
        """
        covers_dir = get_covers_dir()
        unique_name = f"{prefix}_{uuid.uuid4().hex[:10]}"

        if isinstance(source_path_or_bytes, (str, Path)):
            src = Path(source_path_or_bytes)
            ext = src.suffix.lower() or ".jpg"
            target = covers_dir / f"{unique_name}{ext}"
            shutil.copy2(src, target)
            return str(target)
        elif isinstance(source_path_or_bytes, bytes):
            target = covers_dir / f"{unique_name}.jpg"
            target.write_bytes(source_path_or_bytes)
            return str(target)
        else:
            raise ValueError("Unsupported source for cover image.")
