"""Browse tab: search online streaming sites and import shows into Nook."""

from __future__ import annotations

import concurrent.futures
from typing import Any, Callable, Dict, List, Optional

import requests
from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nook.database import Database
from nook.player import open_url
from nook.scraper import OnlineMetadataScraper
from nook.streaming import (
    StreamResult,
    fetch_remote_image_bytes,
    provider_for_site,
)
from nook.styles import color
from nook.ui.icons import icon, pixmap
from nook.ui.widgets.flow_layout import FlowLayout
from nook.ui.widgets.poster_widget import PosterWidget
from nook.ui.widgets.toast import ToastNotification

# How many recent shows are shown first, how many the worker requests from the
# site in one go, and how many extra cards each "Show More" press reveals.
# The request size is larger than the initial view because listing pages differ
# in size (AnimeIDHentai returns ~40 per page, Elisworld ~24, TMDB 20, Miruro
# 15); downloading the whole page into the local buffer avoids skipping rows.
RECENT_INITIAL = 20
RECENT_BATCH = 40
SHOW_MORE_STEP = 5


def _load_posters(
    site: Dict[str, Any],
    items: List[Dict[str, Any]],
    on_poster: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Fetch result posters into memory for display only.

    The bytes are attached to each result as ``poster_bytes`` and never
    written to disk - Nook's covers folder is only used when a show is
    actually added to the library.

    Artwork is reported through ``on_poster`` as soon as each image arrives
    instead of waiting for the whole batch, so cards fill in progressively.
    Items are submitted in display order, which gives the visible cards the
    first available download slots.
    """
    targets = [item for item in items if item.get("poster_url")]
    if not targets:
        return

    referer = site.get("base_url") or ""
    # Reuse connections across the batch: a fresh TLS handshake per poster is
    # a large part of the delay when a site's CDN is slow.
    session = requests.Session()

    def fetch(item: Dict[str, Any]):
        return item, fetch_remote_image_bytes(
            item["poster_url"], timeout=8, referer=referer, session=session
        )

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(fetch, item) for item in targets]
            for future in concurrent.futures.as_completed(futures):
                try:
                    item, data = future.result()
                except Exception:
                    continue
                if not data:
                    continue
                item["poster_bytes"] = data
                if on_poster is not None:
                    try:
                        on_poster(item)
                    except Exception:
                        pass
    except Exception:
        pass
    finally:
        try:
            session.close()
        except Exception:
            pass


class StreamSearchWorker(QThread):
    """Runs a streaming-site search off the UI thread and caches posters."""

    results = pyqtSignal(list)
    poster_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, db: Database, site: Dict[str, Any], query: str):
        super().__init__()
        self.db = db
        self.site = dict(site)
        self.query = query

    def run(self) -> None:
        try:
            provider = provider_for_site(self.site)
            found = provider.search(self.query)
            data = [r.as_dict() for r in found]
            # Surface the cards immediately, then fill in their artwork.
            self.results.emit(data)
            _load_posters(self.site, data, on_poster=self.poster_ready.emit)
        except Exception as exc:  # pragma: no cover - defensive
            self.error.emit(str(exc))


class StreamRecentWorker(QThread):
    """Fetch a streaming site's latest shows off the UI thread."""

    results = pyqtSignal(list, int)   # show dicts, page number
    poster_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        db: Database,
        site: Dict[str, Any],
        page: int = 1,
        limit: int = RECENT_BATCH,
    ):
        super().__init__()
        self.db = db
        self.site = dict(site)
        self.page = max(1, int(page or 1))
        self.limit = max(1, int(limit or RECENT_BATCH))

    def run(self) -> None:
        try:
            provider = provider_for_site(self.site)
            found = provider.fetch_recent(limit=self.limit, page=self.page)
            data = [r.as_dict() for r in found]
            # Surface the cards immediately, then fill in their artwork.
            self.results.emit(data, self.page)
            _load_posters(self.site, data, on_poster=self.poster_ready.emit)
        except Exception as exc:  # pragma: no cover - defensive
            self.error.emit(str(exc))


