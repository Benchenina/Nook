"""Online Metadata Scraper Dialog for fetching descriptions and artwork."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nook.database import Database
from nook.scraper import OnlineMetadataScraper
from nook.ui.widgets.poster_widget import PosterWidget


class ScraperWorker(QThread):
    results_ready = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, scraper: OnlineMetadataScraper, query: str, provider: str):
        super().__init__()
        self.scraper = scraper
        self.query = query
        self.provider = provider

    def run(self) -> None:
        try:
            results = self.scraper.search_metadata(self.query, self.provider)
            self.results_ready.emit(results)
        except Exception as e:
            self.error_occurred.emit(str(e))


class ScraperResultCard(QFrame):
    """Card widget representing an online search result."""

    apply_requested = pyqtSignal(dict)

    def __init__(self, result_data: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.result_data = result_data
        self.setObjectName("episodeRow")

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 14, 10)
        layout.setSpacing(14)

        # 1. Poster thumbnail
        self.poster = PosterWidget(
            image_path=None,
            title=self.result_data.get("title", ""),
            corner_radius=8,
            fixed_size=QSize(60, 90),
            parent=self
        )
        layout.addWidget(self.poster)

        # 2. Text Details
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_lbl = QLabel(self.result_data.get("title", "Untitled"), self)
        t_font = QFont(self.font())
        t_font.setPointSize(13)
        t_font.setBold(True)
        title_lbl.setFont(t_font)
        title_row.addWidget(title_lbl)

        year = self.result_data.get("year")
        if year:
            year_lbl = QLabel(f"({year})", self)
            year_lbl.setStyleSheet("color: #847569; font-size: 12px;")
            title_row.addWidget(year_lbl)

        provider = self.result_data.get("provider", "TV")
        prov_lbl = QLabel(provider, self)
        prov_lbl.setStyleSheet("""
            color: #E5A93C;
            background-color: rgba(229, 169, 60, 0.12);
            border-radius: 6px;
            padding: 2px 6px;
            font-size: 10px;
            font-weight: 600;
        """)
        title_row.addWidget(prov_lbl)
        title_row.addStretch()

        text_layout.addLayout(title_row)

        # Tags
        tags = self.result_data.get("tags") or []
        if tags:
            tag_lbl = QLabel(" • ".join(tags[:4]), self)
            tag_lbl.setStyleSheet("color: #847569; font-size: 11px;")
            text_layout.addWidget(tag_lbl)

        # Description excerpt
        desc = self.result_data.get("description", "")
        if desc:
            desc_lbl = QLabel(desc[:160] + ("..." if len(desc) > 160 else ""), self)
            desc_lbl.setStyleSheet("color: #BFAFA1; font-size: 11px;")
            desc_lbl.setWordWrap(True)
            text_layout.addWidget(desc_lbl)

        layout.addLayout(text_layout)

        # 3. Apply Button
        apply_btn = QPushButton("Apply to Series", self)
        apply_btn.setObjectName("primaryBtn")
        apply_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        apply_btn.clicked.connect(lambda: self.apply_requested.emit(self.result_data))
        layout.addWidget(apply_btn)


class ScraperDialog(QDialog):
    """Dialog for searching and importing metadata from online providers."""

    metadata_applied = pyqtSignal(int)  # series_id

    def __init__(self, series_id: int, db: Database, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.series_id = series_id
        self.db = db
        self.series_data = self.db.get_series_by_id(series_id) or {}
        self.scraper = OnlineMetadataScraper(db)

        self.setWindowTitle(f"Fetch Online Metadata — {self.series_data.get('display_title', '')}")
        self.setMinimumSize(680, 520)
        self.setModal(True)

        self.worker: Optional[ScraperWorker] = None

        self._init_ui()
        # Automatically trigger initial search
        self._start_search()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # Header
        header = QLabel("🌐 Fetch Online Metadata", self)
        h_font = QFont(self.font())
        h_font.setPointSize(16)
        h_font.setBold(True)
        header.setFont(h_font)
        main_layout.addWidget(header)

        # Search bar & Provider selector
        search_row = QHBoxLayout()
        search_row.setSpacing(10)

        self.search_input = QLineEdit(self)
        self.search_input.setText(self.series_data.get("display_title", ""))
        self.search_input.setPlaceholderText("Search title...")
        self.search_input.returnPressed.connect(self._start_search)
        search_row.addWidget(self.search_input, stretch=3)

        self.provider_combo = QComboBox(self)
        self.provider_combo.addItem("TVMaze (Shows/General)", "tvmaze")
        self.provider_combo.addItem("AniList (Anime)", "anilist")
        self.provider_combo.addItem("TheMovieDB (TMDB)", "tmdb")

        # Set saved preferred provider
        pref = self.db.get_setting("preferred_scraper", "tvmaze")
        idx = self.provider_combo.findData(pref)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        search_row.addWidget(self.provider_combo, stretch=1)

        self.search_btn = QPushButton("Search", self)
        self.search_btn.setObjectName("primaryBtn")
        self.search_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.search_btn.clicked.connect(self._start_search)
        search_row.addWidget(self.search_btn)

        main_layout.addLayout(search_row)

        # Progress / Status
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("", self)
        self.status_label.setStyleSheet("color: #847569; font-size: 12px;")
        main_layout.addWidget(self.status_label)

        # Results Scroll Area
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(10)
        self.results_layout.addStretch()

        self.scroll_area.setWidget(self.results_container)
        main_layout.addWidget(self.scroll_area)

        # Close button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        main_layout.addLayout(btn_row)

    def _start_search(self) -> None:
        query = self.search_input.text().strip()
        if not query:
            return

        provider = self.provider_combo.currentData()
        self.progress_bar.setVisible(True)
        self.search_btn.setEnabled(False)
        self.status_label.setText(f"Searching {self.provider_combo.currentText()} for '{query}'...")

        # Clear existing results
        while self.results_layout.count() > 1:
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.worker = ScraperWorker(self.scraper, query, provider)
        self.worker.results_ready.connect(self._on_results_ready)
        self.worker.error_occurred.connect(self._on_search_error)
        self.worker.start()

    def _on_results_ready(self, results: List[Dict[str, Any]]) -> None:
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)

        if not results:
            self.status_label.setText("No results found. Try a different search title or provider.")
            return

        self.status_label.setText(f"Found {len(results)} matches:")
        for r in results:
            card = ScraperResultCard(r, self.results_container)
            card.apply_requested.connect(self._apply_metadata)
            self.results_layout.insertWidget(self.results_layout.count() - 1, card)

    def _on_search_error(self, err_msg: str) -> None:
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        self.status_label.setText(f"Error fetching metadata: {err_msg}")

    def _apply_metadata(self, result: Dict[str, Any]) -> None:
        self.status_label.setText("Downloading cover and applying metadata...")
        poster_url = result.get("poster_url")
        saved_cover = None

        if poster_url:
            saved_cover = self.scraper.download_poster(
                poster_url,
                series_name=result.get("title", "series")
            )

        title = result.get("title")
        year = result.get("year")
        if year and year not in (title or ""):
            final_title = f"{title} ({year})"
        else:
            final_title = title or self.series_data.get("display_title")

        desc = result.get("description") or self.series_data.get("description", "")
        tags = result.get("tags") or self.series_data.get("tags_list") or []

        self.db.update_series_customization(
            series_id=self.series_id,
            display_title=final_title,
            custom_cover_path=saved_cover if saved_cover else None,
            tags=tags,
            description=desc
        )

        self.metadata_applied.emit(self.series_id)
        self.accept()
