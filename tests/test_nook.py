"""Unit and Integration Tests for Nook."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Use offscreen platform for Qt GUI tests
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

from nook.database import Database
from nook.player import MediaPlayer
from nook.scanner import FilenameCleaner, LibraryScanner, LocalMetadataReader
from nook.scraper import OnlineMetadataScraper
from nook.styles import CozyTheme
from nook.ui.customization_modal import CustomizationModal
from nook.ui.library_view import LibraryView
from nook.ui.main_window import MainWindow
from nook.ui.series_detail import SeriesDetailView
from nook.ui.settings_view import SettingsView


class TestNookDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_nook.db"
        self.db = Database(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_settings(self):
        self.assertEqual(self.db.get_setting("theme"), "dark")
        self.db.set_setting("theme", "light")
        self.assertEqual(self.db.get_setting("theme"), "light")
        self.assertEqual(self.db.get_setting("non_existent", "default_val"), "default_val")

    def test_root_directories(self):
        r_id = self.db.add_root_directory("/dummy/path")
        self.assertIsNotNone(r_id)
        roots = self.db.get_root_directories()
        self.assertEqual(len(roots), 1)
        self.assertTrue("/dummy/path" in roots[0]["path"])

        # Test duplicate root add returns existing id
        dup_id = self.db.add_root_directory("/dummy/path")
        self.assertEqual(dup_id, r_id)

        self.db.remove_root_directory(r_id)
        self.assertEqual(len(self.db.get_root_directories()), 0)

    def test_series_and_episodes_crud(self):
        root_id = self.db.add_root_directory("/media/tv")
        series_id = self.db.upsert_series(
            root_id=root_id,
            folder_path="/media/tv/Cowboy Bebop",
            folder_name="Cowboy Bebop",
            display_title="Cowboy Bebop",
            description="Space western anime.",
            tags=["Anime", "Sci-Fi"]
        )
        self.assertIsNotNone(series_id)

        # Check retrieval
        series = self.db.get_series_by_id(series_id)
        self.assertIsNotNone(series)
        self.assertEqual(series["display_title"], "Cowboy Bebop")
        self.assertIn("Anime", series["tags_list"])

        # Insert episodes
        ep1_id = self.db.upsert_episode(
            series_id=series_id,
            file_path="/media/tv/Cowboy Bebop/01.Asteroid.Blues.mkv",
            file_name="01.Asteroid.Blues.mkv",
            clean_title="Episode 01 - Asteroid Blues",
            season_number=1,
            episode_number=1,
            file_size=500000000,
            duration_seconds=1450
        )
        ep2_id = self.db.upsert_episode(
            series_id=series_id,
            file_path="/media/tv/Cowboy Bebop/02.Stray.Dog.Strut.mkv",
            file_name="02.Stray.Dog.Strut.mkv",
            clean_title="Episode 02 - Stray Dog Strut",
            season_number=1,
            episode_number=2,
            file_size=510000000,
            duration_seconds=1450
        )

        episodes = self.db.get_episodes_for_series(series_id)
        self.assertEqual(len(episodes), 2)

        # Test watch tracking & progress
        self.db.update_episode_progress(ep1_id, playback_position=600, duration_seconds=1450, increment_play_count=True)
        ep1 = self.db.get_episode_by_id(ep1_id)
        self.assertEqual(ep1["playback_position"], 600)
        self.assertEqual(ep1["play_count"], 1)
        self.assertIsNotNone(ep1["last_watched_at"])

        # Check recently watched list
        recents = self.db.get_recently_watched_episodes()
        self.assertEqual(len(recents), 1)
        self.assertEqual(recents[0]["id"], ep1_id)
        self.assertEqual(recents[0]["series_title"], "Cowboy Bebop")

        # Test marking watched
        self.db.toggle_episode_watched(ep2_id, True)
        ep2 = self.db.get_episode_by_id(ep2_id)
        self.assertEqual(ep2["watched"], 1)

        # Test customization updates (virtual rename, tags, favorite, hidden)
        self.db.update_series_customization(
            series_id=series_id,
            display_title="Cowboy Bebop Remastered",
            is_favorite=True,
            is_hidden=True
        )
        updated = self.db.get_series_by_id(series_id)
        self.assertEqual(updated["display_title"], "Cowboy Bebop Remastered")
        self.assertEqual(updated["is_favorite"], 1)
        self.assertEqual(updated["is_hidden"], 1)


class TestFilenameCleaner(unittest.TestCase):
    def test_clean_titles(self):
        cases = [
            ("Spider.Man.2002.1080p.BluRay.x264.mkv", "Spider Man 2002"),
            ("Stranger.Things.S01E02.Chapter.Two.720p.mkv", "S01E02 - Chapter Two"),
            ("[SubsPlease] Sousou no Frieren - 05 (1080p) [ABCD1234].mkv", "Episode 05"),
            ("Attack.on.Titan.S03E12.Night.of.the.Battle.1080p.mkv", "S03E12 - Night of the Battle"),
        ]
        for raw, expected_substr in cases:
            cleaned = FilenameCleaner.clean_title(raw, is_episode=True)
            self.assertTrue(
                expected_substr.lower() in cleaned.lower(),
                f"Expected '{expected_substr}' in '{cleaned}' for '{raw}'"
            )

    def test_season_episode_extraction(self):
        self.assertEqual(FilenameCleaner.extract_season_episode("Show.S02E08.mkv")[:2], (2, 8))
        self.assertEqual(FilenameCleaner.extract_season_episode("Show.2x04.avi")[:2], (2, 4))
        self.assertEqual(FilenameCleaner.extract_season_episode("Show - 14.mp4")[:2], (0, 14))


class TestMediaPlayer(unittest.TestCase):
    def test_format_timestamp(self):
        self.assertEqual(MediaPlayer.format_timestamp(0), "00:00")
        self.assertEqual(MediaPlayer.format_timestamp(65), "01:05")
        self.assertEqual(MediaPlayer.format_timestamp(3665), "01:01:05")


class TestThemes(unittest.TestCase):
    def test_stylesheets_generate(self):
        dark_qss = CozyTheme.get_stylesheet("dark")
        light_qss = CozyTheme.get_stylesheet("light")
        self.assertIn("#1A1614", dark_qss)
        self.assertIn("#FAF6F0", light_qss)
        self.assertIn("QScrollBar", dark_qss)
        self.assertIn("QPushButton", light_qss)


class TestGUIWidgets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_gui_nook.db"
        self.db = Database(self.db_path)
        self.player = MediaPlayer(self.db)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_main_window_instantiation(self):
        window = MainWindow(self.db)
        self.assertIsNotNone(window)
        # Test tab switching
        window.switch_tab(0)
        self.assertEqual(window.stack.currentIndex(), 0)
        window.switch_tab(1)
        self.assertEqual(window.stack.currentIndex(), 1)
        window.switch_tab(2)
        self.assertEqual(window.stack.currentIndex(), 2)

        # Test search query input
        window.search_bar.setText("Test")
        self.assertEqual(window.library_view.search_query, "Test")

        # Test theme toggle
        curr_theme = self.db.get_setting("theme")
        window._toggle_theme()
        new_theme = self.db.get_setting("theme")
        self.assertNotEqual(curr_theme, new_theme)

    def test_series_detail_view(self):
        # Create a series in db
        r_id = self.db.add_root_directory("/tmp/test_root")
        s_id = self.db.upsert_series(r_id, "/tmp/test_root/SeriesA", "SeriesA", "Series A Title")
        self.db.upsert_episode(s_id, "/tmp/test_root/SeriesA/ep1.mkv", "ep1.mkv", "Episode 1", 1, 1)

        detail = SeriesDetailView(self.db, self.player)
        detail.load_series(s_id)
        self.assertEqual(detail.title_lbl.text(), "Series A Title")
        self.assertEqual(len(detail.episodes), 1)

        # Test mode toggling
        detail._set_view_mode("grid")
        self.assertEqual(detail.view_mode, "grid")
        detail._set_view_mode("list")
        self.assertEqual(detail.view_mode, "list")

    def test_customization_modal(self):
        r_id = self.db.add_root_directory("/tmp/test_root")
        s_id = self.db.upsert_series(r_id, "/tmp/test_root/SeriesB", "SeriesB", "Original Name")

        modal = CustomizationModal(s_id, self.db)
        modal.title_input.setText("Custom Virtual Name")
        modal.tags_input.setText("Anime, Action")
        modal._save_changes()

        series = self.db.get_series_by_id(s_id)
        self.assertEqual(series["display_title"], "Custom Virtual Name")
        self.assertIn("Action", series["tags_list"])


if __name__ == "__main__":
    unittest.main()
