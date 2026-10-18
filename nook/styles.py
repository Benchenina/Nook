"""Cozy UI Themes and QSS Stylesheets for Nook.

Provides live dynamic theme switching between Cozy Dark and Cozy Light modes.
Inspired by modern streaming platforms with warm, welcoming aesthetics.
"""

from __future__ import annotations

from typing import Dict


class CozyTheme:
    """Color palette and styles generator for Nook."""

    DARK_PALETTE = {
        "name": "dark",
        "bg_base": "#1A1614",
        "bg_surface": "#231D1A",
        "bg_card": "#2B2421",
        "bg_card_hover": "#362E2A",
        "bg_elevated": "#3E3530",
        "bg_input": "#221C19",
        "border": "#3F3530",
        "border_light": "#4F443D",
        "text_primary": "#F7EFE2",
        "text_secondary": "#BFAFA1",
        "text_muted": "#847569",
        "accent": "#E5A93C",
        "accent_hover": "#F2B84D",
        "accent_text": "#1A1614",
        "accent_secondary": "#8A9A86",
        "accent_terracotta": "#C86D51",
        "accent_danger": "#D95D5D",
        "badge_bg": "#362B22",
        "badge_text": "#E5A93C",
        "progress_bg": "#362E2A",
        "progress_fill": "#E5A93C",
        "shadow_color": "rgba(0, 0, 0, 0.4)",
    }

    LIGHT_PALETTE = {
        "name": "light",
        "bg_base": "#FAF6F0",
        "bg_surface": "#F2EBE1",
        "bg_card": "#FFFFFF",
        "bg_card_hover": "#FBF8F3",
        "bg_elevated": "#EDE4D7",
        "bg_input": "#FFFFFF",
        "border": "#E2D7CA",
        "border_light": "#D4C7B8",
        "text_primary": "#2B231F",
        "text_secondary": "#6A5C54",
        "text_muted": "#96877E",
        "accent": "#C86D51",
        "accent_hover": "#D97B5E",
        "accent_text": "#FFFFFF",
        "accent_secondary": "#6C8568",
        "accent_terracotta": "#C86D51",
        "accent_danger": "#C44B4B",
        "badge_bg": "#F5E6DF",
        "badge_text": "#B85D43",
        "progress_bg": "#E5DCD1",
        "progress_fill": "#C86D51",
        "shadow_color": "rgba(43, 35, 31, 0.08)",
    }

    @classmethod
    def get_palette(cls, theme_name: str = "dark") -> Dict[str, str]:
        if theme_name.lower() == "light":
            return cls.LIGHT_PALETTE
        return cls.DARK_PALETTE

    @classmethod
    def get_stylesheet(cls, theme_name: str = "dark") -> str:
        p = cls.get_palette(theme_name)

        return f"""
        /* Global Reset & Base Typography */
        QWidget {{
            font-family: "Segoe UI", "Ubuntu", "Inter", "Noto Sans", -apple-system, sans-serif;
            color: {p["text_primary"]};
            font-size: 14px;
            outline: none;
        }}

        QMainWindow, QDialog {{
            background-color: {p["bg_base"]};
        }}

        /* Scrollbars */
        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {p["border_light"]};
            border-radius: 5px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {p["accent"]};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
        }}

        QScrollBar:horizontal {{
            background: transparent;
            height: 10px;
            margin: 0px;
        }}
        QScrollBar::handle:horizontal {{
            background: {p["border_light"]};
            border-radius: 5px;
            min-width: 30px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {p["accent"]};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: transparent;
        }}

        /* Text Inputs & Search */
        QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox {{
            background-color: {p["bg_input"]};
            border: 1px solid {p["border"]};
            border-radius: 12px;
            padding: 8px 14px;
            color: {p["text_primary"]};
            selection-background-color: {p["accent"]};
            selection-color: {p["accent_text"]};
        }}
        QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {{
            border: 1.5px solid {p["accent"]};
        }}
        QLineEdit:disabled, QTextEdit:disabled {{
            background-color: {p["bg_surface"]};
            color: {p["text_muted"]};
        }}

        /* Buttons */
        QPushButton {{
            background-color: {p["bg_card"]};
            border: 1px solid {p["border"]};
            border-radius: 12px;
            padding: 8px 18px;
            font-weight: 600;
            color: {p["text_primary"]};
        }}
        QPushButton:hover {{
            background-color: {p["bg_card_hover"]};
            border-color: {p["accent"]};
        }}
        QPushButton:pressed {{
            background-color: {p["bg_elevated"]};
        }}
        QPushButton:disabled {{
            background-color: {p["bg_surface"]};
            color: {p["text_muted"]};
            border-color: {p["border"]};
        }}

        /* Accent Primary Button */
        QPushButton#primaryBtn, QPushButton[primary="true"] {{
            background-color: {p["accent"]};
            color: {p["accent_text"]};
            border: none;
            border-radius: 12px;
            font-weight: 700;
            padding: 9px 20px;
        }}
        QPushButton#primaryBtn:hover, QPushButton[primary="true"]:hover {{
            background-color: {p["accent_hover"]};
        }}

        /* Secondary Accent Button */
        QPushButton#secondaryBtn {{
            background-color: {p["bg_elevated"]};
            border: 1px solid {p["border_light"]};
            color: {p["text_primary"]};
            border-radius: 12px;
        }}
        QPushButton#secondaryBtn:hover {{
            border-color: {p["accent"]};
        }}

        /* Danger Button */
        QPushButton#dangerBtn {{
            background-color: transparent;
            border: 1px solid {p["accent_danger"]};
            color: {p["accent_danger"]};
            border-radius: 12px;
        }}
        QPushButton#dangerBtn:hover {{
            background-color: {p["accent_danger"]};
            color: #FFFFFF;
        }}

        /* Icon Buttons */
        QPushButton#iconBtn {{
            background-color: transparent;
            border: none;
            border-radius: 10px;
            padding: 6px;
        }}
        QPushButton#iconBtn:hover {{
            background-color: {p["bg_elevated"]};
        }}

        /* Top Bar Navigation Tabs */
        QPushButton#navTab {{
            background-color: transparent;
            border: none;
            border-radius: 12px;
            padding: 8px 16px;
            font-size: 15px;
            font-weight: 600;
            color: {p["text_secondary"]};
        }}
        QPushButton#navTab:hover {{
            color: {p["text_primary"]};
            background-color: {p["bg_surface"]};
        }}
        QPushButton#navTab[active="true"] {{
            color: {p["accent"]};
            background-color: {p["bg_elevated"]};
            font-weight: 700;
        }}

        /* Combo Box */
        QComboBox {{
            background-color: {p["bg_input"]};
            border: 1px solid {p["border"]};
            border-radius: 12px;
            padding: 6px 14px;
            color: {p["text_primary"]};
            min-height: 24px;
        }}
        QComboBox:hover {{
            border-color: {p["accent"]};
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 28px;
            border-left: none;
        }}
        QComboBox QAbstractItemView {{
            background-color: {p["bg_surface"]};
            border: 1px solid {p["border"]};
            border-radius: 10px;
            padding: 4px;
            selection-background-color: {p["accent"]};
            selection-color: {p["accent_text"]};
            outline: none;
        }}

        /* Progress Bar */
        QProgressBar {{
            background-color: {p["progress_bg"]};
            border: none;
            border-radius: 4px;
            height: 6px;
            text-align: center;
        }}
        QProgressBar::chunk {{
            background-color: {p["progress_fill"]};
            border-radius: 4px;
        }}

        /* Checkboxes & Radio Buttons */
        QCheckBox, QRadioButton {{
            spacing: 8px;
            color: {p["text_primary"]};
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 5px;
            border: 1px solid {p["border_light"]};
            background-color: {p["bg_input"]};
        }}
        QCheckBox::indicator:hover {{
            border-color: {p["accent"]};
        }}
        QCheckBox::indicator:checked {{
            background-color: {p["accent"]};
            border-color: {p["accent"]};
            image: none;
        }}
        QRadioButton::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 9px;
            border: 1px solid {p["border_light"]};
            background-color: {p["bg_input"]};
        }}
        QRadioButton::indicator:checked {{
            background-color: {p["accent"]};
            border-color: {p["accent"]};
        }}

        /* Context Menus */
        QMenu {{
            background-color: {p["bg_surface"]};
            border: 1px solid {p["border"]};
            border-radius: 12px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 8px 24px 8px 12px;
            border-radius: 8px;
            color: {p["text_primary"]};
        }}
        QMenu::item:selected {{
            background-color: {p["bg_elevated"]};
            color: {p["accent"]};
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {p["border"]};
            margin: 4px 8px;
        }}

        /* Tooltips */
        QToolTip {{
            background-color: {p["bg_elevated"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
            border-radius: 8px;
            padding: 6px 10px;
            font-size: 12px;
        }}

        /* Lists & Tables */
        QListWidget, QTableWidget {{
            background-color: {p["bg_card"]};
            border: 1px solid {p["border"]};
            border-radius: 12px;
            padding: 6px;
        }}
        QListWidget::item, QTableWidget::item {{
            border-radius: 8px;
            padding: 8px;
        }}
        QListWidget::item:hover, QTableWidget::item:hover {{
            background-color: {p["bg_card_hover"]};
        }}
        QListWidget::item:selected, QTableWidget::item:selected {{
            background-color: {p["bg_elevated"]};
            color: {p["accent"]};
        }}

        /* Custom Card Widgets */
        #seriesCard {{
            background-color: {p["bg_card"]};
            border: 1px solid {p["border"]};
            border-radius: 14px;
        }}
        #seriesCard:hover {{
            background-color: {p["bg_card_hover"]};
            border-color: {p["accent"]};
        }}

        #topBar {{
            background-color: {p["bg_surface"]};
            border-bottom: 1px solid {p["border"]};
        }}

        #carouselContainer {{
            background-color: {p["bg_surface"]};
            border: 1px solid {p["border"]};
            border-radius: 16px;
        }}

        #tagPill {{
            background-color: {p["bg_elevated"]};
            color: {p["text_secondary"]};
            border: 1px solid {p["border"]};
            border-radius: 12px;
            padding: 4px 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        #tagPill:hover {{
            color: {p["text_primary"]};
            border-color: {p["accent"]};
        }}
        #tagPill[active="true"] {{
            background-color: {p["badge_bg"]};
            color: {p["badge_text"]};
            border-color: {p["badge_text"]};
        }}

        #episodeRow {{
            background-color: {p["bg_card"]};
            border: 1px solid {p["border"]};
            border-radius: 12px;
            padding: 10px 14px;
        }}
        #episodeRow:hover {{
            background-color: {p["bg_card_hover"]};
            border-color: {p["border_light"]};
        }}
        """
