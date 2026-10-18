"""File system scanner, regex filename cleaner, and local metadata reader for Nook."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from nook.database import Database

# Common video file extensions
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
    ".webm", ".m4v", ".ts", ".m2ts", ".mpg", ".mpeg",
    ".3gp", ".vob", ".ogv"
}

# Common cover image file names
COVER_FILENAMES = [
    "poster.jpg", "poster.png", "poster.webp", "poster.jpeg",
    "cover.jpg", "cover.png", "cover.webp", "cover.jpeg",
    "folder.jpg", "folder.png", "folder.webp", "folder.jpeg",
    "thumb.jpg", "thumb.png"
]

# Patterns to strip from titles
COMMON_RELEASE_TAGS = [
    r"1080p", r"720p", r"2160p", r"4k", r"480p", r"360p",
    r"bluray", r"blu-ray", r"bdrip", r"brrip", r"webrip", r"web-dl", r"webdl",
    r"hdtv", r"hdrip", r"dvdrip", r"remux", r"uhd",
    r"x264", r"x265", r"h264", r"h265", r"hevc", r"avc", r"xvid", r"divx",
    r"aac(?:\d\.\d)?", r"ac3", r"dts(?:-hd)?", r"truehd", r"atmos", r"ddp?\d\.\d",
    r"10bit", r"8bit", r"hdr(?:10)?(?:\+)?", r"sdr", r"dolby(?:\s*vision)?",
    r"multi(?:sub)?", r"dual(?:\s*audio)?", r"proper", r"repack",
    r"yify", r"yts(?:\.mx|\.am|\.lt)?", r"rarbg", r"eztv", r"psa", r"sparks",
    r"galaxy", r"ettv", r"tgx", r"subsplease", r"eraikyo", r"judas", r"commie",
    r"[a-f0-9]{8}"  # CRC hashes like [ABCD1234]
]


class FilenameCleaner:
    """Parser to clean messy media filenames into readable titles and extract metadata."""

    @staticmethod
    def extract_season_episode(filename: str) -> Tuple[int, int, str]:
        """Extract (season, episode, remaining_name) from filename.

        Examples:
        - Stranger.Things.S01E02.Chapter.Two.mkv -> (1, 2, "Chapter Two")
        - 1x04 - Pilot.mp4 -> (1, 4, "Pilot")
        - Sousou no Frieren - 05.mkv -> (0, 5, "")
        """
        stem = Path(filename).stem

        # Pattern 1: S01E02 or s1e2 or S01.E02
        se_match = re.search(r"[Ss](\d{1,2})[\s._\-]?[Ee](\d{1,3})", stem)
        if se_match:
            season = int(se_match.group(1))
            episode = int(se_match.group(2))
            return season, episode, stem

        # Pattern 2: 1x02 or 01x02
        x_match = re.search(r"(?:^|[\s._\-\[])(\d{1,2})x(\d{1,3})(?:[\s._\-\]]|$)", stem)
        if x_match:
            season = int(x_match.group(1))
            episode = int(x_match.group(2))
            return season, episode, stem

        # Pattern 3: Episode 02 or EP02 or Ep. 02 or E02 (with word boundaries)
        ep_match = re.search(r"\b(?:episode|ep\.?|e)\s*(\d{1,3})\b", stem, re.IGNORECASE)
        if ep_match:
            episode = int(ep_match.group(1))
            s_match = re.search(r"\b(?:season|s)\s*(\d{1,2})\b", stem, re.IGNORECASE)
            season = int(s_match.group(1)) if s_match else 0
            return season, episode, stem

        # Pattern 4: Anime / release style: "Show Name - 05" or "[Group] Show - 05 (1080p)"
        # Note: Avoid matching isolated numbers that precede a 4-digit year like "Spider.Man.2.2004"
        if not re.search(r"[\s._\-]\d{1,2}[\s._\-](19\d{2}|20\d{2})\b", stem):
            dash_ep = re.search(r"(?:-\s*|\bEP\s*|#\s*)(\d{1,3})(?:[\s._\-v\[(]|$)", stem)
            if dash_ep:
                try:
                    num = int(dash_ep.group(1))
                    if not (1900 <= num <= 2099):
                        return 0, num, stem
                except ValueError:
                    pass

        return 0, 0, stem

    @classmethod
    def clean_title(cls, filename_or_folder: str, is_episode: bool = True) -> str:
        """Convert a messy filename or folder name into a clean, human-readable title."""
        name = Path(filename_or_folder).stem

        # Remove leading release groups in square brackets, e.g. [SubsPlease]
        name = re.sub(r"^\[[^\]]+\]\s*", "", name)

        # Remove trailing hashes in square brackets, e.g. [ABCD1234]
        name = re.sub(r"\[[A-Fa-f0-9]{6,8}\]$", "", name).strip()

        # Check for Season and Episode
        season, episode, _ = cls.extract_season_episode(name)

        # Extract Year if present
        year_match = re.search(r"[\s._\-(](19\d{2}|20\d{2})[\s._\-)](?!\d)", name)
        year = year_match.group(1) if year_match else None

        # Work on cleaning the text
        working = name

        # Replace release tags
        for tag in COMMON_RELEASE_TAGS:
            working = re.sub(r"(?i)\b" + tag + r"\b", " ", working)
            working = re.sub(r"(?i)[\s._\-\[]+" + tag + r"[\]\s._\-]*", " ", working)

        # Replace dots, underscores with spaces (except when part of numbers or acronyms)
        working = re.sub(r"[._]", " ", working)

        # Remove empty brackets and parenthesis
        working = re.sub(r"\[\s*\]|\(\s*\)", "", working)

        # Collapse whitespace
        working = re.sub(r"\s+", " ", working).strip()

        if is_episode:
            # Build clean episode title
            if season > 0 and episode > 0:
                se_prefix = f"S{season:02d}E{episode:02d}"
                # Extract portion after SxxExx from original name
                split_parts = re.split(r"(?i)\bS\d{1,2}[\s._\-]?[Ee]\d{1,3}\b", name, maxsplit=1)
                after_part = split_parts[1] if len(split_parts) > 1 else ""
                ep_subname = after_part
                for tag in COMMON_RELEASE_TAGS:
                    ep_subname = re.sub(r"(?i)\b" + tag + r"\b", " ", ep_subname)
                    ep_subname = re.sub(r"(?i)[\s._\-\[]+" + tag + r"[\]\s._\-]*", " ", ep_subname)
                ep_subname = re.sub(r"[._]", " ", ep_subname)
                ep_subname = re.sub(r"\[\s*\]|\(\s*\)", "", ep_subname)
                ep_subname = re.sub(r"\s+", " ", ep_subname).strip(" -_.")
                if ep_subname and len(ep_subname) > 1:
                    return f"{se_prefix} - {ep_subname}"
                return se_prefix
            elif episode > 0:
                ep_prefix = f"Episode {episode:02d}"
                # Extract portion after episode tag from original name
                split_parts = re.split(r"(?i)(?:-\s*|\b(?:episode|ep\.?|e)\s*0?" + str(episode) + r"\b)", name, maxsplit=1)
                after_part = split_parts[-1] if len(split_parts) > 1 else ""
                ep_subname = after_part
                for tag in COMMON_RELEASE_TAGS:
                    ep_subname = re.sub(r"(?i)\b" + tag + r"\b", " ", ep_subname)
                    ep_subname = re.sub(r"(?i)[\s._\-\[]+" + tag + r"[\]\s._\-]*", " ", ep_subname)
                ep_subname = re.sub(r"[._]", " ", ep_subname)
                ep_subname = re.sub(r"\[\s*\]|\(\s*\)", "", ep_subname)
                ep_subname = re.sub(r"\s+", " ", ep_subname).strip(" -_.")
                if ep_subname and len(ep_subname) > 1:
                    return f"{ep_prefix} - {ep_subname}"
                return ep_prefix

        # For series or movies
        cleaned = re.sub(r"-\s*$", "", working).strip()
        if year and year not in cleaned:
            cleaned = f"{cleaned} ({year})"

        return cleaned or name


class LocalMetadataReader:
    """Reads local cover artwork and Kodi/Plex style .nfo files."""

    @staticmethod
    def find_cover_image(folder_path: Path) -> Optional[Path]:
        """Search a folder for standard cover/poster art."""
        if not folder_path.exists() or not folder_path.is_dir():
            return None

        for filename in COVER_FILENAMES:
            candidate = folder_path / filename
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate

        # Check for any image file containing 'poster' or 'cover'
        try:
            for item in folder_path.iterdir():
                if item.is_file() and item.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
                    lower_name = item.name.lower()
                    if "poster" in lower_name or "cover" in lower_name or "folder" in lower_name:
                        return item
        except PermissionError:
            pass

        return None

    @staticmethod
    def parse_nfo(folder_path: Path) -> Dict[str, str]:
        """Look for and parse .nfo metadata files in a directory."""
        metadata = {"title": "", "plot": "", "genre": "", "year": ""}
        if not folder_path.exists() or not folder_path.is_dir():
            return metadata

        nfo_files = list(folder_path.glob("*.nfo"))
        if not nfo_files:
            return metadata

        nfo_file = nfo_files[0]
        try:
            tree = ET.parse(str(nfo_file))
            root = tree.getroot()

            title_elem = root.find("title")
            if title_elem is not None and title_elem.text:
                metadata["title"] = title_elem.text.strip()

            plot_elem = root.find("plot") or root.find("outline")
            if plot_elem is not None and plot_elem.text:
                metadata["plot"] = plot_elem.text.strip()

            genre_elem = root.find("genre")
            if genre_elem is not None and genre_elem.text:
                metadata["genre"] = genre_elem.text.strip()

            year_elem = root.find("year") or root.find("premiered")
            if year_elem is not None and year_elem.text:
                metadata["year"] = year_elem.text.strip()[:4]
        except Exception:
            # Fallback regex for non-XML or messy .nfo
            try:
                content = nfo_file.read_text(encoding="utf-8", errors="ignore")
                title_m = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
                if title_m:
                    metadata["title"] = title_m.group(1).strip()
                plot_m = re.search(r"<plot>(.*?)</plot>", content, re.IGNORECASE)
                if plot_m:
                    metadata["plot"] = plot_m.group(1).strip()
            except Exception:
                pass

        return metadata


class LibraryScanner(QObject):
    """Scans configured root directories and indexes series & episodes."""

    # Qt Signals for UI integration
    scan_started = pyqtSignal()
    scan_progress = pyqtSignal(int, int, str)  # current, total, status_text
    scan_series_found = pyqtSignal(str)       # series display title
    scan_finished = pyqtSignal(int, int)       # scanned_series_count, scanned_episodes_count

    def __init__(self, db: Optional[Database] = None):
        super().__init__()
        self.db = db or Database()
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def scan_all(
        self,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_series_found: Optional[Callable[[str], None]] = None
    ) -> Tuple[int, int]:
        """Scan all registered root directories."""
        self._is_cancelled = False
        self.scan_started.emit()

        root_dirs = self.db.get_root_directories()
        if not root_dirs:
            if on_progress:
                on_progress(100, 100, "No root folders configured.")
            self.scan_finished.emit(0, 0)
            return 0, 0

        total_roots = len(root_dirs)
        series_count = 0
        episodes_count = 0

        for r_idx, root_info in enumerate(root_dirs):
            if self._is_cancelled:
                break
            root_id = root_info["id"]
            root_path = Path(root_info["path"])

            if not root_path.exists() or not root_path.is_dir():
                continue

            s_count, e_count = self.scan_root(root_id, root_path, on_progress, on_series_found)
            series_count += s_count
            episodes_count += e_count

            progress = int(((r_idx + 1) / total_roots) * 100)
            status_msg = f"Scanned {root_path.name}"
            if on_progress:
                on_progress(progress, 100, status_msg)
            self.scan_progress.emit(progress, 100, status_msg)

        self.scan_finished.emit(series_count, episodes_count)
        return series_count, episodes_count

    def scan_root(
        self,
        root_id: int,
        root_path: Path,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_series_found: Optional[Callable[[str], None]] = None
    ) -> Tuple[int, int]:
        """Scan a single root directory."""
        if not root_path.exists() or not root_path.is_dir():
            return 0, 0

        series_count = 0
        episodes_count = 0
        active_series_folders = []

        try:
            subdirs = [p for p in root_path.iterdir() if p.is_dir() and not p.name.startswith(".")]
        except (PermissionError, OSError):
            subdirs = []

        # Also check if root itself contains loose video files directly
        try:
            loose_videos = [
                f for f in root_path.iterdir()
                if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
            ]
        except (PermissionError, OSError):
            loose_videos = []

        if loose_videos:
            # Treat the root directory itself as a series for standalone videos
            s_count, e_count = self._index_series_folder(
                root_id, root_path, loose_videos, is_root_standalone=True,
                on_series_found=on_series_found
            )
            series_count += s_count
            episodes_count += e_count
            active_series_folders.append(str(root_path.resolve()))

        for subdir in subdirs:
            if self._is_cancelled:
                break

            active_series_folders.append(str(subdir.resolve()))
            s_count, e_count = self._index_series_folder(
                root_id, subdir, on_series_found=on_series_found
            )
            series_count += s_count
            episodes_count += e_count

        # Cleanup series removed from disk
        self.db.cleanup_missing_series(root_id, active_series_folders)
        return series_count, episodes_count

    def _index_series_folder(
        self,
        root_id: int,
        folder_path: Path,
        known_videos: Optional[List[Path]] = None,
        is_root_standalone: bool = False,
        on_series_found: Optional[Callable[[str], None]] = None
    ) -> Tuple[int, int]:
        """Index a single series folder and its episodes."""
        folder_name = folder_path.name
        # Find cover image
        detected_cover = LocalMetadataReader.find_cover_image(folder_path)
        detected_cover_str = str(detected_cover.resolve()) if detected_cover else ""

        # Parse .nfo if available
        nfo_data = LocalMetadataReader.parse_nfo(folder_path)
        display_title = nfo_data["title"] or FilenameCleaner.clean_title(folder_name, is_episode=False)
        description = nfo_data["plot"]

        tags = []
        if nfo_data["genre"]:
            tags = [g.strip() for g in re.split(r"[,/|;]", nfo_data["genre"]) if g.strip()]

        # Collect all video files inside this folder (including Season subdirectories)
        if known_videos is not None:
            video_files = known_videos
        else:
            video_files = []
            try:
                for entry in folder_path.rglob("*"):
                    if entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS and not entry.name.startswith("."):
                        video_files.append(entry)
            except (PermissionError, OSError):
                pass

        if not video_files and not detected_cover:
            # If folder has neither video files nor covers, skip it
            return 0, 0

        # Upsert series in database
        series_id = self.db.upsert_series(
            root_id=root_id,
            folder_path=str(folder_path.resolve()),
            folder_name=folder_name,
            display_title=display_title,
            detected_cover_path=detected_cover_str,
            description=description,
            tags=tags if tags else None
        )
        if on_series_found:
            on_series_found(display_title)
        self.scan_series_found.emit(display_title)

        # Index episodes
        active_episode_files = []
        for vfile in video_files:
            file_name = vfile.name
            clean_ep_title = FilenameCleaner.clean_title(file_name, is_episode=True)
            season_num, ep_num, _ = FilenameCleaner.extract_season_episode(file_name)

            # If season number wasn't found in file name, check parent folder (e.g. "Season 2")
            if season_num == 0 and vfile.parent != folder_path:
                parent_s = re.search(r"[Ss]eason\s*(\d{1,2})", vfile.parent.name)
                if parent_s:
                    season_num = int(parent_s.group(1))

            try:
                file_size = vfile.stat().st_size
            except OSError:
                file_size = 0

            self.db.upsert_episode(
                series_id=series_id,
                file_path=str(vfile.resolve()),
                file_name=file_name,
                clean_title=clean_ep_title,
                season_number=season_num,
                episode_number=ep_num,
                file_size=file_size
            )
            active_episode_files.append(str(vfile.resolve()))

        # Cleanup deleted episode files for this series
        self.db.cleanup_missing_episodes(series_id, active_episode_files)

        return 1, len(video_files)