class StreamImportWorker(QThread):
    """Fetch a show's episodes and import it into the local library."""

    imported = pyqtSignal(int, str)   # series_id, applied title ("" when unmatched)
    error = pyqtSignal(str)

    def __init__(self, db: Database, site: Dict[str, Any], result: Dict[str, Any]):
        super().__init__()
        self.db = db
        self.site = dict(site)
        self.result = dict(result)

    def run(self) -> None:
        try:
            provider = provider_for_site(self.site)
            fields = StreamResult.__dataclass_fields__.keys()
            stream_result = StreamResult(**{k: self.result.get(k, "") for k in fields})

            episodes = provider.fetch_episodes(stream_result)
            payload = [ep.as_dict() for ep in episodes]
            if not payload and stream_result.url:
                # No episode list found - keep a single entry pointing at the
                # show page so the series is still playable (opens in browser).
                site_name = self.site.get("name") or "site"
                payload = [{
                    "title": f"Watch on {site_name}",
                    "url": stream_result.url,
                    "number": 0,
                    "season_number": 1,
                    "season_name": "Season 1",
                }]

            title = stream_result.title or "Untitled"
            year = stream_result.year or ""
            display_title = f"{title} ({year})" if year and year not in title else title
            tag = self.site.get("name")

            series_id = self.db.add_streaming_series(
                source_type=stream_result.source_type or self.site.get("source_type") or "stream",
                source_id=stream_result.source_id,
                title=display_title,
                source_url=stream_result.url,
                poster_path=self._persist_poster(stream_result),
                description=stream_result.description,
                tags=[tag] if tag else None,
                episodes=payload,
            )

            # Pull in the closest online metadata match so the show lands in
            # the library with a proper title, synopsis, tags and poster.
            matched_title = self._apply_online_info(
                series_id,
                display_title,
                fallback_description=stream_result.description,
                fallback_tags=[tag] if tag else None,
            )
            self.imported.emit(series_id, matched_title or "")
        except Exception as exc:  # pragma: no cover - defensive
            self.error.emit(str(exc))

    def _persist_poster(self, stream_result: StreamResult) -> str:
        """Save the show's artwork into Nook's managed covers folder.

        Browse results keep their posters in memory only, so this is the point
        where a poster becomes a real, permanent local file - and only because
        the show is being added to the library.
        """
        if stream_result.poster_path:
            return stream_result.poster_path

        data = self.result.get("poster_bytes")
        if not data and stream_result.poster_url:
            data = fetch_remote_image_bytes(
                stream_result.poster_url,
                referer=self.site.get("base_url") or "",
            )
        if not data:
            return ""
        try:
            prefix = f"stream_{stream_result.source_type or 'site'}"
            return self.db.save_cover_image(data, prefix=prefix)
        except Exception:
            return ""

    def _apply_online_info(
        self,
        series_id: int,
        query: str,
        fallback_description: str = "",
        fallback_tags: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Apply the closest online match to a freshly imported show.

        Returns the applied display title, or ``None`` when nothing matched
        closely enough (in which case the imported data is kept as-is).
        """
        try:
            scraper = OnlineMetadataScraper(self.db)
            best = scraper.find_best_result(query)
            if not best:
                return None
            return scraper.apply_result_to_series(
                series_id,
                best,
                fallback_title=query,
                fallback_description=fallback_description,
                fallback_tags=fallback_tags,
                # Stream imports have no local artwork, so a poster is welcome.
                download_cover=True,
            )
        except Exception:
            return None


class StreamResultCard(QFrame):
    """A single search result card with Open and "Add to Library" actions."""

    add_requested = pyqtSignal(dict)
    open_requested = pyqtSignal(dict)

    CARD_WIDTH = 210
    POSTER_HEIGHT = 262

    def __init__(
        self,
        result: Dict[str, Any],
        site_name: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.result = result
        self.setObjectName("seriesCard")
        self.setFixedWidth(self.CARD_WIDTH)

        self._init_ui(site_name)

    def _init_ui(self, site_name: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.setSpacing(8)

        poster_container = QWidget(self)
        poster_container.setFixedSize(self.CARD_WIDTH - 16, self.POSTER_HEIGHT)
        poster_layout = QVBoxLayout(poster_container)
        poster_layout.setContentsMargins(0, 0, 0, 0)
        poster_layout.setSpacing(0)

        title = self.result.get("title", "")
        self.poster = PosterWidget(
            image_path=self.result.get("poster_path") or None,
            image_bytes=self.result.get("poster_bytes"),
            title=title,
            corner_radius=12,
            fixed_size=QSize(self.CARD_WIDTH - 16, self.POSTER_HEIGHT),
            parent=poster_container,
        )
        poster_layout.addWidget(self.poster)
        layout.addWidget(poster_container)

        # Source pill (top-left of the poster)
        if site_name:
            pill = QFrame(poster_container)
            pill.setStyleSheet(
                "QFrame { background-color: rgba(0, 0, 0, 0.62); border: none; border-radius: 9px; }"
            )
            pill.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            pill_layout = QHBoxLayout(pill)
            pill_layout.setContentsMargins(7, 3, 9, 3)
            pill_layout.setSpacing(5)
            ic = QLabel(pill)
            ic.setPixmap(pixmap("tv", size=12, color="#FFFFFF"))
            ic.setStyleSheet("background: transparent;")
            pill_layout.addWidget(ic)
            tx = QLabel(site_name, pill)
            tx.setStyleSheet("color: #FFFFFF; font-size: 10px; font-weight: 700; background: transparent;")
            pill_layout.addWidget(tx)
            pill.adjustSize()
            pill.move(8, 8)

        # Title
        self.title_lbl = QLabel(title or "Untitled", self)
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setMaximumHeight(38)
        t_font = QFont(self.font())
        t_font.setPointSize(13)
        t_font.setBold(True)
        self.title_lbl.setFont(t_font)
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.title_lbl)

        # Meta (year)
        year = self.result.get("year") or ""
        self.meta_lbl = QLabel(year or "Online stream", self)
        self.meta_lbl.setStyleSheet(f"color: {color('text_muted')}; font-size: 11px; font-weight: 500;")
        layout.addWidget(self.meta_lbl)

        # Action row: Add to Library + Open (without adding)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)

        self.add_btn = QPushButton("Add to Library", self)
        self.add_btn.setObjectName("primaryBtn")
        self.add_btn.setIcon(icon("plus", size=14, color="#0A0A0A"))
        self.add_btn.setIconSize(QSize(14, 14))
        self.add_btn.setFixedHeight(32)
        self.add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.add_btn.clicked.connect(lambda: self.add_requested.emit(self.result))
        actions.addWidget(self.add_btn, stretch=1)

        self.open_btn = QPushButton(self)
        self.open_btn.setObjectName("secondaryBtn")
        self.open_btn.setIcon(icon("external-link", size=15))
        self.open_btn.setIconSize(QSize(15, 15))
        self.open_btn.setFixedSize(38, 32)
        self.open_btn.setToolTip("Open this show on the streaming site (without adding it)")
        self.open_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.open_btn.clicked.connect(lambda: self.open_requested.emit(self.result))
        actions.addWidget(self.open_btn)

        layout.addLayout(actions)

    def set_poster_bytes(self, data: Optional[bytes]) -> None:
        """Apply artwork that finished downloading after the card was shown."""
        if not data:
            return
        self.result["poster_bytes"] = data
        self.poster.set_image(
            self.result.get("poster_path") or None,
            title=self.result.get("title", ""),
            image_bytes=data,
        )

    def set_added(self, added: bool) -> None:
        """Mark the result as already present in the library."""
        if added:
            self.add_btn.setText("In Library")
            self.add_btn.setObjectName("secondaryBtn")
            self.add_btn.setIcon(icon("check", size=14))
            self.add_btn.setEnabled(False)
        else:
            self.add_btn.setText("Add to Library")
            self.add_btn.setObjectName("primaryBtn")
            self.add_btn.setIcon(icon("plus", size=14, color="#0A0A0A"))
            self.add_btn.setEnabled(True)
        self.add_btn.style().unpolish(self.add_btn)
        self.add_btn.style().polish(self.add_btn)


class BrowseView(QWidget):
    """Browse and import shows from user-configured streaming sites."""

    series_added = pyqtSignal(int)  # series_id

    def __init__(self, db: Database, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db = db
        self._results: List[Dict[str, Any]] = []
        self._cards: Dict[Any, StreamResultCard] = {}
        self._visible_count = 0
        self._recent_mode = False
        self._recent_page = 0
        self._recent_exhausted = False
        self._recent_loading = False
        self._recent_site_id: Optional[int] = None
        self._request_token = 0
        self._last_site_name = ""
        self._search_loading = False
        self._search_workers: List[StreamSearchWorker] = []
        self._recent_workers: List[StreamRecentWorker] = []
        self.search_worker: Optional[StreamSearchWorker] = None
        self.recent_worker: Optional[StreamRecentWorker] = None
        self.import_worker: Optional[StreamImportWorker] = None

        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 14, 20, 14)
        main_layout.setSpacing(12)

        # Header
        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        self.header_icon = QLabel(self)
        self.header_icon.setPixmap(pixmap("tv", size=22))
        header_row.addWidget(self.header_icon)

        header = QLabel("Browse Streaming Sites", self)
        h_font = QFont(self.font())
        h_font.setPointSize(20)
        h_font.setBold(True)
        header.setFont(h_font)
        header_row.addWidget(header)
        header_row.addStretch()
        main_layout.addLayout(header_row)

        # Controls: site selector + search
        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.site_combo = QComboBox(self)
        self.site_combo.setMinimumWidth(180)
        self.site_combo.setToolTip("Streaming site to search")
        self.site_combo.currentIndexChanged.connect(self._on_site_changed)
        controls.addWidget(self.site_combo)

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search for a show...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self.start_search)
        controls.addWidget(self.search_input, stretch=1)

        self.search_btn = QPushButton("Search", self)
        self.search_btn.setObjectName("primaryBtn")
        self.search_btn.setIcon(icon("search", size=15, color="#0A0A0A"))
        self.search_btn.setIconSize(QSize(15, 15))
        self.search_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.search_btn.clicked.connect(self.start_search)
        controls.addWidget(self.search_btn)

        self.recent_btn = QPushButton("Show Recent", self)
        self.recent_btn.setObjectName("secondaryBtn")
        self.recent_btn.setIcon(icon("clock", size=15))
        self.recent_btn.setIconSize(QSize(15, 15))
        self.recent_btn.setToolTip("Show the newest shows added to this site")
        self.recent_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.recent_btn.clicked.connect(lambda: self.load_recent(reset=True))
        controls.addWidget(self.recent_btn)

        main_layout.addLayout(controls)

        self.status_lbl = QLabel("", self)
        self.status_lbl.setObjectName("mutedText")
        main_layout.addWidget(self.status_lbl)

        # Results grid
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.grid_container = QWidget()
        self.grid_layout = FlowLayout(self.grid_container, margin=4, h_spacing=18, v_spacing=22)
        self.scroll_area.setWidget(self.grid_container)
        main_layout.addWidget(self.scroll_area)

        # Progressive reveal for the recent-shows listing.
        self.show_more_row = QWidget(self)
        show_more_layout = QHBoxLayout(self.show_more_row)
        show_more_layout.setContentsMargins(0, 0, 0, 0)
        show_more_layout.setSpacing(0)
        show_more_layout.addStretch()
        self.show_more_btn = QPushButton("Show More", self.show_more_row)
        self.show_more_btn.setObjectName("secondaryBtn")
        self.show_more_btn.setIcon(icon("chevron-down", size=14))
        self.show_more_btn.setIconSize(QSize(14, 14))
        self.show_more_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.show_more_btn.clicked.connect(self._show_more)
        show_more_layout.addWidget(self.show_more_btn)
        show_more_layout.addStretch()
        self.show_more_row.setVisible(False)
        main_layout.addWidget(self.show_more_row)

        # Empty / placeholder state
        self.empty_widget = QWidget(self)
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(12)

        self.empty_icon = QLabel(self.empty_widget)
        self.empty_icon.setPixmap(pixmap("tv", size=72))
        self.empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_icon)

        self.empty_title = QLabel("Browse Streaming Sites", self.empty_widget)
        empty_font = QFont(self.font())
        empty_font.setPointSize(18)
        empty_font.setBold(True)
        self.empty_title.setFont(empty_font)
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)

        self.empty_subtitle = QLabel("", self.empty_widget)
        self.empty_subtitle.setWordWrap(True)
        self.empty_subtitle.setStyleSheet(f"color: {color('text_muted')}; font-size: 13px;")
        self.empty_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_subtitle)

        main_layout.addWidget(self.empty_widget)

        self.refresh()

    # ------------------------------------------------------------------
    # Data / state
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Reload the configured streaming sites into the selector."""
        previous = self.site_combo.currentData()
        self.site_combo.blockSignals(True)
        self.site_combo.clear()
        sites = self.db.get_streaming_sites()
        for site in sites:
            self.site_combo.addItem(site["name"], site["id"])
        if previous is not None:
            idx = self.site_combo.findData(previous)
            if idx >= 0:
                self.site_combo.setCurrentIndex(idx)
        self.site_combo.blockSignals(False)

        has_sites = bool(sites)
        self.site_combo.setEnabled(has_sites)
        self.search_input.setEnabled(has_sites)
        self.search_btn.setEnabled(has_sites and not self._is_searching())
        self.recent_btn.setEnabled(has_sites and not self._recent_loading)

        if not has_sites:
            self._results = []
            self._visible_count = 0
            self._recent_mode = False
            self._recent_exhausted = True
            self._clear_grid()
            self._show_empty(
                "No Streaming Sites Yet",
                "Add a streaming site URL in Settings ➔ Streaming Sites, "
                "then come back here to browse its catalogue.",
            )
        else:
            self.status_lbl.setText("")
            if self._results:
                self._render_results()
            else:
                self._show_empty(
                    "Search a Streaming Site",
                    "Pick a site and hit Search, or click Show Recent to see "
                    "the newest shows added to it.",
                )
        self._update_show_more()

    def refresh_icons(self) -> None:
        """Re-render icons after a theme change."""
        self.header_icon.setPixmap(pixmap("tv", size=22))
        self.empty_icon.setPixmap(pixmap("tv", size=72))
        self.search_btn.setIcon(icon("search", size=15, color="#0A0A0A"))
        self.recent_btn.setIcon(icon("clock", size=15))
        self.show_more_btn.setIcon(icon("chevron-down", size=14))
        self._render_results()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def _is_searching(self) -> bool:
        # Only the fetch phase counts: the worker keeps running while it fills
        # in posters, and that should not block a new search or Show More.
        return self._search_loading

    def _is_loading_recent(self) -> bool:
        return self._recent_loading

    def _on_site_changed(self, _index: int) -> None:
        """Switching sites shows that site's newest shows by default."""
        if not self.site_combo.isEnabled():
            return
        self._request_token += 1
        self._recent_loading = False
        self.load_recent(reset=True)

    def start_search(self) -> None:
        if self._is_searching():
            return
        site_id = self.site_combo.currentData()
        query = self.search_input.text().strip()
        if site_id is None:
            ToastNotification.show_toast(self.window(), "Add a streaming site in Settings first.")
            return
        if not query:
            # An empty search is a request for the site's latest shows.
            self.load_recent(reset=True)
            return

        site = self.db.get_streaming_site_by_id(site_id)
        if not site:
            ToastNotification.show_toast(self.window(), "That streaming site no longer exists.")
            self.refresh()
            return

        # Any in-flight recent request is now stale.
        self._request_token += 1
        self._recent_mode = False
        self._recent_loading = False
        self._update_show_more()

        self._last_site_name = site.get("name") or site.get("base_url", "this site")
        self._search_loading = True
        self.search_btn.setEnabled(False)
        self.status_lbl.setText(f"Searching '{query}' on {site['name']}...")

        worker = StreamSearchWorker(self.db, site, query)
        self.search_worker = worker
        self._search_workers.append(worker)
        worker.results.connect(self._on_results)
        worker.poster_ready.connect(self._on_poster_ready)
        worker.error.connect(self._on_search_error)
        worker.finished.connect(lambda w=worker: self._on_search_finished(w))
        worker.start()

    def load_recent(self, reset: bool = True) -> None:
        """Load the selected site's newest shows (page 1 or the next page)."""
        if self._is_loading_recent():
            return
        site_id = self.site_combo.currentData()
        if site_id is None:
            ToastNotification.show_toast(self.window(), "Add a streaming site in Settings first.")
            return
        site = self.db.get_streaming_site_by_id(site_id)
        if not site:
            ToastNotification.show_toast(self.window(), "That streaming site no longer exists.")
            self.refresh()
            return

        if reset:
            self._request_token += 1
            self._recent_mode = True
            self._recent_page = 0
            self._recent_exhausted = False
            self._results = []
            self._visible_count = 0
            self._clear_grid()
            self._show_empty(
                "Loading Latest Shows",
                f"Fetching the newest shows from {site['name']}…",
            )
        page = 1 if reset else self._recent_page + 1

        self._recent_loading = True
        self._recent_site_id = site_id
        self._last_site_name = site.get("name") or site.get("base_url", "this site")
        self.search_btn.setEnabled(False)
        self.recent_btn.setEnabled(False)
        if not reset:
            self.status_lbl.setText(
                f"Loading more shows from {site['name']}…"
            )
        self._update_show_more()

        token = self._request_token
        worker = StreamRecentWorker(self.db, site, page=page, limit=RECENT_BATCH)
        self.recent_worker = worker
        self._recent_workers.append(worker)
        worker.results.connect(
            lambda items, loaded_page, t=token: self._on_recent_results(
                items, loaded_page, t
            )
        )
        worker.poster_ready.connect(self._on_poster_ready)
        worker.error.connect(
            lambda message, t=token: self._on_recent_error(message, t)
        )
        worker.finished.connect(lambda w=worker: self._on_recent_finished(w))
        worker.start()

    def _on_recent_results(self, items: list, page: int, token: int) -> None:
        if token != self._request_token:
            return
        self._recent_loading = False
        self._recent_mode = True
        # The fetch is done; posters keep downloading in the background.
        has_sites = self.site_combo.count() > 0
        self.search_btn.setEnabled(has_sites and not self._is_searching())
        self.recent_btn.setEnabled(has_sites)
        page = max(1, int(page or 1))
        site_name = getattr(self, "_last_site_name", "this site")

        if page <= 1:
            self._results = list(items or [])
            self._recent_page = 1
            self._recent_exhausted = not self._results
            self._visible_count = min(RECENT_INITIAL, len(self._results))
        else:
            known = {
                (item.get("source_type"), item.get("source_id"))
                for item in self._results
            }
            fresh = [
                item
                for item in (items or [])
                if (item.get("source_type"), item.get("source_id")) not in known
            ]
            if not fresh:
                # The site repeated the same page; stop asking for more.
                self._recent_exhausted = True
            else:
                previous_count = len(self._results)
                self._results.extend(fresh)
                self._recent_page = page
                self._visible_count = min(
                    len(self._results), previous_count + SHOW_MORE_STEP
                )

        if not self._results:
            self.status_lbl.setText("No recent shows found.")
            self._clear_grid()
            self._show_empty(
                "No Recent Shows",
                f"{site_name} did not return a recent list. Search for a "
                "title instead — some sites hide their catalogue behind "
                "JavaScript or block automated requests.",
            )
            self._update_show_more()
            return

        self.status_lbl.setText(
            f"Latest shows on {site_name} — showing "
            f"{self._visible_count} of {len(self._results)}"
        )
        self._render_results()

    def _on_recent_error(self, message: str, token: int) -> None:
        if token != self._request_token:
            return
        self._recent_loading = False
        site_name = getattr(self, "_last_site_name", "this site")
        self.status_lbl.setText(f"Could not load latest shows: {message}")
        if not self._results:
            self._show_empty(
                "Latest Shows Unavailable",
                f"Nook could not read the newest shows from {site_name}. "
                "Search for a title instead, or try again later.",
            )
        self._update_show_more()

    def _on_recent_finished(self, worker: Optional[StreamRecentWorker] = None) -> None:
        if worker in self._recent_workers:
            self._recent_workers.remove(worker)
        if worker is not None and worker is not self.recent_worker:
            # A newer request already replaced this one; ignore its finish.
            return
        self._recent_loading = False
        has_sites = self.site_combo.count() > 0
        self.search_btn.setEnabled(has_sites and not self._is_searching())
        self.recent_btn.setEnabled(has_sites)
        self._update_show_more()
        # If the user picked another site while this request was running, load
        # the new site's list now that the old worker has finished.
        current = self.site_combo.currentData()
        if current is not None and current != self._recent_site_id:
            self.load_recent(reset=True)

    def _show_more(self) -> None:
        if not self._recent_mode or self._is_loading_recent():
            return
        if self._visible_count < len(self._results):
            self._visible_count = min(
                len(self._results), self._visible_count + SHOW_MORE_STEP
            )
            site_name = getattr(self, "_last_site_name", "this site")
            self.status_lbl.setText(
                f"Latest shows on {site_name} — showing "
                f"{self._visible_count} of {len(self._results)}"
            )
            self._render_results()
            return
        if self._recent_exhausted:
            self._update_show_more()
            return
        self.load_recent(reset=False)

    def _update_show_more(self) -> None:
        visible = (
            self._recent_mode
            and bool(self._results)
            and (
                self._visible_count < len(self._results)
                or not self._recent_exhausted
            )
        )
        self.show_more_row.setVisible(visible)
        if not visible:
            return
        remaining = len(self._results) - self._visible_count
        if remaining > 0:
            self.show_more_btn.setText(
                f"Show More (+{min(SHOW_MORE_STEP, remaining)})"
            )
        else:
            self.show_more_btn.setText("Show More")
        self.show_more_btn.setEnabled(not self._recent_loading)

    def _on_results(self, results: list) -> None:
        self._search_loading = False
        self._recent_mode = False
        self._recent_loading = False
        self._recent_exhausted = True
        # The fetch is done; posters keep downloading in the background.
        has_sites = self.site_combo.count() > 0
        self.search_btn.setEnabled(has_sites)
        self.recent_btn.setEnabled(has_sites)
        self._results = results or []
        self._visible_count = len(self._results)
        if not self._results:
            self.status_lbl.setText("No results found.")
            self._clear_grid()
            site_name = getattr(self, "_last_site_name", "this site")
            self._show_empty(
                "No Results",
                f"Nothing matched that search on {site_name}. Try a different "
                "title, or check that the site opens in your browser — some "
                "sites require JavaScript or block automated requests.",
            )
            self._update_show_more()
            return
        self.status_lbl.setText(f"{len(self._results)} result(s)")
        self._render_results()

    def _on_search_error(self, message: str) -> None:
        self._search_loading = False
        self._recent_mode = False
        self.status_lbl.setText(f"Search failed: {message}")
        self._clear_grid()
        self._show_empty("Search Failed", message)
        self._update_show_more()

    def _on_search_finished(self, worker: Optional[StreamSearchWorker] = None) -> None:
        if worker in self._search_workers:
            self._search_workers.remove(worker)
        if worker is not None and worker is not self.search_worker:
            return
        self._search_loading = False
        has_sites = self.site_combo.count() > 0
        self.search_btn.setEnabled(has_sites and not self._search_loading)
        self.recent_btn.setEnabled(has_sites and not self._recent_loading)
        self._update_show_more()

    @staticmethod
    def _result_key(result: Dict[str, Any]) -> Any:
        source_type = result.get("source_type") or ""
        source_id = result.get("source_id") or ""
        if source_type or source_id:
            return (source_type, source_id)
        return result.get("url") or id(result)

    def _on_poster_ready(self, item: dict) -> None:
        """Apply one piece of artwork as soon as its download finishes."""
        data = (item or {}).get("poster_bytes")
        if not data:
            return
        key = self._result_key(item)
        # Keep the buffered result in sync so the card has artwork if it is
        # revealed later by Show More.
        for result in self._results:
            if self._result_key(result) == key:
                result["poster_bytes"] = data
                break
        card = self._cards.get(key)
        if card is not None:
            card.set_poster_bytes(data)

    def _render_results(self) -> None:
        self._clear_grid()
        if not self._results:
            self._update_show_more()
            return
        if not self._recent_mode:
            self._visible_count = len(self._results)
        site_name = self.site_combo.currentText()
        self.empty_widget.setVisible(False)
        self.scroll_area.setVisible(True)
        self.show_more_row.setVisible(False)

        for result in self._results[: self._visible_count]:
            card = StreamResultCard(result, site_name=site_name, parent=self.grid_container)
            card.add_requested.connect(self._add_result)
            card.open_requested.connect(self._open_result)
            already = self.db.get_series_by_source(
                result.get("source_type", ""), result.get("source_id", "")
            )
            card.set_added(bool(already))
            self.grid_layout.addWidget(card)
            card.show()
            self._cards[self._result_key(result)] = card

        self.grid_container.adjustSize()
        self._update_show_more()

    def _clear_grid(self) -> None:
        self._cards = {}
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item:
                widget = item.widget()
                if widget:
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()

    def _show_empty(self, title: str, subtitle: str) -> None:
        self.empty_title.setText(title)
        self.empty_subtitle.setText(subtitle)
        self.scroll_area.setVisible(False)
        self.show_more_row.setVisible(False)
        self.empty_widget.setVisible(True)

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------
    def _add_result(self, result: Dict[str, Any]) -> None:
        if self.import_worker and self.import_worker.isRunning():
            ToastNotification.show_toast(self.window(), "An import is already in progress.")
            return
        site_id = self.site_combo.currentData()
        site = self.db.get_streaming_site_by_id(site_id) if site_id is not None else None
        if not site:
            ToastNotification.show_toast(self.window(), "Add a streaming site in Settings first.")
            return

        self.status_lbl.setText(f"Adding '{result.get('title', 'show')}' to your library...")
        self.import_worker = StreamImportWorker(self.db, site, result)
        self.import_worker.imported.connect(self._on_imported)
        self.import_worker.error.connect(self._on_import_error)
        self.import_worker.start()

    def _on_imported(self, series_id: int, matched_title: str = "") -> None:
        if matched_title:
            self.status_lbl.setText(f"Added '{matched_title}' to your library.")
            ToastNotification.show_toast(self.window(), f"Added to library: {matched_title}")
        else:
            self.status_lbl.setText("Added to your library.")
            ToastNotification.show_toast(self.window(), "Show added to your library.")
        self.series_added.emit(series_id)
        self._render_results()  # refresh "In Library" badges

    def _on_import_error(self, message: str) -> None:
        self.status_lbl.setText(f"Import failed: {message}")
        ToastNotification.show_toast(self.window(), f"Import failed: {message}", duration_ms=4000)

    def _open_result(self, result: Dict[str, Any]) -> None:
        """Open a search result on its streaming site without adding it."""
        url = (result or {}).get("url") or ""
        if not url:
            ToastNotification.show_toast(self.window(), "This result has no page to open.")
            return
        open_url(url)
        ToastNotification.show_toast(self.window(), "Opening show page in your browser.")
