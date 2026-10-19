"""Series Customization Modal Dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from nook.database import Database
from nook.styles import color
from nook.ui.icons import icon, pixmap
from nook.ui.widgets.poster_widget import PosterWidget


class CustomizationModal(QDialog):
    """Modal dialog for customizing a series (virtual title, cover, tags, visibility, favorite)."""

    customization_saved = pyqtSignal(int)  # series_id

    def __init__(self, series_id: int, db: Database, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.series_id = series_id
        self.db = db
        self.series_data = self.db.get_series_by_id(series_id) or {}

        self.setWindowTitle(f"Customize — {self.series_data.get('display_title', 'Series')}")
        self.setMinimumSize(560, 620)
        self.setModal(True)

        self._pending_cover_path: Optional[str] = self.series_data.get("custom_cover_path")

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        # Header Title
        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_icon = QLabel(self)
        header_icon.setPixmap(pixmap("sparkles", size=20))
        header_row.addWidget(header_icon)

        header = QLabel("Series Customization", self)
        font = QFont(self.font())
        font.setPointSize(16)
        font.setBold(True)
        header.setFont(font)
        header_row.addWidget(header)
        header_row.addStretch()
        main_layout.addLayout(header_row)

        sub = QLabel("Customize metadata, virtual title, and poster artwork safely without touching files on disk.", self)
        sub.setStyleSheet(f"color: {color('text_muted')}; font-size: 12px;")
        sub.setWordWrap(True)
        main_layout.addWidget(sub)

        # Top section: Poster Preview & Cover controls
        cover_section = QHBoxLayout()
        cover_section.setSpacing(18)

        active_cover = self._pending_cover_path or self.series_data.get("detected_cover_path")
        self.poster_preview = PosterWidget(
            image_path=active_cover,
            title=self.series_data.get("display_title", ""),
            corner_radius=10,
            fixed_size=QSize(110, 160),
            parent=self
        )
        cover_section.addWidget(self.poster_preview)

        cover_btns_layout = QVBoxLayout()
        cover_btns_layout.setSpacing(10)
        cover_btns_layout.addStretch()

        cover_label = QLabel("Poster Artwork:", self)
        cover_label.setStyleSheet("font-weight: 600;")
        cover_btns_layout.addWidget(cover_label)

        self.btn_select_cover = QPushButton("Choose Custom Image...", self)
        self.btn_select_cover.setIcon(icon("image", size=15))
        self.btn_select_cover.setIconSize(QSize(15, 15))
        self.btn_select_cover.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_select_cover.clicked.connect(self._choose_cover_file)
        cover_btns_layout.addWidget(self.btn_select_cover)

        self.btn_reset_cover = QPushButton("Reset to Original Cover", self)
        self.btn_reset_cover.setObjectName("secondaryBtn")
        self.btn_reset_cover.setIcon(icon("refresh", size=15))
        self.btn_reset_cover.setIconSize(QSize(15, 15))
        self.btn_reset_cover.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_reset_cover.clicked.connect(self._reset_cover)
        cover_btns_layout.addWidget(self.btn_reset_cover)

        cover_btns_layout.addStretch()
        cover_section.addLayout(cover_btns_layout)
        cover_section.addStretch()

        main_layout.addLayout(cover_section)

        # Form fields
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 1. Virtual Display Title
        self.title_input = QLineEdit(self)
        self.title_input.setText(self.series_data.get("display_title", ""))
        self.title_input.setPlaceholderText("Virtual display title...")
        form_layout.addRow("Display Title:", self.title_input)

        # 2. Custom Tags (comma-separated)
        tags_list = self.series_data.get("tags_list") or []
        self.tags_input = QLineEdit(self)
        self.tags_input.setText(", ".join(tags_list))
        self.tags_input.setPlaceholderText("Action, Sci-Fi, Anime, Comedy (comma-separated)")
        form_layout.addRow("Tags / Genres:", self.tags_input)

        # 3. Synopsis / Description
        self.desc_input = QTextEdit(self)
        self.desc_input.setPlainText(self.series_data.get("description", ""))
        self.desc_input.setPlaceholderText("Plot summary or notes...")
        self.desc_input.setFixedHeight(80)
        form_layout.addRow("Description:", self.desc_input)

        main_layout.addLayout(form_layout)

        # 4. Checkbox toggles
        chk_layout = QHBoxLayout()
        chk_layout.setSpacing(20)

        self.fav_chk = QCheckBox("Mark as Favorite", self)
        self.fav_chk.setIcon(icon("heart", size=14, color="#FF5B6E"))
        self.fav_chk.setIconSize(QSize(14, 14))
        self.fav_chk.setChecked(bool(self.series_data.get("is_favorite", 0)))
        chk_layout.addWidget(self.fav_chk)

        self.hide_chk = QCheckBox("Hide from Library", self)
        self.hide_chk.setIcon(icon("eye-off", size=14))
        self.hide_chk.setIconSize(QSize(14, 14))
        self.hide_chk.setChecked(bool(self.series_data.get("is_hidden", 0)))
        chk_layout.addWidget(self.hide_chk)

        chk_layout.addStretch()
        main_layout.addLayout(chk_layout)

        main_layout.addStretch()

        # Bottom Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save Changes", self)
        self.save_btn.setObjectName("primaryBtn")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save_changes)
        btn_layout.addWidget(self.save_btn)

        main_layout.addLayout(btn_layout)

    def _choose_cover_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Poster Artwork",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if file_path:
            # Copy into managed storage
            saved_cover = self.db.save_cover_image(
                file_path,
                prefix=f"series_{self.series_id}"
            )
            self._pending_cover_path = saved_cover
            self.poster_preview.set_image(saved_cover, title=self.title_input.text())

    def _reset_cover(self) -> None:
        self._pending_cover_path = ""
        detected = self.series_data.get("detected_cover_path", "")
        self.poster_preview.set_image(detected, title=self.title_input.text())

    def _save_changes(self) -> None:
        title = self.title_input.text().strip() or self.series_data.get("folder_name", "Untitled")
        raw_tags = self.tags_input.text().strip()
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        desc = self.desc_input.toPlainText().strip()
        is_fav = self.fav_chk.isChecked()
        is_hidden = self.hide_chk.isChecked()

        self.db.update_series_customization(
            series_id=self.series_id,
            display_title=title,
            custom_cover_path=self._pending_cover_path,
            tags=tags,
            is_favorite=is_fav,
            is_hidden=is_hidden,
            description=desc
        )

        self.customization_saved.emit(self.series_id)
        self.accept()
