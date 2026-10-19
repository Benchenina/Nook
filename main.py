#!/usr/bin/env python3
"""Nook - Cross-Platform Cozy Local Video Library Manager.

Inspired by Steam and modern streaming platforms, infused with a cozy,
welcoming aesthetic.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to sys.path so 'nook' can be imported cleanly
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

from nook import __app_name__, __version__
from nook.database import Database
from nook.scanner import LibraryScanner
from nook.scraper import auto_match_new_series
from nook.ui.main_window import MainWindow


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nook",
        description="Nook: Cozy Local Video Library Manager"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__app_name__} v{__version__}"
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Run library scanner in headless mode then exit"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    db = Database()

    # Headless CLI scanning option
    if args.scan:
        print(f"[{__app_name__}] Running library scanner...")
        scanner = LibraryScanner(db)
        s_count, e_count = scanner.scan_all()
        print(f"[{__app_name__}] Scan complete: {s_count} series, {e_count} episodes indexed.")
        matched = auto_match_new_series(
            db,
            scanner.new_series,
            on_progress=lambda index, total, msg: print(f"[{__app_name__}] {msg}"),
        )
        if matched:
            print(f"[{__app_name__}] Auto-applied online metadata to {matched} new folder(s).")
        sys.exit(0)

    # Initialize PyQt6 GUI Application
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName("Nook")
    app.setOrganizationName("NookApp")

    # Set cross-platform clean default font
    font = QFont()
    font.setFamilies(["Segoe UI", "Ubuntu", "Inter", "Noto Sans", "sans-serif"])
    font.setPointSize(10)
    app.setFont(font)

    # Set application icon (supports running from source or frozen AppImage)
    base_dir = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    app_icon = QIcon()
    for icon_name in ("icon.png", "icon.ico"):
        candidate = base_dir / icon_name
        if candidate.exists():
            app_icon = QIcon(str(candidate))
            app.setWindowIcon(app_icon)
            break

    # Launch Main Window
    window = MainWindow(db=db)
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
