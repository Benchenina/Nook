"""Nook UI package."""

from nook.ui.customization_modal import CustomizationModal
from nook.ui.library_view import LibraryView
from nook.ui.main_window import MainWindow
from nook.ui.recently_watched import RecentlyWatchedCarousel
from nook.ui.scraper_dialog import ScraperDialog
from nook.ui.series_card import SeriesCard
from nook.ui.series_detail import SeriesDetailView
from nook.ui.settings_view import SettingsView

__all__ = [
    "MainWindow",
    "LibraryView",
    "SeriesDetailView",
    "SettingsView",
    "SeriesCard",
    "RecentlyWatchedCarousel",
    "CustomizationModal",
    "ScraperDialog",
]
