"""Main Application Window for Nook."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction, QCursor, QFont, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nook.database import Database
from nook.player import MediaPlayer
from nook.styles import CozyTheme
from nook.ui.library_view import LibraryView
from nook.ui.series_detail import SeriesDetailView
from nook.ui.settings_view import SettingsView
from nook.ui.widgets.toast import ToastNotification


class MainWindow(QMainWindow):
    """Nook Main Application Window."""

    def __init__(self, db: Optional[Database] = None):
        super().__init__()
        self.db = db or Database()
        self.media_player = MediaPlayer(self.db)

        self.setWindowTitle("Nook — Cozy Video Library Manager")
        self.resize(1150, 780)
        self.setMinimumSize(850, 600)

        self._current_tab_index = 0
        self._previous_tab_index = 0

        self._init_ui()
        self._setup_shortcuts()
        self._apply_saved_theme()

        # Initial refresh
        self.library_view.refresh()

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # -------------------------------------------------------------
        # Top Bar Navigation & Controls
        # -------------------------------------------------------------
        self.top_bar = QWidget(self)
        self.top_bar.setObjectName("topBar")
        self.top_bar.setFixedHeight(64)

        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(20, 10, 20, 10)
        top_layout.setSpacing(16)

        # Brand Logo & Title
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(8)

        logo_lbl = QLabel("☕", self.top_bar)
        logo_font = QFont(self.font())
        logo_font.setPointSize(20)
        logo_lbl.setFont(logo_font)
        brand_layout.addWidget(logo_lbl)

        title_lbl = QLabel("Nook", self.top_bar)
        title_font = QFont(self.font())
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        brand_layout.addWidget(title_lbl)

        top_layout.addLayout(brand_layout)
        top_layout.addSpacing(16)

        # Navigation Tabs (Library, Favorites, Settings)
        self.nav_group = QButtonGroup(self.top_bar)

        self.tab_library = QPushButton("Library", self.top_bar)
        self.tab_library.setObjectName("navTab")
        self.tab_library.setProperty("active", "true")
        self.tab_library.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.tab_library.clicked.connect(lambda: self.switch_tab(0))
        self.nav_group.addButton(self.tab_library)
        top_layout.addWidget(self.tab_library)

        self.tab_favorites = QPushButton("Favorites", self.top_bar)
        self.tab_favorites.setObjectName("navTab")
        self.tab_favorites.setProperty("active", "false")
        self.tab_favorites.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.tab_favorites.clicked.connect(lambda: self.switch_tab(1))
        self.nav_group.addButton(self.tab_favorites)
        top_layout.addWidget(self.tab_favorites)

        self.tab_settings = QPushButton("Settings", self.top_bar)
        self.tab_settings.setObjectName("navTab")
        self.tab_settings.setProperty("active", "false")
        self.tab_settings.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.tab_settings.clicked.connect(lambda: self.switch_tab(2))
        self.nav_group.addButton(self.tab_settings)
        top_layout.addWidget(self.tab_settings)

        top_layout.addSpacing(20)

        # Global Search Bar
        self.search_bar = QLineEdit(self.top_bar)
        self.search_bar.setPlaceholderText("🔍 Search your library... (Ctrl+F)")
        self.search_bar.setFixedWidth(280)
        self.search_bar.setClearButtonEnabled(True)
        self.search_bar.textChanged.connect(self._on_search_text_changed)
        top_layout.addWidget(self.search_bar)

        top_layout.addStretch()

        # Rescan Quick Button
        self.quick_scan_btn = QPushButton("🔄 Rescan", self.top_bar)
        self.quick_scan_btn.setObjectName("secondaryBtn")
        self.quick_scan_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.quick_scan_btn.setToolTip("Rescan configured root folders (F5)")
        self.quick_scan_btn.clicked.connect(self._trigger_quick_scan)
        top_layout.addWidget(self.quick_scan_btn)

        # Live Theme Switcher Button
        self.theme_toggle_btn = QPushButton("🌙", self.top_bar)
        self.theme_toggle_btn.setObjectName("iconBtn")
        self.theme_toggle_btn.setFixedSize(38, 38)
        self.theme_toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.theme_toggle_btn.setToolTip("Toggle Cozy Light / Dark Mode")
        self.theme_toggle_btn.clicked.connect(self._toggle_theme)
        top_layout.addWidget(self.theme_toggle_btn)

        root_layout.addWidget(self.top_bar)

        # -------------------------------------------------------------
        # Main Content Views (QStackedWidget)
        # -------------------------------------------------------------
        self.stack = QStackedWidget(self)

        # View 0: Main Library View
        self.library_view = LibraryView(self.db, self.media_player, only_favorites=False, parent=self.stack)
        self.library_view.series_selected.connect(self.open_series_detail)
        self.library_view.open_settings_requested.connect(lambda: self.switch_tab(2))
        self.stack.addWidget(self.library_view)

        # View 1: Favorites View
        self.favorites_view = LibraryView(self.db, self.media_player, only_favorites=True, parent=self.stack)
        self.favorites_view.series_selected.connect(self.open_series_detail)
        self.favorites_view.open_settings_requested.connect(lambda: self.switch_tab(2))
        self.stack.addWidget(self.favorites_view)

        # View 2: Settings View
        self.settings_view = SettingsView(self.db, parent=self.stack)
        self.settings_view.theme_changed.connect(self.apply_theme)
        self.settings_view.library_rescanned.connect(self._on_library_rescanned)
        self.stack.addWidget(self.settings_view)

        # View 3: Series Detail View
        self.detail_view = SeriesDetailView(self.db, self.media_player, parent=self.stack)
        self.detail_view.back_requested.connect(self._on_detail_back)
        self.detail_view.series_updated.connect(self._on_series_updated)
        self.stack.addWidget(self.detail_view)

        root_layout.addWidget(self.stack)

    def _setup_shortcuts(self) -> None:
        # Ctrl+F to focus search
        shortcut_search = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_search.activated.connect(self.focus_search)

        # Esc to exit detail view or clear search
        shortcut_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        shortcut_esc.activated.connect(self._on_escape_pressed)

        # F5 to rescan
        shortcut_f5 = QShortcut(QKeySequence("F5"), self)
        shortcut_f5.activated.connect(self._trigger_quick_scan)

    def focus_search(self) -> None:
        # Switch to library tab if on settings or detail
        if self.stack.currentIndex() not in (0, 1):
            self.switch_tab(0)
        self.search_bar.setFocus()
        self.search_bar.selectAll()

    def _on_escape_pressed(self) -> None:
        if self.stack.currentIndex() == 3:
            # Inside detail view, go back
            self._on_detail_back()
        elif self.search_bar.hasFocus() or self.search_bar.text():
            self.search_bar.clear()
            self.search_bar.clearFocus()

    def switch_tab(self, index: int) -> None:
        self._previous_tab_index = self._current_tab_index
        self._current_tab_index = index

        self.tab_library.setProperty("active", "true" if index == 0 else "false")
        self.tab_favorites.setProperty("active", "true" if index == 1 else "false")
        self.tab_settings.setProperty("active", "true" if index == 2 else "false")

        # Refresh style for tab buttons
        self.tab_library.style().unpolish(self.tab_library)
        self.tab_library.style().polish(self.tab_library)
        self.tab_favorites.style().unpolish(self.tab_favorites)
        self.tab_favorites.style().polish(self.tab_favorites)
        self.tab_settings.style().unpolish(self.tab_settings)
        self.tab_settings.style().polish(self.tab_settings)

        self.stack.setCurrentIndex(index)

        # Refresh view
        if index == 0:
            self.library_view.refresh()
        elif index == 1:
            self.favorites_view.refresh()
        elif index == 2:
            self.settings_view.refresh()

    def open_series_detail(self, series_id: int) -> None:
        self.detail_view.load_series(series_id)
        self.stack.setCurrentIndex(3)

    def _on_detail_back(self) -> None:
        self.switch_tab(self._current_tab_index)

    def _on_series_updated(self, series_id: int) -> None:
        self.library_view.refresh()
        self.favorites_view.refresh()

    def _on_search_text_changed(self, text: str) -> None:
        self.library_view.set_search_query(text)
        self.favorites_view.set_search_query(text)
        # Automatically show library if in settings or detail
        if self.stack.currentIndex() not in (0, 1) and text.strip():
            self.switch_tab(0)

    def _trigger_quick_scan(self) -> None:
        ToastNotification.show_toast(self, "Starting library rescan...")
        self.settings_view.start_scan()

    def _on_library_rescanned(self, series_count: int, episode_count: int) -> None:
        self.library_view.refresh()
        self.favorites_view.refresh()

    # -------------------------------------------------------------
    # Dynamic Theme Management
    # -------------------------------------------------------------
    def _apply_saved_theme(self) -> None:
        theme = self.db.get_setting("theme", "dark")
        self.apply_theme(theme)

    def apply_theme(self, theme_name: str) -> None:
        """Apply dynamic QSS stylesheet across the entire application."""
        qss = CozyTheme.get_stylesheet(theme_name)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(qss)

        # Update toggle button icon
        if theme_name == "light":
            self.theme_toggle_btn.setText("☀️")
            self.theme_toggle_btn.setToolTip("Switch to Cozy Dark Mode")
        else:
            self.theme_toggle_btn.setText("🌙")
            self.theme_toggle_btn.setToolTip("Switch to Cozy Light Mode")

    def _toggle_theme(self) -> None:
        curr = self.db.get_setting("theme", "dark")
        next_theme = "light" if curr == "dark" else "dark"
        self.db.set_setting("theme", next_theme)
        self.apply_theme(next_theme)
        self.settings_view.refresh()
        ToastNotification.show_toast(self, f"Switched to Cozy {next_theme.capitalize()} Mode")
