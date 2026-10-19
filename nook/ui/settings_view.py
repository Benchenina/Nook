"""Settings Tab View for configuring root directories, media players, themes, and hidden series."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal
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
    QInputDialog,
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
from nook.scraper import auto_match_new_series
from nook.styles import (
    DEFAULT_ACCENT,
    accent_label,
    accent_names,
    accent_palette,
    color,
    normalize_accent_name,
)
from nook.ui.icons import icon, pixmap
from nook.ui.widgets.toast import ToastNotification


class ScanWorker(QThread):
    """Background worker for scanning media libraries."""

    progress = pyqtSignal(int, int, str)
    series_found = pyqtSignal(str)
    finished = pyqtSignal(int, int)
    error = pyqtSignal(str)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    def run(self) -> None:
        try:
            scanner = LibraryScanner(self.db)
            s_count, e_count = scanner.scan_all(
                on_progress=lambda curr, total, msg: self.progress.emit(curr, total, msg),
                on_series_found=lambda name: self.series_found.emit(name)
            )
            self._auto_scrape_new_series(scanner.new_series)
            self.finished.emit(s_count, e_count)
        except Exception as e:
            self.error.emit(str(e))

    def _auto_scrape_new_series(self, new_series: list) -> None:
        """Fetch online metadata for folders discovered during this scan.

        Delegates to the shared scraper helper so the GUI and headless CLI
        behave identically. Only brand-new folders are considered, and folders
        with no close match are left exactly as they were scanned.
        """
        auto_match_new_series(
            self.db,
            new_series,
            on_progress=lambda index, total, msg: self.progress.emit(100, 100, msg),
        )


class SettingsView(QWidget):
    """Settings center for managing directories, player, themes, and hidden items."""

    theme_changed = pyqtSignal(str)       # "dark" or "light"
    accent_changed = pyqtSignal(str)      # accent preset key, e.g. "blue"
    library_rescanned = pyqtSignal(int, int)
    hidden_changed = pyqtSignal()
    streaming_sites_changed = pyqtSignal()

    def __init__(self, db: Database, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db = db
        self.scan_worker: Optional[ScanWorker] = None
        # (label, icon_name) pairs so section icons can be re-rendered on theme change
        self._card_icons: List[tuple] = []
        # accent preset key -> swatch button
        self._accent_buttons: Dict[str, QPushButton] = {}

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 16, 24, 20)
        main_layout.setSpacing(14)

        # Header Title
        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        self.header_icon = QLabel(self)
        self.header_icon.setPixmap(pixmap("gear", size=22))
        header_row.addWidget(self.header_icon)

        header = QLabel("Settings & Configuration", self)
        h_font = QFont(self.font())
        h_font.setPointSize(20)
        h_font.setBold(True)
        header.setFont(h_font)
        header_row.addWidget(header)
        header_row.addStretch()
        main_layout.addLayout(header_row)

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
        dirs_card, dirs_layout = self._create_card(
            "folder", "Library Root Folders",
            "Nook scans subfolders one level deep as distinct Series or Collections.",
        )
        dirs_layout.setSpacing(12)

        self.dirs_list = QListWidget(dirs_card)
        self.dirs_list.setFixedHeight(120)
        dirs_layout.addWidget(self.dirs_list)

        dir_btns = QHBoxLayout()
        dir_btns.setSpacing(10)

        add_dir_btn = QPushButton("Add Folder...", dirs_card)
        add_dir_btn.setIcon(icon("plus", size=15))
        add_dir_btn.setIconSize(QSize(15, 15))
        add_dir_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_dir_btn.clicked.connect(self._add_root_directory)
        dir_btns.addWidget(add_dir_btn)

        self.remove_dir_btn = QPushButton("Remove Selected", dirs_card)
        self.remove_dir_btn.setObjectName("dangerBtn")
        self.remove_dir_btn.setIcon(icon("close", size=15))
        self.remove_dir_btn.setIconSize(QSize(15, 15))
        self.remove_dir_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.remove_dir_btn.clicked.connect(self._remove_root_directory)
        dir_btns.addWidget(self.remove_dir_btn)

        dir_btns.addStretch()

        self.scan_now_btn = QPushButton("Scan Library Now", dirs_card)
        self.scan_now_btn.setObjectName("primaryBtn")
        self.scan_now_btn.setIcon(icon("refresh", size=15, color="#0A0A0A"))
        self.scan_now_btn.setIconSize(QSize(15, 15))
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
        self.scan_status_lbl.setObjectName("mutedText")
        dirs_layout.addWidget(self.scan_status_lbl)

        content_layout.addWidget(dirs_card)

        # -------------------------------------------------------------
        # 2. Appearance & Theme Section
        # -------------------------------------------------------------
        theme_card, theme_layout = self._create_card(
            "palette", "Appearance & UI",
            "Pick a theme and choose what the library shows you.",
        )
        theme_layout.setSpacing(12)

        theme_radio_layout = QHBoxLayout()
        theme_radio_layout.setSpacing(20)

        theme_lbl = QLabel("App Theme:", theme_card)
        theme_lbl.setStyleSheet("font-weight: 600;")
        theme_radio_layout.addWidget(theme_lbl)

        self.theme_group = QButtonGroup(theme_card)
        self.radio_dark = QRadioButton("Dark (Black)", theme_card)
        self.radio_light = QRadioButton("Light", theme_card)
        self.radio_dark.setIcon(icon("moon", size=15))
        self.radio_dark.setIconSize(QSize(15, 15))
        self.radio_light.setIcon(icon("sun", size=15))
        self.radio_light.setIconSize(QSize(15, 15))
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

        # Accent colour presets -------------------------------------------------
        accent_header = QHBoxLayout()
        accent_header.setSpacing(10)
        accent_lbl = QLabel("Accent Colour:", theme_card)
        accent_lbl.setStyleSheet("font-weight: 600;")
        accent_header.addWidget(accent_lbl)
        self.accent_name_lbl = QLabel("", theme_card)
        self.accent_name_lbl.setObjectName("mutedText")
        accent_header.addWidget(self.accent_name_lbl)
        accent_header.addStretch()
        theme_layout.addLayout(accent_header)

        self.accent_group = QButtonGroup(theme_card)
        self.accent_group.setExclusive(True)
        accent_row = QHBoxLayout()
        accent_row.setSpacing(9)
        accent_row.setContentsMargins(0, 0, 0, 0)
        for accent_key in accent_names():
            btn = QPushButton(theme_card)
            btn.setCheckable(True)
            btn.setFixedSize(28, 28)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setToolTip(accent_label(accent_key))
            btn.clicked.connect(
                lambda checked, key=accent_key: self._on_accent_selected(key, checked)
            )
            self.accent_group.addButton(btn)
            self._accent_buttons[accent_key] = btn
            accent_row.addWidget(btn)
        accent_row.addStretch()
        theme_layout.addLayout(accent_row)

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
        player_card, player_layout = self._create_card(
            "play", "Media Player Launcher",
            "Choose the external player used to open videos, with timestamp resume support.",
        )
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
        path_lbl.setObjectName("mutedText")
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
        hidden_card, hidden_layout = self._create_card(
            "eye-off", "Hidden Series",
            "Items currently hidden from the library grid.",
        )
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
        scraper_card, scraper_layout = self._create_card(
            "globe", "Online Metadata Providers",
            "Configure public scrapers to fetch official series information and artwork.",
        )
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
        tmdb_lbl.setObjectName("mutedText")
        tmdb_row.addWidget(tmdb_lbl)

        self.tmdb_key_input = QLineEdit(scraper_card)
        self.tmdb_key_input.setText(self.db.get_setting("tmdb_api_key", ""))
        self.tmdb_key_input.setPlaceholderText("Enter optional TMDB v3 API Key...")
        self.tmdb_key_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.tmdb_key_input.textChanged.connect(lambda text: self.db.set_setting("tmdb_api_key", text.strip()))
        tmdb_row.addWidget(self.tmdb_key_input, stretch=1)
        scraper_layout.addLayout(tmdb_row)

        # Automatic matching for newly added folders
        self.auto_scrape_check = QCheckBox(
            "Automatically fetch online info for newly added folders", scraper_card
        )
        self.auto_scrape_check.setToolTip(
            "When a new folder is recognised during a scan, search online "
            "providers and apply the closest title match. Folders with no "
            "match are left exactly as they were scanned."
        )
        self.auto_scrape_check.setChecked(
            self.db.get_setting("auto_scrape_new_series", "true") == "true"
        )
        self.auto_scrape_check.toggled.connect(
            lambda checked: self.db.set_setting(
                "auto_scrape_new_series", "true" if checked else "false"
            )
        )
        scraper_layout.addWidget(self.auto_scrape_check)

        content_layout.addWidget(scraper_card)

        # -------------------------------------------------------------
        # 6. Streaming Sites Manager
        # -------------------------------------------------------------
        stream_card, stream_layout = self._create_card(
            "tv", "Streaming Sites",
            "Register streaming sites (e.g. HiAnime, Miruru) to browse their "
            "catalogue in the Browse tab and import shows into your library.",
        )
        stream_layout.setSpacing(12)

        stream_row = QHBoxLayout()
        stream_row.setSpacing(10)

        self.stream_url_input = QLineEdit(stream_card)
        self.stream_url_input.setPlaceholderText("Paste a site base URL")
        self.stream_url_input.returnPressed.connect(self._add_streaming_site)
        stream_row.addWidget(self.stream_url_input, stretch=1)

        add_stream_btn = QPushButton("Add", stream_card)
        add_stream_btn.setObjectName("primaryBtn")
        add_stream_btn.setIcon(icon("plus", size=15, color="#0A0A0A"))
        add_stream_btn.setIconSize(QSize(15, 15))
        add_stream_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_stream_btn.clicked.connect(self._add_streaming_site)
        stream_row.addWidget(add_stream_btn)

        stream_layout.addLayout(stream_row)

        self.stream_sites_list = QListWidget(stream_card)
        self.stream_sites_list.setFixedHeight(110)
        self.stream_sites_list.setToolTip("Double-click a site to rename it")
        self.stream_sites_list.itemDoubleClicked.connect(
            lambda _item: self._rename_streaming_site()
        )
        stream_layout.addWidget(self.stream_sites_list)

        stream_buttons = QHBoxLayout()
        stream_buttons.setSpacing(10)

        rename_stream_btn = QPushButton("Rename Selected", stream_card)
        rename_stream_btn.setIcon(icon("pencil", size=15))
        rename_stream_btn.setIconSize(QSize(15, 15))
        rename_stream_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        rename_stream_btn.clicked.connect(self._rename_streaming_site)
        stream_buttons.addWidget(rename_stream_btn)

        remove_stream_btn = QPushButton("Remove Selected", stream_card)
        remove_stream_btn.setObjectName("dangerBtn")
        remove_stream_btn.setIcon(icon("trash", size=15))
        remove_stream_btn.setIconSize(QSize(15, 15))
        remove_stream_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        remove_stream_btn.clicked.connect(self._remove_streaming_site)
        stream_buttons.addWidget(remove_stream_btn)

        stream_buttons.addStretch()
        stream_layout.addLayout(stream_buttons)

        content_layout.addWidget(stream_card)

        # -------------------------------------------------------------
        # 7. Database & Application Data Info Section
        # -------------------------------------------------------------
        info_card, info_layout = self._create_card(
            "download", "Data & Storage",
            "Where Nook keeps its database and managed cover artwork.",
        )
        info_layout.setSpacing(8)

        db_path_lbl = QLabel(f"SQLite Database: <b>{get_db_path()}</b>", info_card)
        db_path_lbl.setObjectName("mutedText")
        info_layout.addWidget(db_path_lbl)

        covers_dir = get_covers_dir()
        cover_count = len(list(covers_dir.glob("*")))
        covers_lbl = QLabel(f"Managed Covers Cache: <b>{covers_dir}</b> ({cover_count} saved images)", info_card)
        covers_lbl.setObjectName("mutedText")
        info_layout.addWidget(covers_lbl)

        open_app_dir_btn = QPushButton("Open Storage Folder", info_card)
        open_app_dir_btn.setIcon(icon("folder-open", size=15))
        open_app_dir_btn.setIconSize(QSize(15, 15))
        open_app_dir_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        open_app_dir_btn.clicked.connect(self._open_appdata_folder)
        info_layout.addWidget(open_app_dir_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        content_layout.addWidget(info_card)

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # Initial data load
        self.refresh()

    def _create_card(self, icon_name: str, title: str, subtitle: str):
        """Build a frameless settings card with an icon + title header.

        Returns ``(card, body_layout)`` where ``body_layout`` is ready for the
        section's own widgets.
        """
        card = QFrame(self)
        card.setObjectName("episodeRow")

        outer = QVBoxLayout(card)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)

        icon_lbl = QLabel(card)
        icon_lbl.setPixmap(pixmap(icon_name, size=18))
        icon_lbl.setFixedSize(20, 20)
        self._card_icons.append((icon_lbl, icon_name))
        header.addWidget(icon_lbl)

        title_lbl = QLabel(title, card)
        title_lbl.setObjectName("sectionTitle")
        header.addWidget(title_lbl)
        header.addStretch()
        outer.addLayout(header)

        if subtitle:
            sub_lbl = QLabel(subtitle, card)
            sub_lbl.setObjectName("mutedText")
            sub_lbl.setWordWrap(True)
            outer.addWidget(sub_lbl)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        outer.addLayout(body)

        return card, body

    def refresh_icons(self) -> None:
        """Re-render section icons after a theme change."""
        self.header_icon.setPixmap(pixmap("gear", size=22))
        for label, name in self._card_icons:
            label.setPixmap(pixmap(name, size=18))
        self.radio_dark.setIcon(icon("moon", size=15))
        self.radio_light.setIcon(icon("sun", size=15))
        self._restyle_accent_swatches(self.db.get_setting("theme", "dark"))
        self.refresh()

    def refresh(self) -> None:
        """Reload root directories and hidden series."""
        # 1. Root directories
        self.dirs_list.clear()
        roots = self.db.get_root_directories()
        for r in roots:
            item = QListWidgetItem(f"  {r['path']}")
            item.setIcon(icon("folder", size=16))
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.dirs_list.addItem(item)

        # 2. Hidden series
        self._refresh_hidden_table()

        # 3. Streaming sites
        self._refresh_stream_sites()

        # 4. Accent colour selection
        self._sync_accent_selection()

        # 5. Theme radios (kept in sync when toggled from the top bar)
        self._sync_theme_selection()

    def _sync_theme_selection(self) -> None:
        """Check the radio matching the saved theme without re-emitting."""
        theme = self.db.get_setting("theme", "dark")
        target = self.radio_light if theme == "light" else self.radio_dark
        if target.isChecked():
            return
        blocked = target.blockSignals(True)
        target.setChecked(True)
        target.blockSignals(blocked)

    def _refresh_stream_sites(self) -> None:
        """Reload the configured streaming sites list."""
        self.stream_sites_list.clear()
        for site in self.db.get_streaming_sites():
            item = QListWidgetItem(f"  {site['name']}  —  {site['base_url']}")
            item.setIcon(icon("tv", size=16))
            item.setData(Qt.ItemDataRole.UserRole, site["id"])
            self.stream_sites_list.addItem(item)

    def _add_streaming_site(self) -> None:
        url = self.stream_url_input.text().strip()
        if not url:
            ToastNotification.show_toast(self.window(), "Enter a streaming site URL first.")
            return
        site_id = self.db.add_streaming_site(url)
        if site_id is None:
            ToastNotification.show_toast(self.window(), "That does not look like a valid site URL.")
            return
        self.stream_url_input.clear()
        self._refresh_stream_sites()
        self.streaming_sites_changed.emit()
        site = self.db.get_streaming_site_by_id(site_id)
        name = site["name"] if site else url
        ToastNotification.show_toast(self.window(), f"Added streaming site: {name}")

    def _remove_streaming_site(self) -> None:
        current = self.stream_sites_list.currentItem()
        if not current:
            ToastNotification.show_toast(self.window(), "Select a streaming site to remove.")
            return
        site_id = current.data(Qt.ItemDataRole.UserRole)
        self.db.remove_streaming_site(site_id)
        self._refresh_stream_sites()
        self.streaming_sites_changed.emit()
        ToastNotification.show_toast(self.window(), "Streaming site removed.")

    def _rename_streaming_site(self) -> None:
        current = self.stream_sites_list.currentItem()
        if not current:
            ToastNotification.show_toast(self.window(), "Select a streaming site to rename.")
            return
        site_id = current.data(Qt.ItemDataRole.UserRole)
        site = self.db.get_streaming_site_by_id(site_id)
        if not site:
            return
        new_name, accepted = QInputDialog.getText(
            self,
            "Rename Streaming Site",
            "Display name:",
            QLineEdit.EchoMode.Normal,
            site.get("name", ""),
        )
        new_name = (new_name or "").strip()
        if not accepted or not new_name or new_name == site.get("name"):
            return
        self.db.rename_streaming_site(site_id, new_name)
        self._refresh_stream_sites()
        self.streaming_sites_changed.emit()
        ToastNotification.show_toast(self.window(), f"Renamed streaming site to: {new_name}")

    def _refresh_hidden_table(self) -> None:
        hidden_series = self.db.get_all_series(include_hidden=True)
        hidden_only = [s for s in hidden_series if s.get("is_hidden")]

        self.hidden_table.setRowCount(len(hidden_only))
        for row_idx, s in enumerate(hidden_only):
            title_item = QTableWidgetItem(s.get("display_title", ""))
            path_item = QTableWidgetItem(s.get("folder_path", ""))

            unhide_btn = QPushButton("Unhide", self.hidden_table)
            unhide_btn.setObjectName("secondaryBtn")
            unhide_btn.setIcon(icon("eye", size=14))
            unhide_btn.setIconSize(QSize(14, 14))
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
        self.hidden_changed.emit()
        ToastNotification.show_toast(self.window(), "Series unhidden and restored to library grid.")

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
        self.library_rescanned.emit(0, 0)
        ToastNotification.show_toast(self.window(), "Root folder removed from library.")

    def start_scan(self) -> None:
        """Trigger background library scan."""
        if self.scan_worker and self.scan_worker.isRunning():
            return

        self.scan_now_btn.setEnabled(False)
        self.scan_progress_bar.setVisible(True)
        self.scan_progress_bar.setValue(0)
        self.scan_status_lbl.setText("Starting library scan...")

        self.scan_worker = ScanWorker(self.db)
        self.scan_worker.progress.connect(self._on_scan_progress)
        self.scan_worker.series_found.connect(lambda title: self.scan_status_lbl.setText(f"Found: {title}"))
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.error.connect(self._on_scan_error)
        self.scan_worker.start()

    def _on_scan_error(self, err_msg: str) -> None:
        self.scan_now_btn.setEnabled(True)
        self.scan_progress_bar.setVisible(False)
        self.scan_status_lbl.setText(f"Scan error: {err_msg}")
        ToastNotification.show_toast(self.window(), f"Scan error: {err_msg}", duration_ms=4000)

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

    def _on_accent_selected(self, accent_key: str, checked: bool) -> None:
        if not checked:
            return
        accent_key = normalize_accent_name(accent_key)
        if self.db.get_setting("accent", DEFAULT_ACCENT) == accent_key:
            return
        self.db.set_setting("accent", accent_key)
        self.accent_changed.emit(accent_key)
        ToastNotification.show_toast(
            self.window(), f"Accent colour: {accent_label(accent_key)}"
        )

    def _sync_accent_selection(self) -> None:
        """Check the swatch matching the saved accent without re-emitting."""
        current = normalize_accent_name(self.db.get_setting("accent", DEFAULT_ACCENT))
        self.accent_name_lbl.setText(accent_label(current))
        button = self._accent_buttons.get(current)
        if button is None:
            return
        blocked = button.blockSignals(True)
        button.setChecked(True)
        button.blockSignals(blocked)

    def _restyle_accent_swatches(self, theme_name: str) -> None:
        """Paint every swatch in the colour it would apply for this theme."""
        border_hover = color("text_muted")
        border_checked = color("text_primary")
        for key, button in self._accent_buttons.items():
            swatch = accent_palette(key, theme_name)["accent"]
            button.setStyleSheet(
                "QPushButton {"
                f" background-color: {swatch};"
                " border: 2px solid transparent;"
                " border-radius: 14px;"
                " padding: 0px;"
                " min-width: 0px;"
                " min-height: 0px;"
                "}"
                "QPushButton:hover {"
                f" border-color: {border_hover};"
                "}"
                "QPushButton:checked {"
                f" border: 2px solid {border_checked};"
                "}"
            )

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
