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
from nook.styles import DEFAULT_ACCENT, CozyTheme, color, get_qpalette, set_active_theme
from nook.ui.browse_view import BrowseView
from nook.ui.icons import icon, pixmap, set_color
from nook.ui.library_view import LibraryView
from nook.ui.series_detail import SeriesDetailView
from nook.ui.settings_view import SettingsView
from nook.ui.widgets.toast import ToastNotification


class MainWindow(QMainWindow):
    """Nook Main Application Window."""

    # Stacked page indexes (detail is a fourth, hidden page).
    TAB_LIBRARY = 0
    TAB_FAVORITES = 1
    TAB_BROWSE = 2
    TAB_SETTINGS = 3
    TAB_DETAIL = 4

    def __init__(self, db: Optional[Database] = None):
        super().__init__()
        self.db = db or Database()
        self.media_player = MediaPlayer(self.db)

        self.setWindowTitle("Nook")
        self.resize(1150, 780)
        self.setMinimumSize(850, 600)

        self._current_tab_index = 0
        self._previous_tab_index = 0

        # Resolve the saved theme + accent before building widgets so
        # palette-aware colours are correct from the first paint.
        self._accent = self.db.get_setting("accent", DEFAULT_ACCENT) or DEFAULT_ACCENT
        set_active_theme(
            self.db.get_setting("theme", "dark") or "dark", self._accent
        )

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
        brand_layout.setSpacing(9)

        self.logo_lbl = QLabel(self.top_bar)
        self.logo_lbl.setPixmap(pixmap("coffee", size=24, color=color("accent")))
        self.logo_lbl.setFixedSize(26, 26)
        brand_layout.addWidget(self.logo_lbl)

        title_lbl = QLabel("Nook", self.top_bar)
        title_font = QFont(self.font())
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        brand_layout.addWidget(title_lbl)

        top_layout.addLayout(brand_layout)
        top_layout.addSpacing(16)

        # Navigation Tabs (Library, Favorites, Browse, Settings)
        self.nav_group = QButtonGroup(self.top_bar)

        self.tab_library = QPushButton("Library", self.top_bar)
        self.tab_library.setObjectName("navTab")
        self.tab_library.setProperty("active", "true")
        self.tab_library.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.tab_library.clicked.connect(lambda: self.switch_tab(self.TAB_LIBRARY))
        self.nav_group.addButton(self.tab_library)
        top_layout.addWidget(self.tab_library)

        self.tab_favorites = QPushButton("Favorites", self.top_bar)
        self.tab_favorites.setObjectName("navTab")
        self.tab_favorites.setProperty("active", "false")
        self.tab_favorites.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.tab_favorites.clicked.connect(lambda: self.switch_tab(self.TAB_FAVORITES))
        self.nav_group.addButton(self.tab_favorites)
        top_layout.addWidget(self.tab_favorites)

        self.tab_browse = QPushButton("Browse", self.top_bar)
        self.tab_browse.setObjectName("navTab")
        self.tab_browse.setProperty("active", "false")
        self.tab_browse.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.tab_browse.clicked.connect(lambda: self.switch_tab(self.TAB_BROWSE))
        self.nav_group.addButton(self.tab_browse)
        top_layout.addWidget(self.tab_browse)

        self.tab_settings = QPushButton("Settings", self.top_bar)
        self.tab_settings.setObjectName("navTab")
        self.tab_settings.setProperty("active", "false")
        self.tab_settings.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.tab_settings.clicked.connect(lambda: self.switch_tab(self.TAB_SETTINGS))
        self.nav_group.addButton(self.tab_settings)
        top_layout.addWidget(self.tab_settings)

        top_layout.addSpacing(20)

        # Global Search Bar
        self.search_bar = QLineEdit(self.top_bar)
        self.search_bar.setPlaceholderText("Search your library...  (Ctrl+F)")
        self.search_bar.setFixedWidth(280)
        self.search_bar.setClearButtonEnabled(True)
        self.search_bar.textChanged.connect(self._on_search_text_changed)
        self._search_action = self.search_bar.addAction(
            icon("search", size=17), QLineEdit.ActionPosition.LeadingPosition
        )
        top_layout.addWidget(self.search_bar)

        top_layout.addStretch()

        # Rescan Quick Button
        self.quick_scan_btn = QPushButton("Rescan", self.top_bar)
        self.quick_scan_btn.setObjectName("secondaryBtn")
        self.quick_scan_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.quick_scan_btn.setToolTip("Rescan configured root folders (F5)")
        self.quick_scan_btn.clicked.connect(self._trigger_quick_scan)
        top_layout.addWidget(self.quick_scan_btn)

        # Live Theme Switcher Button
        self.theme_toggle_btn = QPushButton(self.top_bar)
        self.theme_toggle_btn.setObjectName("iconBtn")
        self.theme_toggle_btn.setFixedSize(38, 38)
        self.theme_toggle_btn.setIconSize(QSize(19, 19))
        self.theme_toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.theme_toggle_btn.setToolTip("Toggle Light / Dark Mode")
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
        self.library_view.open_settings_requested.connect(lambda: self.switch_tab(self.TAB_SETTINGS))
        self.stack.addWidget(self.library_view)

        # View 1: Favorites View
        self.favorites_view = LibraryView(self.db, self.media_player, only_favorites=True, parent=self.stack)
        self.favorites_view.series_selected.connect(self.open_series_detail)
        self.favorites_view.open_settings_requested.connect(lambda: self.switch_tab(self.TAB_SETTINGS))
        self.stack.addWidget(self.favorites_view)

        # View 2: Browse Streaming Sites View
        self.browse_view = BrowseView(self.db, parent=self.stack)
        self.browse_view.series_added.connect(self._on_series_added)
        self.stack.addWidget(self.browse_view)

        # View 3: Settings View
        self.settings_view = SettingsView(self.db, parent=self.stack)
        self.settings_view.theme_changed.connect(self.apply_theme)
        self.settings_view.accent_changed.connect(self.set_accent)
        self.settings_view.library_rescanned.connect(self._on_library_rescanned)
        self.settings_view.hidden_changed.connect(lambda: (self.library_view.refresh(), self.favorites_view.refresh()))
        self.settings_view.streaming_sites_changed.connect(self.browse_view.refresh)
        self.stack.addWidget(self.settings_view)

        # View 4: Series Detail View
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

    def _nav_buttons(self):
        return (
            (self.tab_library, self.TAB_LIBRARY),
            (self.tab_favorites, self.TAB_FAVORITES),
            (self.tab_browse, self.TAB_BROWSE),
            (self.tab_settings, self.TAB_SETTINGS),
        )

    def _sync_nav_tabs(self, active_index: int) -> None:
        for button, tab_index in self._nav_buttons():
            button.setProperty("active", "true" if tab_index == active_index else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def focus_search(self) -> None:
        # Switch to library tab if on browse/settings/detail
        if self.stack.currentIndex() not in (self.TAB_LIBRARY, self.TAB_FAVORITES):
            self.switch_tab(self.TAB_LIBRARY)
        self.search_bar.setFocus()
        self.search_bar.selectAll()

    def _on_escape_pressed(self) -> None:
        if self.stack.currentIndex() == self.TAB_DETAIL:
            # Inside detail view, go back
            self._on_detail_back()
        elif self.search_bar.hasFocus() or self.search_bar.text():
            self.search_bar.clear()
            self.search_bar.clearFocus()

    def switch_tab(self, index: int) -> None:
        self._previous_tab_index = self._current_tab_index
        self._current_tab_index = index

        self._sync_nav_tabs(index)
        self.stack.setCurrentIndex(index)

        # Refresh view
        if index == self.TAB_LIBRARY:
            self.library_view.refresh()
        elif index == self.TAB_FAVORITES:
            self.favorites_view.refresh()
        elif index == self.TAB_BROWSE:
            self.browse_view.refresh()
        elif index == self.TAB_SETTINGS:
            self.settings_view.refresh()

    def open_series_detail(self, series_id: int) -> None:
        self.detail_view.load_series(series_id)
        self.stack.setCurrentIndex(self.TAB_DETAIL)

    def _on_detail_back(self) -> None:
        self.switch_tab(self._current_tab_index)

    def _on_series_updated(self, series_id: int) -> None:
        self.library_view.refresh()
        self.favorites_view.refresh()

    def _on_series_added(self, series_id: int) -> None:
        """A streaming show was imported - surface it in the library grids."""
        self._on_series_updated(series_id)

    def _on_search_text_changed(self, text: str) -> None:
        self.library_view.set_search_query(text)
        self.favorites_view.set_search_query(text)
        # Automatically show library if on browse/settings/detail
        if self.stack.currentIndex() not in (self.TAB_LIBRARY, self.TAB_FAVORITES) and text.strip():
            self.switch_tab(self.TAB_LIBRARY)

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
        accent = self.db.get_setting("accent", DEFAULT_ACCENT) or DEFAULT_ACCENT
        self.apply_theme(theme, accent)

    def apply_theme(self, theme_name: str, accent_name: Optional[str] = None) -> None:
        """Apply dynamic QSS stylesheet across the entire application."""
        accent = accent_name or self._accent or DEFAULT_ACCENT
        self._accent = accent
        qss = CozyTheme.get_stylesheet(theme_name, accent)
        app = QApplication.instance()
        qpalette = get_qpalette(theme_name, accent)
        if app:
            app.setStyleSheet(qss)
            app.setPalette(qpalette)
        # Also assign the palette to the window so widgets built before the
        # theme was resolved pick up the new colours as well.
        self.setPalette(qpalette)

        # Icons are stroked in the current text colour so they stay legible.
        set_color("#17171A" if theme_name == "light" else "#E9E9E9")
        self._refresh_icons(theme_name)

    def set_accent(self, accent_name: str) -> None:
        """Persist and apply a new accent colour preset."""
        self.db.set_setting("accent", accent_name)
        theme = self.db.get_setting("theme", "dark")
        self.apply_theme(theme, accent_name)

    def _refresh_icons(self, theme_name: str) -> None:
        """Re-apply icons to widgets that live for the whole session."""
        palette = CozyTheme.get_palette(theme_name, self._accent)
        self.logo_lbl.setPixmap(pixmap("coffee", size=24, color=palette["accent"]))
        self.quick_scan_btn.setIcon(icon("refresh", size=17))
        self.quick_scan_btn.setIconSize(QSize(17, 17))
        self.theme_toggle_btn.setIcon(icon("sun" if theme_name == "light" else "moon", size=19))
        self._search_action.setIcon(icon("search", size=17))

        for view in (
            self.library_view,
            self.favorites_view,
            self.browse_view,
            self.settings_view,
            self.detail_view,
        ):
            refresh = getattr(view, "refresh_icons", None)
            if callable(refresh):
                refresh()

    def _toggle_theme(self) -> None:
        curr = self.db.get_setting("theme", "dark")
        next_theme = "light" if curr == "dark" else "dark"
        self.db.set_setting("theme", next_theme)
        self.apply_theme(next_theme)
        self.settings_view.refresh()
        ToastNotification.show_toast(self, f"Switched to {'Light' if next_theme == 'light' else 'Dark'} Mode")
