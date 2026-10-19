"""Cozy UI Themes and QSS Stylesheets for Nook.

Provides live dynamic theme switching between dark (black) and light modes.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Accent colour presets
# ---------------------------------------------------------------------------
# Each preset is anchored on a vivid "dark theme" colour. The light-theme
# colour, hover shade, readable text colour and badge tint are derived from it
# so a single hex value per preset is enough to keep the whole palette
# coherent. ``amber`` mirrors the original Nook look and pins both themes.

ACCENT_PRESETS: "OrderedDict[str, Dict[str, str]]" = OrderedDict(
    (
        ("amber", {"label": "Amber", "dark": "#E5A93C", "light": "#C86D51"}),
        ("orange", {"label": "Orange", "dark": "#F08A3C"}),
        ("coral", {"label": "Coral", "dark": "#F2685A"}),
        ("rose", {"label": "Rose", "dark": "#E4577B"}),
        ("pink", {"label": "Pink", "dark": "#F06CA8"}),
        ("magenta", {"label": "Magenta", "dark": "#D65CD6"}),
        ("violet", {"label": "Violet", "dark": "#9B6BF2"}),
        ("indigo", {"label": "Indigo", "dark": "#6C78F0"}),
        ("blue", {"label": "Blue", "dark": "#4C8DF6"}),
        ("sky", {"label": "Sky", "dark": "#3FB6F0"}),
        ("cyan", {"label": "Cyan", "dark": "#2FC4D6"}),
        ("teal", {"label": "Teal", "dark": "#2FB8A6"}),
        ("green", {"label": "Green", "dark": "#4CBB63"}),
        ("lime", {"label": "Lime", "dark": "#9BC53D"}),
        ("red", {"label": "Red", "dark": "#E05A5A"}),
        ("slate", {"label": "Slate", "dark": "#94A3B8"}),
    )
)

DEFAULT_ACCENT = "amber"


def _hex_to_rgb(value: str) -> Tuple[int, int, int]:
    raw = (value or "").lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        raw = "E5A93C"
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _rgb_to_hex(rgb: Tuple[float, float, float]) -> str:
    parts = [max(0, min(255, int(round(channel)))) for channel in rgb]
    return "#{:02X}{:02X}{:02X}".format(*parts)


def _mix(color_a: str, color_b: str, weight_b: float) -> str:
    """Blend ``color_a`` towards ``color_b`` (0 keeps A, 1 returns B)."""
    a = _hex_to_rgb(color_a)
    b = _hex_to_rgb(color_b)
    weight_b = max(0.0, min(1.0, weight_b))
    return _rgb_to_hex(
        tuple(a[i] * (1 - weight_b) + b[i] * weight_b for i in range(3))
    )


def _luminance(value: str) -> float:
    r, g, b = _hex_to_rgb(value)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _readable_text_on(value: str) -> str:
    return "#0A0A0A" if _luminance(value) > 0.55 else "#FFFFFF"


def normalize_accent_name(name: Optional[str]) -> str:
    """Map a user-supplied accent name onto a known preset key."""
    key = (name or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    for candidate in ACCENT_PRESETS:
        if candidate.replace(" ", "") == key:
            return candidate
    return DEFAULT_ACCENT


def accent_names() -> List[str]:
    """Return the available accent preset keys, in display order."""
    return list(ACCENT_PRESETS.keys())


def accent_label(name: str) -> str:
    preset = ACCENT_PRESETS.get(normalize_accent_name(name), {})
    return preset.get("label", "Amber")


def accent_palette(name: str, theme_name: str = "dark") -> Dict[str, str]:
    """Build the accent-related palette keys for one preset + theme."""
    preset = ACCENT_PRESETS[normalize_accent_name(name)]
    is_light = theme_name.lower() == "light"
    if is_light:
        base = preset.get("light") or _mix(preset["dark"], "#000000", 0.12)
    else:
        base = preset["dark"]

    if is_light:
        badge_bg = _mix(base, "#FFFFFF", 0.86)
        badge_text = _mix(base, "#000000", 0.14)
    else:
        badge_bg = _mix(base, "#000000", 0.85)
        badge_text = base

    return {
        "accent": base,
        "accent_hover": _mix(base, "#FFFFFF", 0.10),
        "accent_text": _readable_text_on(base),
        "badge_bg": badge_bg,
        "badge_text": badge_text,
        "progress_fill": base,
    }


# ---------------------------------------------------------------------------
# Active palette helpers so widgets can use theme colours from code too
# ---------------------------------------------------------------------------
_ACTIVE_PALETTE: Dict[str, str] = {}
_ACTIVE_ACCENT: str = DEFAULT_ACCENT


def _resolve_accent(accent_name: Optional[str]) -> str:
    if accent_name:
        return normalize_accent_name(accent_name)
    return _ACTIVE_ACCENT or DEFAULT_ACCENT


def set_active_theme(theme_name: str, accent_name: Optional[str] = None) -> None:
    global _ACTIVE_PALETTE, _ACTIVE_ACCENT
    if accent_name:
        _ACTIVE_ACCENT = normalize_accent_name(accent_name)
    _ACTIVE_PALETTE = dict(CozyTheme.get_palette(theme_name, _ACTIVE_ACCENT))


def active_accent() -> str:
    """Return the currently active accent preset key."""
    return _ACTIVE_ACCENT or DEFAULT_ACCENT


def active_palette() -> Dict[str, str]:
    if not _ACTIVE_PALETTE:
        set_active_theme("dark", DEFAULT_ACCENT)
    return _ACTIVE_PALETTE


def color(key: str, default: str = "#FFFFFF") -> str:
    """Return a palette colour for the active theme."""
    return active_palette().get(key, default)


def color_rgba(key: str, alpha: float) -> str:
    """Return a palette colour converted to a QSS ``rgba(...)`` string."""
    hex_value = color(key).lstrip("#")
    if len(hex_value) != 6:
        return color(key)
    r = int(hex_value[0:2], 16)
    g = int(hex_value[2:4], 16)
    b = int(hex_value[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def get_qpalette(theme_name: str = "dark", accent_name: Optional[str] = None):
    """Build a QPalette matching the theme.

    Widgets that are not covered by the stylesheet (scroll area viewports,
    plain container widgets, native popups) read their background from the
    application palette, so it has to follow the active theme too.
    """
    from PyQt6.QtGui import QColor, QPalette

    p = CozyTheme.get_palette(theme_name, accent_name)
    qp = QPalette()
    roles = {
        QPalette.ColorRole.Window: p["bg_base"],
        QPalette.ColorRole.WindowText: p["text_primary"],
        QPalette.ColorRole.Base: p["bg_base"],
        QPalette.ColorRole.AlternateBase: p["bg_card"],
        QPalette.ColorRole.Text: p["text_primary"],
        QPalette.ColorRole.Button: p["bg_card"],
        QPalette.ColorRole.ButtonText: p["text_primary"],
        QPalette.ColorRole.ToolTipBase: p["bg_elevated"],
        QPalette.ColorRole.ToolTipText: p["text_primary"],
        QPalette.ColorRole.Highlight: p["accent"],
        QPalette.ColorRole.HighlightedText: p["accent_text"],
        QPalette.ColorRole.PlaceholderText: p["text_muted"],
        QPalette.ColorRole.Link: p["accent"],
    }
    for role, value in roles.items():
        qp.setColor(role, QColor(value))
    return qp


class CozyTheme:
    """Color palette and styles generator for Nook."""

    DARK_PALETTE = {
        "name": "dark",
        "bg_base": "#000000",
        "bg_surface": "#0B0B0B",
        "bg_card": "#121212",
        "bg_card_hover": "#1B1B1B",
        "bg_elevated": "#212121",
        "bg_input": "#141414",
        "border": "#1E1E1E",
        "border_light": "#2B2B2B",
        "text_primary": "#F2F2F2",
        "text_secondary": "#A6A6A6",
        "text_muted": "#6B6B6B",
        "accent": "#E5A93C",
        "accent_hover": "#F2B84D",
        "accent_text": "#0A0A0A",
        "accent_secondary": "#8A9A86",
        "accent_terracotta": "#C86D51",
        "accent_danger": "#E05A5A",
        "badge_bg": "#241A0C",
        "badge_text": "#E5A93C",
        "progress_bg": "#232323",
        "progress_fill": "#E5A93C",
        "shadow_color": "rgba(0, 0, 0, 0.65)",
    }

    LIGHT_PALETTE = {
        "name": "light",
        "bg_base": "#F4F4F6",
        "bg_surface": "#FFFFFF",
        "bg_card": "#FFFFFF",
        "bg_card_hover": "#EFEFF2",
        "bg_elevated": "#E7E7EB",
        "bg_input": "#FFFFFF",
        "border": "#E4E4E8",
        "border_light": "#D4D4DA",
        "text_primary": "#17171A",
        "text_secondary": "#5C5C63",
        "text_muted": "#8E8E96",
        "accent": "#C86D51",
        "accent_hover": "#D97B5E",
        "accent_text": "#FFFFFF",
        "accent_secondary": "#6C8568",
        "accent_terracotta": "#C86D51",
        "accent_danger": "#C44B4B",
        "badge_bg": "#F7E7E0",
        "badge_text": "#B85D43",
        "progress_bg": "#E3E3E8",
        "progress_fill": "#C86D51",
        "shadow_color": "rgba(20, 20, 25, 0.10)",
    }

    @classmethod
    def get_palette(cls, theme_name: str = "dark",
                    accent_name: Optional[str] = None) -> Dict[str, str]:
        palette = dict(
            cls.LIGHT_PALETTE if theme_name.lower() == "light" else cls.DARK_PALETTE
        )
        accent = _resolve_accent(accent_name)
        palette.update(accent_palette(accent, theme_name))
        return palette

    @classmethod
    def get_stylesheet(cls, theme_name: str = "dark",
                       accent_name: Optional[str] = None) -> str:
        p = cls.get_palette(theme_name, accent_name)
        set_active_theme(theme_name, accent_name)
        return cls._build_stylesheet(p)

    @classmethod
    def _build_stylesheet(cls, p: Dict[str, str]) -> str:
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

        /* Pin every page/surface to the theme background. Widgets created
           before the theme is applied can otherwise keep the default light
           palette, leaving grey areas behind the content. */
        QMainWindow > QWidget, QDialog > QWidget,
        QStackedWidget > QWidget, QScrollArea > QWidget {{
            background-color: {p["bg_base"]};
        }}

        QStackedWidget, QScrollArea, QAbstractScrollArea {{
            border: none;
        }}

        /* Frameless content layers inside scroll areas paint the base colour. */
        QScrollArea > QWidget > QWidget {{
            background-color: {p["bg_base"]};
        }}

        /* Scrollbars */
        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {p["border_light"]};
            border-radius: 4px;
            min-height: 36px;
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
            margin: 2px;
        }}
        QScrollBar::handle:horizontal {{
            background: {p["border_light"]};
            border-radius: 4px;
            min-width: 36px;
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
            border: 1px solid transparent;
            border-radius: 14px;
            padding: 8px 14px;
            color: {p["text_primary"]};
            selection-background-color: {p["accent"]};
            selection-color: {p["accent_text"]};
        }}
        QLineEdit:hover, QTextEdit:hover, QSpinBox:hover {{
            background-color: {p["bg_elevated"]};
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{
            background-color: {p["bg_elevated"]};
            border: 1px solid {p["accent"]};
        }}
        QLineEdit:disabled, QTextEdit:disabled {{
            background-color: {p["bg_surface"]};
            color: {p["text_muted"]};
        }}

        /* Buttons */
        QPushButton {{
            background-color: {p["bg_card"]};
            border: none;
            border-radius: 14px;
            padding: 9px 18px;
            font-weight: 600;
            color: {p["text_primary"]};
        }}
        QPushButton:hover {{
            background-color: {p["bg_card_hover"]};
        }}
        QPushButton:pressed {{
            background-color: {p["bg_elevated"]};
        }}
        QPushButton:disabled {{
            background-color: {p["bg_surface"]};
            color: {p["text_muted"]};
        }}

        /* Accent Primary Button */
        QPushButton#primaryBtn, QPushButton[primary="true"] {{
            background-color: {p["accent"]};
            color: {p["accent_text"]};
            border: none;
            border-radius: 14px;
            font-weight: 700;
            padding: 10px 20px;
        }}
        QPushButton#primaryBtn:hover, QPushButton[primary="true"]:hover {{
            background-color: {p["accent_hover"]};
        }}
        QPushButton#primaryBtn:pressed, QPushButton[primary="true"]:pressed {{
            background-color: {p["accent"]};
        }}

        /* Secondary Accent Button */
        QPushButton#secondaryBtn {{
            background-color: {p["bg_elevated"]};
            border: none;
            color: {p["text_primary"]};
            border-radius: 14px;
        }}
        QPushButton#secondaryBtn:hover {{
            background-color: {p["bg_card_hover"]};
            color: {p["accent"]};
        }}

        /* Danger Button */
        QPushButton#dangerBtn {{
            background-color: {p["bg_card"]};
            border: none;
            color: {p["accent_danger"]};
            border-radius: 14px;
        }}
        QPushButton#dangerBtn:hover {{
            background-color: {p["accent_danger"]};
            color: #FFFFFF;
        }}

        /* Icon Buttons */
        QPushButton#iconBtn {{
            background-color: transparent;
            border: none;
            border-radius: 12px;
            padding: 6px;
        }}
        QPushButton#iconBtn:hover {{
            background-color: {p["bg_elevated"]};
        }}

        /* Tiny remove-from-history button on Continue Watching cards */
        QPushButton#removeHistoryBtn {{
            background-color: transparent;
            border: none;
            border-radius: 50%;
            padding: 2px;
        }}
        QPushButton#removeHistoryBtn:hover {{
            background-color: {p["accent_danger"]};
        }}

        /* Top Bar Navigation Tabs */
        QPushButton#navTab {{
            background-color: transparent;
            border: none;
            border-radius: 14px;
            padding: 9px 18px;
            font-size: 15px;
            font-weight: 600;
            color: {p["text_secondary"]};
        }}
        QPushButton#navTab:hover {{
            color: {p["text_primary"]};
            background-color: {p["bg_card"]};
        }}
        QPushButton#navTab[active="true"] {{
            color: {p["accent_text"]};
            background-color: {p["accent"]};
            font-weight: 700;
        }}

        /* Combo Box */
        QComboBox {{
            background-color: {p["bg_input"]};
            border: 1px solid transparent;
            border-radius: 14px;
            padding: 7px 14px;
            color: {p["text_primary"]};
            min-height: 24px;
        }}
        QComboBox:hover {{
            background-color: {p["bg_elevated"]};
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 30px;
            border: none;
        }}
        QComboBox QAbstractItemView {{
            background-color: {p["bg_surface"]};
            border: none;
            border-radius: 14px;
            padding: 6px;
            selection-background-color: {p["bg_elevated"]};
            selection-color: {p["accent"]};
            outline: none;
        }}

        /* Progress Bar */
        QProgressBar {{
            background-color: {p["progress_bg"]};
            border: none;
            border-radius: 999px;
            text-align: center;
        }}
        QProgressBar::chunk {{
            background-color: {p["progress_fill"]};
            border-radius: 999px;
        }}

        /* Checkboxes & Radio Buttons */
        QCheckBox, QRadioButton {{
            spacing: 9px;
            color: {p["text_primary"]};
            padding: 2px 0px;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 6px;
            border: none;
            background-color: {p["bg_elevated"]};
        }}
        QCheckBox::indicator:hover {{
            background-color: {p["border_light"]};
        }}
        QCheckBox::indicator:checked {{
            background-color: {p["accent"]};
        }}
        QRadioButton::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 9px;
            border: none;
            background-color: {p["bg_elevated"]};
        }}
        QRadioButton::indicator:hover {{
            background-color: {p["border_light"]};
        }}
        QRadioButton::indicator:checked {{
            background-color: {p["accent"]};
            border: 5px solid {p["bg_base"]};
        }}

        /* Context Menus */
        QMenu {{
            background-color: {p["bg_surface"]};
            border: none;
            border-radius: 16px;
            padding: 8px;
        }}
        QMenu::item {{
            padding: 9px 22px 9px 12px;
            border-radius: 10px;
            color: {p["text_primary"]};
        }}
        QMenu::item:selected {{
            background-color: {p["bg_elevated"]};
            color: {p["accent"]};
        }}
        QMenu::icon {{
            padding-left: 10px;
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {p["bg_elevated"]};
            margin: 6px 10px;
        }}

        /* Tooltips */
        QToolTip {{
            background-color: {p["bg_elevated"]};
            color: {p["text_primary"]};
            border: none;
            border-radius: 10px;
            padding: 6px 10px;
            font-size: 12px;
        }}

        /* Lists & Tables */
        QListWidget, QTableWidget {{
            background-color: {p["bg_card"]};
            border: none;
            border-radius: 16px;
            padding: 6px;
        }}
        QListWidget::item, QTableWidget::item {{
            border-radius: 10px;
            padding: 8px;
        }}
        QListWidget::item:hover, QTableWidget::item:hover {{
            background-color: {p["bg_card_hover"]};
        }}
        QListWidget::item:selected, QTableWidget::item:selected {{
            background-color: {p["bg_elevated"]};
            color: {p["accent"]};
        }}
        QHeaderView::section {{
            background-color: transparent;
            border: none;
            padding: 8px 6px;
            color: {p["text_muted"]};
            font-weight: 600;
        }}
        QTableCornerButton::section {{
            background: transparent;
            border: none;
        }}

        /* Group Boxes (frameless) */
        QGroupBox {{
            border: none;
            margin-top: 10px;
            padding-top: 8px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 0px;
            padding: 0 0 6px 0;
            color: {p["text_secondary"]};
            font-weight: 600;
        }}

        /* Custom Card Widgets */
        #seriesCard {{
            background-color: {p["bg_card"]};
            border: none;
            border-radius: 20px;
        }}
        #seriesCard:hover {{
            background-color: {p["bg_card_hover"]};
        }}

        #topBar {{
            background-color: {p["bg_base"]};
            border: none;
        }}

        #carouselContainer {{
            background-color: {p["bg_surface"]};
            border: none;
            border-radius: 22px;
        }}

        #tagPill {{
            background-color: {p["bg_card"]};
            color: {p["text_secondary"]};
            border: none;
            border-radius: 14px;
            padding: 6px 14px;
            font-size: 12px;
            font-weight: 600;
        }}
        #tagPill:hover {{
            background-color: {p["bg_card_hover"]};
            color: {p["text_primary"]};
        }}
        #tagPill[active="true"] {{
            background-color: {p["accent"]};
            color: {p["accent_text"]};
            font-weight: 700;
        }}

        #episodeRow {{
            background-color: {p["bg_card"]};
            border: none;
            border-radius: 16px;
        }}
        #episodeRow:hover {{
            background-color: {p["bg_card_hover"]};
        }}

        /* Season section header */
        #seasonHeader {{
            background-color: {p["bg_surface"]};
            border: none;
            border-radius: 16px;
        }}
        #seasonHeader:hover {{
            background-color: {p["bg_card_hover"]};
        }}
        QLabel#seasonStats {{
            color: {p["text_muted"]};
            font-size: 12px;
            font-weight: 600;
        }}

        /* Card section titles used inside settings / detail views */
        #sectionTitle {{
            font-size: 16px;
            font-weight: 700;
            color: {p["text_primary"]};
        }}
        #mutedText {{
            color: {p["text_muted"]};
            font-size: 12px;
        }}
        """
