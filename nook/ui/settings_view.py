"""Settings Tab View for configuring root directories, media players, themes, and hidden series."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nook.database import Database, get_app_dir, get_covers_dir, get_db_path
from nook.scanner import LibraryScanner
from nook.ui.widgets.toast import ToastNotification


class ScanWorker(QThread):
    """Background worker for scanning media libraries."""

    progress = pyqtSignal(int, int, str)
    series_found = pyqtSignal(str)
    finished = pyqtSignal(int, int)

    def __init__(self, scanner: LibraryScanner):
        super().__init__()
        self.scanner = scanner

    def run(self) -> None:
        self.scanner.scan_progress.connect(self.progress.emit)
        self.scanner.scan_series_found.connect(self.series_found.emit)
        s_count, e_count = self.scanner.scan_all()
        self.finished.emit(s_count, e_count)


class SettingsView(QWidget):
    """Settings center for managing directories, player, themes, and hidden items."""

    theme_changed = pyqtSignal(str)       # "dark" or "light"
    library_rescanned = pyqtSignal(int, int)

    def __init__(self, db: Database, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db = db
        self.scanner = LibraryScanner(self.db)
        self.scan_worker: Optional[ScanWorker] = None

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 16, 24, 20)
        main_layout.setSpacing(14)

        # Header Title
        header = QLabel("⚙ Settings & Configuration", self)
        h_font = QFont(self.font())
        h_font.setPointSize(20)
        h_font.setBold(True)
        header.setFont(h_font)
        main_layout.addWidget(header)

        # Scroll Area for all settings cards
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(18)

        # -------------------------------------------------------------
        # 1. Root Directories Section
        # -------------------------------------------------------------
        dirs_card = self._create_card("📁 Library Root Folders", "Nook scans subfolders one level deep as distinct Series or Collections.")
        dirs_layout = QVBoxLayout(dirs_card)
        dirs_layout.setContentsMargins(18, 16, 18, 16)
        dirs_layout.setSpacing(12)

        self.dirs_list = QListWidget(dirs_card)
        self.dirs_list.setFixedHeight(120)
        dirs_layout.addWidget(self.dirs_list)

        dir_btns = QHBoxLayout()
        dir_btns.setSpacing(10)

        add_dir_btn = QPushButton("➕ Add Folder...", dirs_card)
        add_dir_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_dir_btn.clicked.connect(self._add_root_directory)
        dir_btns.addWidget(add_dir_btn)

        self.remove_dir_btn = QPushButton("✕ Remove Selected", dirs_card)
        self.remove_dir_btn.setObjectName("dangerBtn")
        self.remove_dir_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.remove_dir_btn.clicked.connect(self._remove_root_directory)
        dir_btns.addWidget(self.remove_dir_btn)

        dir_btns.addStretch()

        self.scan_now_btn = QPushButton("🔄 Scan Library Now", dirs_card)
        self.scan_now_btn.setObjectName("primaryBtn")
        self.scan_now_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.scan_now_btn.clicked.connect(self.start_scan)
        dir_btns.addWidget(self.scan_now_btn)

        dirs_layout.addLayout(dir_btns)

        # Scan progress bar & status
        self.scan_progress_bar = QProgressBar(dirs_card)
        self.scan_progress_bar.setFixedHeight(6)
        self.scan_progress_bar.setVisible(False)
        dirs_layout.addWidget(self.scan_progress_bar)

        self.scan_status_lbl = QLabel("", dirs_card)
        self.scan_status_lbl.setStyleSheet("color: #847569; font-size: 12px;")
        dirs_layout.addWidget(self.scan_status_lbl)

        content_layout.addWidget(dirs_card)

        # -------------------------------------------------------------
        # 2. Cozy Appearance & Theme Section
        # -------------------------------------------------------------
        theme_card = self._create_card("🎨 Cozy Appearance & UI", "Tailor your viewing experience with warm accents and comfortable themes.")
        theme_layout = QVBoxLayout(theme_card)
        theme_layout.setContentsMargins(18, 16, 18, 16)
        theme_layout.setSpacing(12)

        theme_radio_layout = QHBoxLayout()
        theme_radio_layout.setSpacing(20)

        theme_lbl = QLabel("App Theme:", theme_card)
        theme_lbl.setStyleSheet("font-weight: 600;")
        theme_radio_layout.addWidget(theme_lbl)

        self.theme_group = QButtonGroup(theme_card)
        self.radio_dark = QRadioButton("🌙 Cozy Dark (Warm Charcoal & Amber)", theme_card)
        self.radio_light = QRadioButton("☀️ Cozy Light (Soft Linen & Terracotta)", theme_card)
        self.theme_group.addButton(self.radio_dark)
        self.theme_group.addButton(self.radio_light)

        curr_theme = self.db.get_setting("theme", "dark")
        if curr_theme == "light":
            self.radio_light.setChecked(True)
        else:
            self.radio_dark.setChecked(True)

        self.radio_dark.toggled.connect(lambda c: self._on_theme_toggled("dark", c))
        self.radio_light.toggled.connect(lambda c: self._on_theme_toggled("light", c))

        theme_radio_layout.addWidget(self.radio_dark)
        theme_radio_layout.addWidget(self.radio_light)
        theme_radio_layout.addStretch()
        theme_layout.addLayout(theme_radio_layout)

        # Carousel toggle
        self.carousel_chk = QCheckBox("Show 'Continue Watching' carousel at the top of Library tab", theme_card)
        show_carousel = self.db.get_setting("show_recently_watched", "true").lower() == "true"
        self.carousel_chk.setChecked(show_carousel)
        self.carousel_chk.toggled.connect(self._on_carousel_toggled)
        theme_layout.addWidget(self.carousel_chk)

        content_layout.addWidget(theme_card)

        # -------------------------------------------------------------
        # 3. Media Player Launcher Section
        # -------------------------------------------------------------
        player_card = self._create_card("▶ Media Player Launcher", "Choose the external player to open videos with timestamp resume support.")
        player_layout = QVBoxLayout(player_card)
        player_layout.setContentsMargins(18, 16, 18, 16)
        player_layout.setSpacing(12)

        player_mode = self.db.get_setting("media_player_mode", "system")

        self.player_group = QButtonGroup(player_card)
        self.radio_player_sys = QRadioButton("Use System Default Player (xdg-open / Windows default)", player_card)
        self.radio_player_custom = QRadioButton("Use Custom Player (VLC, MPV, etc.)", player_card)
        self.player_group.addButton(self.radio_player_sys)
        self.player_group.addButton(self.radio_player_custom)

        if player_mode == "custom":
            self.radio_player_custom.setChecked(True)
        else:
            self.radio_player_sys.setChecked(True)

        self.radio_player_sys.toggled.connect(self._on_player_mode_changed)
        self.radio_player_custom.toggled.connect(self._on_player_mode_changed)

        player_layout.addWidget(self.radio_player_sys)
        player_layout.addWidget(self.radio_player_custom)

        # Custom player path input
        custom_row = QHBoxLayout()
        custom_row.setSpacing(10)

        path_lbl = QLabel("Executable Path or Command:", player_card)
        path_lbl.setStyleSheet("color: #847569; font-size: 13px;")
        custom_row.addWidget(path_lbl)

        self.player_path_input = QLineEdit(player_card)
        self.player_path_input.setText(self.db.get_setting("media_player_path", ""))
        self.player_path_input.setPlaceholderText("e.g. mpv, vlc, /usr/bin/mpv, or C:\\Program Files\\VideoLAN\\VLC\\vlc.exe")
        self.player_path_input.textChanged.connect(lambda text: self.db.set_setting("media_player_path", text.strip()))
        custom_row.addWidget(self.player_path_input, stretch=1)

        self.browse_player_btn = QPushButton("Browse...", player_card)
        self.browse_player_btn.clicked.connect(self._browse_custom_player)
        custom_row.addWidget(self.browse_player_btn)

        player_layout.addLayout(custom_row)
        content_layout.addWidget(player_card)

        # -------------------------------------------------------------
        # 4. Hidden Series Manager Section
        # -------------------------------------------------------------
        hidden_card = self._create_card("👁 Hidden Series Manager", "Items you have hidden from the main library grid.")
        hidden_layout = QVBoxLayout(hidden_card)
        hidden_layout.setContentsMargins(18, 16, 18, 16)
        hidden_layout.setSpacing(10)

        self.hidden_table = QTableWidget(hidden_card)
        self.hidden_table.setColumnCount(3)
        self.hidden_table.setHorizontalHeaderLabels(["Title", "Folder Path", "Action"])
        self.hidden_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.hidden_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.hidden_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.hidden_table.setFixedHeight(140)
        hidden_layout.addWidget(self.hidden_table)

        content_layout.addWidget(hidden_card)

        # -------------------------------------------------------------
        # 5. Online Scraper Settings
        # -------------------------------------------------------------
        scraper_card = self._create_card("🌐 Online Metadata Providers", "Configure public scrapers to fetch official series information and artwork.")
        scraper_layout = QVBoxLayout(scraper_card)
        scraper_layout.setContentsMargins(18, 16, 18, 16)
        scraper_layout.setSpacing(12)

        sc_row = QHBoxLayout()
        sc_row.setSpacing(12)

        sc_lbl = QLabel("Preferred Provider:", scraper_card)
        sc_lbl.setStyleSheet("font-weight: 600;")
        sc_row.addWidget(sc_lbl)

        self.scraper_combo = QComboBox(scraper_card)
        self.scraper_combo.addItem("TVMaze (No key required - Television/Shows)", "tvmaze")
        self.scraper_combo.addItem("AniList (No key required - Anime)", "anilist")
        self.scraper_combo.addItem("TheMovieDB (Requires TMDB API Key)", "tmdb")

        pref_sc = self.db.get_setting("preferred_scraper", "tvmaze")
        idx = self.scraper_combo.findData(pref_sc)
        if idx >= 0:
            self.scraper_combo.setCurrentIndex(idx)
        self.scraper_combo.currentIndexChanged.connect(lambda: self.db.set_setting("preferred_scraper", self.scraper_combo.currentData()))
        sc_row.addWidget(self.scraper_combo, stretch=1)
        scraper_layout.addLayout(sc_row)

        # TMDB Key row
        tmdb_row = QHBoxLayout()
        tmdb_lbl = QLabel("TMDB API Key (Optional):", scraper_card)
        tmdb_lbl.setStyleSheet("color: #847569; font-size: 13px;")
        tmdb_row.addWidget(tmdb_lbl)

        self.tmdb_key_input = QLineEdit(scraper_card)
        self.tmdb_key_input.setText(self.db.get_setting("tmdb_api_key", ""))
        self.tmdb_key_input.setPlaceholderText("Enter optional TMDB v3 API Key...")
        self.tmdb_key_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.tmdb_key_input.textChanged.connect(lambda text: self.db.set_setting("tmdb_api_key", text.strip()))
        tmdb_row.addWidget(self.tmdb_key_input, stretch=1)
        scraper_layout.addLayout(tmdb_row)

        content_layout.addWidget(scraper_card)

        # -------------------------------------------------------------
        # 6. Database & Application Data Info Section
        # -------------------------------------------------------------
        info_card = self._create_card("💾 Data Persistence & App Storage", "Database and managed covers storage details.")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(18, 16, 18, 16)
        info_layout.setSpacing(8)

        db_path_lbl = QLabel(f"SQLite Database: <b>{get_db_path()}</b>", info_card)
        db_path_lbl.setStyleSheet("color: #847569; font-size: 12px;")
        info_layout.addWidget(db_path_lbl)

        covers_dir = get_covers_dir()
        cover_count = len(list(covers_dir.glob("*")))
        covers_lbl = QLabel(f"Managed Covers Cache: <b>{covers_dir}</b> ({cover_count} saved images)", info_card)
        covers_lbl.setStyleSheet("color: #847569; font-size: 12px;")
        info_layout.addWidget(covers_lbl)

        open_app_dir_btn = QPushButton("📂 Open AppData Storage Folder", info_card)
        open_app_dir_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        open_app_dir_btn.clicked.connect(self._open_appdata_folder)
        info_layout.addWidget(open_app_dir_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        content_layout.addWidget(info_card)

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # Initial data load
        self.refresh()

    def _create_card(self, title: str, subtitle: str) -> QFrame:
        card = QFrame(self)
        card.setObjectName("episodeRow")
        return card

    def refresh(self) -> None:
        """Reload root directories and hidden series."""
        # 1. Root directories
        self.dirs_list.clear()
        roots = self.db.get_root_directories()
        for r in roots:
            item = QListWidgetItem(f"📁 {r['path']}")
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.dirs_list.addItem(item)

        # 2. Hidden series
        self._refresh_hidden_table()

    def _refresh_hidden_table(self) -> None:
        hidden_series = self.db.get_all_series(include_hidden=True)
        hidden_only = [s for s in hidden_series if s.get("is_hidden")]

        self.hidden_table.setRowCount(len(hidden_only))
        for row_idx, s in enumerate(hidden_only):
            title_item = QTableWidgetItem(s.get("display_title", ""))
            path_item = QTableWidgetItem(s.get("folder_path", ""))

            unhide_btn = QPushButton("👁 Unhide", self.hidden_table)
            unhide_btn.setObjectName("secondaryBtn")
            unhide_btn.setFixedHeight(26)
            unhide_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            series_id = s["id"]
            unhide_btn.clicked.connect(lambda checked, sid=series_id: self._unhide_series(sid))

            self.hidden_table.setItem(row_idx, 0, title_item)
            self.hidden_table.setItem(row_idx, 1, path_item)
            self.hidden_table.setCellWidget(row_idx, 2, unhide_btn)

    def _unhide_series(self, series_id: int) -> None:
        self.db.set_series_hidden(series_id, False)
        self._refresh_hidden_table()
        ToastNotification.show_toast(self.window(), "Series restored to library grid.")

    def _add_root_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Video Library Folder")
        if folder:
            self.db.add_root_directory(folder)
            self.refresh()
            ToastNotification.show_toast(self.window(), f"Added: {Path(folder).name}")
            # Prompt or auto-scan
            self.start_scan()

    def _remove_root_directory(self) -> None:
        curr = self.dirs_list.currentItem()
        if not curr:
            return
        root_id = curr.data(Qt.ItemDataRole.UserRole)
        self.db.remove_root_directory(root_id)
        self.refresh()
        ToastNotification.show_toast(self.window(), "Root folder removed from library.")

    def start_scan(self) -> None:
        """Trigger background library scan."""
        if self.scan_worker and self.scan_worker.isRunning():
            return

        self.scan_now_btn.setEnabled(False)
        self.scan_progress_bar.setVisible(True)
        self.scan_progress_bar.setValue(0)
        self.scan_status_lbl.setText("Starting library scan...")

        self.scan_worker = ScanWorker(self.scanner)
        self.scan_worker.progress.connect(self._on_scan_progress)
        self.scan_worker.series_found.connect(lambda title: self.scan_status_lbl.setText(f"Found: {title}"))
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.start()

    def _on_scan_progress(self, curr: int, total: int, status: str) -> None:
        self.scan_progress_bar.setValue(curr)
        self.scan_status_lbl.setText(status)

    def _on_scan_finished(self, series_count: int, episode_count: int) -> None:
        self.scan_now_btn.setEnabled(True)
        self.scan_progress_bar.setVisible(False)
        self.scan_status_lbl.setText(f"Scan complete: {series_count} series, {episode_count} episodes indexed.")
        ToastNotification.show_toast(self.window(), f"Scan complete: {series_count} series, {episode_count} episodes found.")
        self.library_rescanned.emit(series_count, episode_count)

    def _on_theme_toggled(self, theme_name: str, checked: bool) -> None:
        if checked:
            self.db.set_setting("theme", theme_name)
            self.theme_changed.emit(theme_name)

    def _on_carousel_toggled(self, checked: bool) -> None:
        self.db.set_setting("show_recently_watched", "true" if checked else "false")

    def _on_player_mode_changed(self) -> None:
        mode = "custom" if self.radio_player_custom.isChecked() else "system"
        self.db.set_setting("media_player_mode", mode)

    def _browse_custom_player(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Player Executable")
        if file_path:
            self.player_path_input.setText(file_path)
            self.radio_player_custom.setChecked(True)

    def _open_appdata_folder(self) -> None:
        app_dir = get_app_dir()
        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(app_dir)
            elif system == "Darwin":
                subprocess.Popen(["open", str(app_dir)])
            else:
                subprocess.Popen(["xdg-open", str(app_dir)])
        except Exception:
            pass
