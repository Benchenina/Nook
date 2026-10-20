"""Unit and Integration Tests for Nook."""

import gzip
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Use offscreen platform for Qt GUI tests
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication, QMessageBox

from nook.database import Database
from nook.player import MediaPlayer
from nook.scanner import FilenameCleaner, LibraryScanner, LocalMetadataReader
from nook.scraper import (
    OnlineMetadataScraper,
    auto_match_new_series,
    find_best_match,
    match_score,
    normalize_title,
    strip_year,
)
from nook.streaming import (
    MIRURO_XOR_KEY,
    AnimeIDHentaiProvider,
    ElisworldProvider,
    FlixbabaProvider,
    GenericStreamingProvider,
    HanimeProvider,
    HentaiHavenProvider,
    HiAnimeProvider,
    MManiProvider,
    MiruroProvider,
    MiruruProvider,
    OneTubeProvider,
    StreamEpisode,
    StreamResult,
    is_stream_url,
    normalize_site_url,
    provider_for_site,
    site_display_name,
    site_slug,
)
from nook.styles import (
    DEFAULT_ACCENT,
    CozyTheme,
    accent_names,
    accent_palette,
    active_accent,
    color,
    color_rgba,
    get_qpalette,
    normalize_accent_name,
    set_active_theme,
)
from nook.ui.browse_view import BrowseView, StreamResultCard
from nook.ui.customization_modal import CustomizationModal
from nook.ui.library_view import LibraryView
from nook.ui.main_window import MainWindow
from nook.ui.series_detail import SeriesDetailView
from nook.ui.settings_view import ScanWorker, SettingsView
from nook.ui.widgets.poster_widget import PosterWidget


def _make_png_bytes(color: str = "#3366CC", size: int = 8) -> bytes:
    """Create a tiny, valid PNG in memory to stand in for a remote poster."""
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from PyQt6.QtGui import QColor, QImage

    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


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

    def test_remove_episode_from_history(self):
        root_id = self.db.add_root_directory("/media/tv")
        series_id = self.db.upsert_series(
            root_id, "/media/tv/Show", "Show", "Show"
        )
        ep_id = self.db.upsert_episode(
            series_id, "/media/tv/Show/e1.mkv", "e1.mkv", "Episode 1", 1, 1
        )
        self.db.update_episode_progress(
            ep_id, playback_position=120, duration_seconds=1200, increment_play_count=True
        )
        self.assertEqual(len(self.db.get_recently_watched_episodes()), 1)

        self.db.remove_episode_from_history(ep_id)

        self.assertEqual(self.db.get_recently_watched_episodes(), [])
        # Only the history entry is dropped - watch progress is kept.
        ep = self.db.get_episode_by_id(ep_id)
        self.assertEqual(ep["playback_position"], 120)
        self.assertIsNone(ep["last_watched_at"])

    def test_streaming_sites_crud(self):
        self.assertEqual(self.db.get_streaming_sites(), [])
        self.assertIsNone(self.db.add_streaming_site("not a url"))

        site_id = self.db.add_streaming_site("https://hianime.to")
        self.assertIsNotNone(site_id)

        sites = self.db.get_streaming_sites()
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["name"], "HiAnime")
        self.assertEqual(sites[0]["base_url"], "https://hianime.to")
        self.assertEqual(sites[0]["source_type"], "hianime")

        # A differently-written URL for the same host updates, not duplicates.
        self.assertEqual(self.db.add_streaming_site("hianime.to/"), site_id)
        self.assertEqual(len(self.db.get_streaming_sites()), 1)

        self.assertEqual(self.db.get_streaming_site_by_id(site_id)["name"], "HiAnime")

        # Display names can be customised without touching the slug/URL.
        self.db.rename_streaming_site(site_id, "My Anime Site")
        renamed = self.db.get_streaming_site_by_id(site_id)
        self.assertEqual(renamed["name"], "My Anime Site")
        self.assertEqual(renamed["source_type"], "hianime")
        self.assertEqual(renamed["base_url"], "https://hianime.to")
        # An empty name is ignored.
        self.db.rename_streaming_site(site_id, "   ")
        self.assertEqual(
            self.db.get_streaming_site_by_id(site_id)["name"], "My Anime Site"
        )

        self.db.remove_streaming_site(site_id)
        self.assertEqual(self.db.get_streaming_sites(), [])

    def test_stream_import_marks_multi_season_shows(self):
        series_id = self.db.add_streaming_series(
            "1tube",
            "1148",
            "Show",
            episodes=[
                {
                    "title": "S1E1",
                    "url": "https://1tube.org/watch/1148/1/1",
                    "number": 1,
                    "season_number": 1,
                    "season_name": "Season 1",
                },
                {
                    "title": "S2E1",
                    "url": "https://1tube.org/watch/1148/2/1",
                    "number": 1,
                    "season_number": 2,
                    "season_name": "Season 2",
                },
            ],
        )
        self.assertTrue(self.db.get_series_by_id(series_id)["has_seasons"])

    def test_multi_source_duplicate_titles_coexist(self):
        r_id = self.db.add_root_directory("/media/lib")
        local_id = self.db.upsert_series(r_id, "/media/lib/Naruto", "Naruto", "Naruto")
        hianime_id = self.db.add_streaming_series(
            "hianime",
            "naruto-1",
            "Naruto",
            source_url="https://hianime.to/watch/naruto-1",
            tags=["HiAnime"],
            episodes=[
                {"title": "Episode 1", "url": "https://cdn.example/e1.m3u8", "number": 1},
                {"title": "Episode 2", "url": "https://cdn.example/e2.m3u8", "number": 2},
            ],
        )
        miruru_id = self.db.add_streaming_series(
            "miruru",
            "naruto-1",
            "Naruto",
            source_url="https://miruru.tv/anime/naruto-1",
            episodes=[],
        )

        # Three independent rows sharing the same title.
        self.assertEqual(len({local_id, hianime_id, miruru_id}), 3)
        titles = [s["display_title"] for s in self.db.get_all_series()]
        self.assertEqual(titles.count("Naruto"), 3)

        # Re-importing the same (source_type, source_id) is idempotent.
        again = self.db.add_streaming_series(
            "hianime",
            "naruto-1",
            "Naruto",
            source_url="https://hianime.to/watch/naruto-1",
            episodes=[],
        )
        self.assertEqual(again, hianime_id)
        self.assertEqual(len(self.db.get_all_series()), 3)

        # Stream episodes keep their network URL verbatim (not path-resolved).
        eps = self.db.get_episodes_for_series(hianime_id)
        self.assertEqual(eps[0]["file_path"], "https://cdn.example/e1.m3u8")
        self.assertEqual(self.db.get_series_by_source("hianime", "naruto-1")["id"], hianime_id)
        self.assertIsNone(self.db.get_series_by_source("hianime", "missing"))

        # Streaming series are not tied to a root directory and use a synthetic path.
        stream_series = self.db.get_series_by_id(hianime_id)
        self.assertIsNone(stream_series["root_id"])
        self.assertEqual(stream_series["folder_path"], "hianime://naruto-1")
        self.assertEqual(stream_series["source_url"], "https://hianime.to/watch/naruto-1")
        self.assertIn("HiAnime", stream_series["tags_list"])

    def test_delete_series_cascades_episodes(self):
        s_id = self.db.add_streaming_series(
            "hianime",
            "d1",
            "Delete Me",
            source_url="https://hianime.to/watch/d1",
            episodes=[
                {"title": "Episode 1", "url": "https://cdn/e1.m3u8", "number": 1},
                {"title": "Episode 2", "url": "https://cdn/e2.m3u8", "number": 2},
            ],
        )
        self.assertEqual(len(self.db.get_episodes_for_series(s_id)), 2)

        self.db.delete_series(s_id)

        self.assertIsNone(self.db.get_series_by_id(s_id))
        self.assertEqual(self.db.get_episodes_for_series(s_id), [])
        self.assertIsNone(self.db.get_series_by_source("hianime", "d1"))


class TestStreamingProviders(unittest.TestCase):
    SEARCH_HTML = """
    <html><body>
      <div class="film">
        <a href="/watch/naruto-1234" title="Naruto">
          <img data-src="/img/naruto.jpg" alt="Naruto Shippuden">
        </a>
        <a href="/watch/bleach-9"><img src="https://cdn.example/bleach.png"></a>
        <a href="/watch/naruto-1234"><img src="/img/dupe.jpg"></a>
        <a href="/watch/naruto-1234?ep=5">Episode 5</a>
        <a href="/genres/action">Action</a>
      </div>
    </body></html>
    """

    def test_url_helpers(self):
        self.assertEqual(site_slug("https://www.hianime.to/"), "hianime")
        self.assertEqual(site_slug("miruru.tv"), "miruru")
        self.assertEqual(site_slug("Miruru"), "miruru")
        self.assertEqual(site_slug(""), "stream")

        self.assertEqual(normalize_site_url("hianime.to"), "https://hianime.to")
        self.assertEqual(normalize_site_url("https://hianime.to/watch/x"), "https://hianime.to")
        self.assertEqual(normalize_site_url("https://hianime.to/"), "https://hianime.to")
        self.assertEqual(normalize_site_url(""), "")
        self.assertEqual(normalize_site_url("not a url"), "")

        self.assertEqual(site_display_name("", "hianime"), "HiAnime")
        self.assertEqual(site_display_name("", "weirdsite"), "Weirdsite")

        self.assertTrue(is_stream_url("https://cdn/x/e1.m3u8"))
        self.assertTrue(is_stream_url("http://cdn/x/e1.mp4"))
        self.assertFalse(is_stream_url("/media/lib/e1.mkv"))
        self.assertFalse(is_stream_url(""))
        self.assertFalse(is_stream_url(None))

    def test_provider_selection(self):
        self.assertIsInstance(
            provider_for_site({"base_url": "https://hianime.to"}), HiAnimeProvider
        )
        self.assertIsInstance(
            provider_for_site({"base_url": "https://miruru.tv"}), MiruruProvider
        )
        self.assertIsInstance(
            provider_for_site({"base_url": "https://mmani.com"}), MManiProvider
        )
        self.assertIsInstance(
            provider_for_site({"base_url": "https://www.miruro.tv"}), MiruroProvider
        )
        self.assertIsInstance(
            provider_for_site({"base_url": "https://www.1tube.org"}), OneTubeProvider
        )
        self.assertIsInstance(
            provider_for_site({"base_url": "https://animeidhentai.com"}),
            AnimeIDHentaiProvider,
        )
        self.assertIsInstance(
            provider_for_site({"base_url": "https://flixbaba.org.uk"}),
            FlixbabaProvider,
        )
        self.assertIsInstance(
            provider_for_site({"base_url": "https://elisworld.tv"}),
            ElisworldProvider,
        )
        self.assertIsInstance(
            provider_for_site({"base_url": "https://random.example"}), GenericStreamingProvider
        )

    def test_generic_search_tries_alternate_paths(self):
        """Sites that use a non-standard query parameter still get searched."""
        provider = provider_for_site(
            {"base_url": "https://example.com", "source_type": "example"}
        )
        html = '<a href="/watch/thing-1">Thing</a>'

        def fake_get_text(url):
            return html if "wd=" in url else ""

        with mock.patch.object(provider, "_get_text", side_effect=fake_get_text):
            results = provider.search("thing")

        self.assertEqual([r.source_id for r in results], ["thing-1"])

    def test_mmani_json_search_mapping(self):
        provider = MManiProvider("https://mmani.com", slug="mmani")
        payload = {
            "status": "success",
            "data": [
                {
                    "postid": 411646,
                    "postname": "ONE PIECE HEROINES",
                    "postyear": "2026",
                    "ani_cover_large": "https://s4.anilist.co/file/x.jpg",
                },
                {
                    "postid": 408966,
                    "postname": "Futari Solo Camp",
                    "postyear": "2025",
                    "ani_cover_large": "/covers/solo.jpg",
                },
            ],
        }
        root = '<script>const AppConfig = {"search":"https://api.example/search3.php"}</script>'

        with mock.patch.object(provider, "_get_text", return_value=root), \
             mock.patch.object(provider, "_get_json", return_value=payload) as get_json:
            results = provider.search("one piece")

        self.assertEqual([r.source_id for r in results], ["411646", "408966"])
        self.assertEqual(results[0].title, "ONE PIECE HEROINES")
        self.assertEqual(results[0].url, "https://mmani.com/up/411646")
        self.assertEqual(results[0].poster_url, "https://s4.anilist.co/file/x.jpg")
        self.assertEqual(results[0].year, "2026")
        self.assertEqual(
            results[1].poster_url, "https://rez1.ims1.top/350x/covers/solo.jpg"
        )
        # The endpoint advertised by the page is used, not the fallback.
        self.assertEqual(get_json.call_args[0][0], "https://api.example/search3.php")

    def test_mmani_episode_mapping_and_hls_resolution(self):
        provider = MManiProvider("https://mmani.com", slug="mmani")
        result = StreamResult(
            source_type="mmani",
            source_id="408371",
            title="Show",
            url="https://mmani.com/up/408371",
        )

        def fake_json(url, params=None, headers=None):
            if url == provider.SINGLE_API_FALLBACK:
                return {"status": "success", "data": {"anilist": "143598"}}
            if url == provider.EPISODES_API:
                return [
                    {
                        "id": 10,
                        "server_data": [
                            {"name": "01", "slug": "01", "link": "L1"},
                            {"name": "02", "slug": "02", "link": "L2"},
                        ],
                    }
                ]
            if url == provider.SOURCE_API:
                return [{"server": "SR", "link": "https://play.example/p?id=1"}]
            return None

        def fake_text(url, referer=""):
            return (
                '<script>window.PLAYER_CONFIG = '
                '{"videoUrl":"/hls/x/index.m3u8"};</script>'
            )

        with mock.patch.object(provider, "_get_text", side_effect=fake_text), \
             mock.patch.object(provider, "_get_json", side_effect=fake_json):
            episodes = provider.fetch_episodes(result)

        self.assertEqual([e.number for e in episodes], [1, 2])
        # Opaque episode ids are upgraded to a direct HLS URL.
        self.assertEqual(episodes[0].url, "https://play.example/hls/x/index.m3u8")
        self.assertEqual(episodes[1].url, "https://play.example/hls/x/index.m3u8")

    def test_miruro_json_search_mapping(self):
        provider = MiruroProvider("https://www.miruro.tv", slug="miruro")
        payload = {
            "data": [
                {
                    "id": "abc123",
                    "title": {"romaji": "NARUTO", "english": "Naruto"},
                    "cover_url": "/img/n.jpg",
                    "season_year": 2002,
                    "description": "A ninja story",
                }
            ],
            "has_more": False,
        }
        with mock.patch.object(provider, "_api_get", return_value=payload) as api_get:
            results = provider.search("naruto")

        # Miruro rejects limits above 15.
        self.assertEqual(api_get.call_args[0][1]["limit"], 15)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source_type, "miruro")
        self.assertEqual(results[0].source_id, "abc123")
        self.assertEqual(results[0].title, "Naruto")
        self.assertEqual(results[0].url, "https://www.miruro.tv/info/abc123")
        self.assertEqual(results[0].poster_url, "https://www.miruro.tv/img/n.jpg")
        self.assertEqual(results[0].year, "2002")

    def test_miruro_decodes_obfuscated_api(self):
        provider = MiruroProvider("https://www.miruro.tv", slug="miruro")
        body = json.dumps({"data": [], "has_more": False}).encode()
        compressed = gzip.compress(body)
        obfuscated = bytes(
            byte ^ MIRURO_XOR_KEY[index % len(MIRURO_XOR_KEY)]
            for index, byte in enumerate(compressed)
        )

        class FakeResponse:
            status_code = 200
            headers = {"content-type": "application/octet-stream"}
            content = obfuscated

        with mock.patch("nook.streaming._curl_available", return_value=False), \
             mock.patch.object(
                 provider.session, "get", return_value=FakeResponse()
             ):
            decoded = provider._api_get("/api/v1/anime", {"q": "naruto"})

        self.assertEqual(decoded, {"data": [], "has_more": False})

    def test_miruro_uses_curl_transport(self):
        """Miruro prefers the curl binary, which bypasses Cloudflare."""
        provider = MiruroProvider("https://www.miruro.tv", slug="miruro")
        body = json.dumps({"data": [{"id": "x"}], "has_more": False}).encode()
        compressed = gzip.compress(body)
        obfuscated = bytes(
            byte ^ MIRURO_XOR_KEY[index % len(MIRURO_XOR_KEY)]
            for index, byte in enumerate(compressed)
        )

        with mock.patch(
            "nook.streaming._curl_available", return_value=True
        ), mock.patch(
            "nook.streaming._curl_fetch", return_value=obfuscated
        ) as curl_fetch:
            decoded = provider._api_get(
                "/api/v1/anime", {"q": "naruto"}, referer="https://x/"
            )

        self.assertEqual(decoded, {"data": [{"id": "x"}], "has_more": False})
        called_url = curl_fetch.call_args[0][0]
        self.assertIn("/api/v1/anime?", called_url)
        self.assertIn("q=naruto", called_url)

    def test_miruro_episode_count_fallback(self):
        provider = MiruroProvider("https://www.miruro.tv", slug="miruro")
        result = StreamResult(
            source_type="miruro",
            source_id="abc",
            title="Show",
            url="https://www.miruro.tv/info/abc",
        )

        def fake_api(path, params=None, referer=""):
            if path.endswith("/episodes"):
                return None
            if path == "/api/v1/anime/abc":
                return {"episode_count": 3}
            return None

        with mock.patch.object(provider, "_api_get", side_effect=fake_api):
            episodes = provider.fetch_episodes(result)

        self.assertEqual([e.number for e in episodes], [1, 2, 3])
        self.assertEqual(
            episodes[0].url, "https://www.miruro.tv/watch/abc?ep=1"
        )

    def test_1tube_search_mapping(self):
        provider = OneTubeProvider("https://www.1tube.org", slug="1tube")
        payload = {
            "results": [
                {
                    "id": 46260,
                    "name": "Naruto",
                    "poster_path": "/n.jpg",
                    "first_air_date": "2002-10-03",
                    "overview": "Ninja",
                },
                {
                    "id": 550,
                    "title": "Fight Club",
                    "poster_path": "https://cdn.example/x.jpg",
                    "release_date": "1999-10-15",
                },
            ]
        }
        with mock.patch.object(provider, "_get_json", return_value=payload):
            results = provider.search("naruto")

        self.assertEqual([r.source_id for r in results], ["46260", "550"])
        self.assertEqual(
            results[0].poster_url, "https://image.tmdb.org/t/p/w500/n.jpg"
        )
        self.assertEqual(results[0].year, "2002")
        self.assertEqual(results[0].url, "https://www.1tube.org/watch/46260")
        self.assertEqual(results[1].poster_url, "https://cdn.example/x.jpg")

    def test_1tube_episode_mapping(self):
        provider = OneTubeProvider("https://www.1tube.org", slug="1tube")
        result = StreamResult(
            source_type="1tube",
            source_id="46260",
            title="Naruto",
            url="https://www.1tube.org/watch/46260",
        )

        def fake_json(url, params=None, headers=None):
            if url.endswith("/api/tv/46260/season/1"):
                return {
                    "episodes": [
                        {"episode_number": 1, "name": "Enter Naruto"},
                        {"episode_number": 2, "name": "My Name is Naruto"},
                    ]
                }
            if url.endswith("/api/tv/46260/season/2"):
                return {"episodes": [{"episode_number": 1, "name": "S2E1"}]}
            return None

        with mock.patch.object(provider, "_get_json", side_effect=fake_json):
            episodes = provider.fetch_episodes(result)

        self.assertEqual(
            [(e.season_number, e.number) for e in episodes],
            [(1, 1), (1, 2), (2, 1)],
        )
        self.assertEqual(episodes[0].season_name, "Season 1")
        self.assertEqual(
            episodes[2].url, "https://www.1tube.org/watch/46260/2/1"
        )

    def test_animeidhentai_search_groups_episodes_by_show(self):
        provider = AnimeIDHentaiProvider(
            "https://animeidhentai.com", slug="animeidhentai"
        )
        payload = {
            "videos": [
                {
                    "titleSlug": "show-a",
                    "title": "Show A",
                    "ep": 1,
                    "year": 2024,
                    "cover": "/uploads/a.jpg",
                    "embedUrl": "https://nhplayer.com/v/a1/",
                },
                {
                    "titleSlug": "show-a",
                    "title": "Show A",
                    "ep": 2,
                    "year": 2024,
                    "cover": "/uploads/a.jpg",
                    "embedUrl": "https://nhplayer.com/v/a2/",
                },
                {
                    "titleSlug": "show-b",
                    "title": "Show B",
                    "ep": 1,
                    "year": 2020,
                    "cover": "https://cdn.example/b.jpg",
                    "embedUrl": "https://nhplayer.com/v/b1/",
                },
            ]
        }
        with mock.patch.object(provider, "_get_json", return_value=payload):
            results = provider.search("show")

        self.assertEqual([r.source_id for r in results], ["show-a", "show-b"])
        self.assertEqual(results[0].title, "Show A")
        self.assertEqual(results[0].url, "https://animeidhentai.com/series/show-a")
        self.assertEqual(
            results[0].poster_url, "https://animeidhentai.com/uploads/a.jpg"
        )
        self.assertEqual(results[1].poster_url, "https://cdn.example/b.jpg")

    def test_animeidhentai_episodes_from_series_page(self):
        provider = AnimeIDHentaiProvider(
            "https://animeidhentai.com", slug="animeidhentai"
        )
        objects = [
            {
                "id": "1",
                "slug": "show-a-episode-1",
                "title": "Show A",
                "titleSlug": "show-a",
                "ep": 1,
                "embedUrl": "https://nhplayer.com/v/one/",
            },
            {
                "id": "2",
                "slug": "show-a-episode-2",
                "title": "Show A",
                "titleSlug": "show-a",
                "ep": 2,
                "embedUrl": "https://nhplayer.com/v/two/",
            },
            {
                "id": "3",
                "slug": "show-b-episode-1",
                "title": "Show B",
                "titleSlug": "show-b",
                "ep": 1,
                "embedUrl": "https://nhplayer.com/v/other/",
            },
        ]
        rsc = "".join(
            json.dumps(obj, separators=(",", ":")) for obj in objects
        )
        page = (
            '<script>self.__next_f.push([1,"'
            + rsc.replace('"', '\\"')
            + '"])</script>'
        )
        result = StreamResult(
            source_type="animeidhentai",
            source_id="show-a",
            title="Show A",
            url="https://animeidhentai.com/series/show-a",
        )
        with mock.patch.object(provider, "_get_text", return_value=page):
            episodes = provider.fetch_episodes(result)

        self.assertEqual([e.number for e in episodes], [1, 2])
        self.assertEqual(episodes[0].url, "https://nhplayer.com/v/one/")
        self.assertEqual(episodes[0].title, "Show A Episode 1")

    def test_flixbaba_search_mapping(self):
        provider = FlixbabaProvider("https://flixbaba.org.uk", slug="flixbaba")
        payload = {
            "results": [
                {
                    "media_type": "tv",
                    "id": 1396,
                    "name": "Breaking Bad",
                    "poster_path": "/bb.jpg",
                    "first_air_date": "2008-01-20",
                    "overview": "Chemistry teacher.",
                },
                {
                    "media_type": "movie",
                    "id": 19995,
                    "title": "Avatar",
                    "poster_path": "/av.jpg",
                    "release_date": "2009-12-18",
                },
                {"media_type": "person", "id": 5, "name": "Someone"},
                {"media_type": "tv", "id": 1396, "name": "Breaking Bad dup"},
            ]
        }
        with mock.patch.object(provider, "_proxy", return_value=payload) as proxy:
            results = provider.search("breaking bad")

        self.assertEqual([r.source_id for r in results], ["tv:1396", "movie:19995"])
        self.assertEqual(proxy.call_args[0][0], "/search/multi")
        self.assertEqual(results[0].url, "https://flixbaba.org.uk/details/tv/1396")
        self.assertEqual(
            results[0].poster_url, "https://flixbaba.org.uk/api/tmdb-img/w500/bb.jpg"
        )
        self.assertEqual(results[0].year, "2008")

    def test_flixbaba_tv_episodes(self):
        provider = FlixbabaProvider("https://flixbaba.org.uk", slug="flixbaba")
        result = StreamResult(
            source_type="flixbaba",
            source_id="tv:1396",
            title="Breaking Bad",
            url="https://flixbaba.org.uk/details/tv/1396",
        )

        def fake_proxy(endpoint, params=None, referer_query=""):
            if endpoint == "/tv/1396/season/1":
                return {
                    "episodes": [
                        {"episode_number": 1, "name": "Pilot"},
                        {"episode_number": 2, "name": "Cat's in the Bag..."},
                    ]
                }
            if endpoint == "/tv/1396/season/2":
                return {"episodes": [{"episode_number": 1, "name": "Seven Thirty-Seven"}]}
            return None

        with mock.patch.object(provider, "_proxy", side_effect=fake_proxy):
            episodes = provider.fetch_episodes(result)

        self.assertEqual(
            [(e.season_number, e.number) for e in episodes],
            [(1, 1), (1, 2), (2, 1)],
        )
        self.assertEqual(
            episodes[0].url, "https://player.cinezo.live/embed/tv/1396/1/1"
        )
        self.assertEqual(episodes[0].title, "Pilot")

    def test_flixbaba_movie_returns_single_embed(self):
        provider = FlixbabaProvider("https://flixbaba.org.uk", slug="flixbaba")
        result = StreamResult(
            source_type="flixbaba",
            source_id="movie:19995",
            title="Avatar",
            url="https://flixbaba.org.uk/details/movie/19995",
        )
        episodes = provider.fetch_episodes(result)
        self.assertEqual(len(episodes), 1)
        self.assertEqual(
            episodes[0].url, "https://player.cinezo.live/embed/movie/19995"
        )

    def test_elisworld_search_parses_show_and_movie_cards(self):
        provider = ElisworldProvider("https://elisworld.tv", slug="elisworld")
        html = """
        <html><body>
          <a href="https://elisworld.tv/cartoons/steven-universe/" class="search-item show-card">
            <div class="show-thumb">
              <img width="300" src="https://elisworld.tv/wp-content/uploads/2024/12/sss-300x300.png">
            </div>
            <div class="ew-cw-title">Steven Universe</div>
            <div class="ew-cw-sub">Cartoon</div>
          </a>
          <a class="ew-cw-card ew-mv-card" href="https://elisworld.tv/movies/ben-10-secret-of-the-omnitrix/">
            <div class="ew-cw-thumb" style="background-image:url('https://elisworld.tv/wp-content/uploads/2025/01/ben-10-movie-300x125.webp');">
              <div class="ew-cw-ep-row"><span class="ew-cw-ep-label">MOVIE</span></div>
            </div>
            <div class="ew-cw-title">Ben 10: Secret of the Omnitrix</div>
            <div class="ew-cw-sub">Movie</div>
          </a>
          <a href="/cartoons/steven-universe/" class="search-item show-card">
            <div class="ew-cw-title">Steven Universe Duplicate</div>
          </a>
        </body></html>
        """
        with mock.patch.object(provider, "_get_text", return_value=html) as get_text:
            results = provider.search("steven universe")

        self.assertEqual(
            [r.source_id for r in results],
            ["cartoons/steven-universe", "movies/ben-10-secret-of-the-omnitrix"],
        )
        self.assertEqual(results[0].title, "Steven Universe")
        self.assertEqual(results[0].url, "https://elisworld.tv/cartoons/steven-universe/")
        self.assertEqual(
            results[0].poster_url,
            "https://elisworld.tv/wp-content/uploads/2024/12/sss-300x300.png",
        )
        self.assertEqual(results[1].title, "Ben 10: Secret of the Omnitrix")
        self.assertEqual(
            results[1].poster_url,
            "https://elisworld.tv/wp-content/uploads/2025/01/ben-10-movie-300x125.webp",
        )
        self.assertIn("/?s=steven+universe", get_text.call_args[0][0])

    def test_elisworld_tv_episodes_from_tmdb(self):
        provider = ElisworldProvider("https://elisworld.tv", slug="elisworld")
        result = StreamResult(
            source_type="elisworld",
            source_id="cartoons/steven-universe",
            title="Steven Universe",
            url="https://elisworld.tv/cartoons/steven-universe/",
        )
        show_html = """
        <script>
          const id = "61175";
          const showSlug = "steven-universe";
          const apiKey = "abc123";
        </script>
        <select id="season-select" class="season-dropdown">
          <option value="1" selected>Season 1</option>
          <option value="2">Season 2</option>
        </select>
        """
        payloads = {
            1: {"episodes": [{"episode_number": 1, "name": "Gem Glow"}]},
            2: {"episodes": [{"episode_number": 1, "name": "Joy Ride"}]},
        }

        def fake_json(url, params=None, headers=None):
            season = int(url.rsplit("/", 1)[-1])
            self.assertEqual(params, {"api_key": "abc123"})
            return payloads[season]

        with mock.patch.object(provider, "_get_text", return_value=show_html), \
                mock.patch.object(provider, "_get_json", side_effect=fake_json):
            episodes = provider.fetch_episodes(result)

        self.assertEqual(
            [(e.season_number, e.number) for e in episodes], [(1, 1), (2, 1)]
        )
        self.assertEqual(episodes[0].title, "Gem Glow")
        self.assertEqual(
            episodes[0].url, "https://elisworld.tv/watch/steven-universe/s1e1/"
        )
        self.assertEqual(episodes[1].url, "https://elisworld.tv/watch/steven-universe/s2e1/")

    def test_stream_resolver_skips_player_placeholder(self):
        provider = ElisworldProvider("https://elisworld.tv", slug="elisworld")
        page = (
            '<script>var x={"blankVideo":'
            '"https://elisworld.tv/wp-content/plugins/easy-video-player/lib/blank.mp4"};'
            "</script>"
        )
        with mock.patch.object(provider, "_get_text", return_value=page):
            self.assertEqual(
                provider.resolve_stream_url("https://elisworld.tv/watch/x/s1e1/"),
                "",
            )

    def test_stream_resolver_finds_real_stream(self):
        provider = GenericStreamingProvider("https://example.com")
        page = "var src = 'https://cdn.example/hls/episode-1.m3u8';"
        with mock.patch.object(provider, "_get_text", return_value=page):
            self.assertEqual(
                provider.resolve_stream_url("https://example.com/watch/1"),
                "https://cdn.example/hls/episode-1.m3u8",
            )

    def test_elisworld_movie_returns_embed(self):
        provider = ElisworldProvider("https://elisworld.tv", slug="elisworld")
        result = StreamResult(
            source_type="elisworld",
            source_id="movies/ben-10-secret-of-the-omnitrix",
            title="Ben 10: Secret of the Omnitrix",
            url="https://elisworld.tv/movies/ben-10-secret-of-the-omnitrix/",
        )
        movie_html = """
        <iframe id="sms-frame" src="https://gomovies-sx.net/embed/movie/15403" allowfullscreen></iframe>
        <iframe src="https://www.google.com/recaptcha/x"></iframe>
        """
        with mock.patch.object(provider, "_get_text", return_value=movie_html):
            episodes = provider.fetch_episodes(result)

        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0].url, "https://gomovies-sx.net/embed/movie/15403")

    def test_generic_search_stops_when_host_is_unreachable(self):
        provider = provider_for_site(
            {"base_url": "https://flux.example", "source_type": "flux"}
        )
        calls = []

        def failing_get(url, **kwargs):
            calls.append(url)
            raise ConnectionError("refused")

        with mock.patch.object(provider.session, "get", side_effect=failing_get):
            results = provider.search("anything")

        self.assertEqual(results, [])
        # One failed request is enough; we do not retry every URL shape.
        self.assertEqual(len(calls), 1)

    def test_miruro_episode_mapping(self):
        provider = MiruroProvider("https://www.miruro.tv", slug="miruro")
        result = StreamResult(
            source_type="miruro",
            source_id="xyz",
            title="Show",
            url="https://www.miruro.tv/info/xyz",
        )
        payload = {
            "data": [
                {"episode_number": 2, "title": "Second"},
                {"episode_number": 1, "title": "First"},
            ]
        }
        with mock.patch.object(provider, "_api_get", return_value=payload):
            episodes = provider.fetch_episodes(result)

        self.assertEqual([e.number for e in episodes], [1, 2])
        self.assertEqual(episodes[0].title, "First")
        self.assertEqual(episodes[1].url, "https://www.miruro.tv/watch/xyz?ep=2")

    SIBLING_POSTER_HTML = """
    <html><body>
      <div class="flw-item">
        <div class="film-poster">
          <img class="film-poster-img lazyload" data-src="https://cdn.site/naruto.jpg"
               src="data:image/gif;base64,R0lGOD" alt="Naruto">
          <a href="/watch/naruto-1234" class="film-poster-ahref"></a>
        </div>
        <div class="film-detail">
          <h3 class="film-name"><a href="/watch/naruto-1234" title="Naruto">Naruto</a></h3>
        </div>
      </div>
      <div class="flw-item">
        <div class="film-poster">
          <img data-src="https://cdn.site/bleach.jpg" src="data:image/gif;base64,R0lGOD">
          <a href="/watch/bleach-9" class="film-poster-ahref"></a>
        </div>
        <div class="film-detail">
          <h3 class="film-name"><a href="/watch/bleach-9">Bleach</a></h3>
        </div>
      </div>
    </body></html>
    """

    DATA_BG_POSTER_HTML = """
    <html><body>
      <div class="ani">
        <div class="poster" data-setbg="/covers/one-piece.jpg"></div>
        <a href="/anime/one-piece-100">One Piece</a>
      </div>
      <div class="ani">
        <a href="/anime/frieren-2">Frieren</a>
        <div class="poster" data-setbg="/covers/frieren.jpg"></div>
      </div>
    </body></html>
    """

    def test_search_result_parsing(self):
        provider = provider_for_site(
            {"base_url": "https://hianime.to", "source_type": "hianime", "name": "HiAnime"}
        )
        results = provider.parse_search_results(self.SEARCH_HTML)

        # Episode links and non-show links are ignored; duplicates are collapsed.
        self.assertEqual([r.source_id for r in results], ["naruto-1234", "bleach-9"])

        first = results[0]
        self.assertEqual(first.source_type, "hianime")
        self.assertEqual(first.title, "Naruto")
        self.assertEqual(first.url, "https://hianime.to/watch/naruto-1234")
        self.assertEqual(first.poster_url, "https://hianime.to/img/naruto.jpg")

        # No metadata on the second card -> falls back to the URL slug.
        self.assertEqual(results[1].title, "Bleach 9")
        self.assertEqual(results[1].poster_url, "https://cdn.example/bleach.png")

    def test_search_parses_sibling_poster_images(self):
        """Posters live in a sibling element (the real-world site layout)."""
        provider = provider_for_site(
            {"base_url": "https://hianime.to", "source_type": "hianime"}
        )
        results = provider.parse_search_results(self.SIBLING_POSTER_HTML)

        self.assertEqual([r.source_id for r in results], ["naruto-1234", "bleach-9"])

        # The lazy-loaded ``data-src`` is used, and the link text wins as title.
        self.assertEqual(results[0].title, "Naruto")
        self.assertEqual(results[0].poster_url, "https://cdn.site/naruto.jpg")
        self.assertEqual(results[1].title, "Bleach")
        self.assertEqual(results[1].poster_url, "https://cdn.site/bleach.jpg")

    def test_search_parses_data_attribute_posters(self):
        """Lazy poster URLs on non-``img`` elements (e.g. ``data-setbg``)."""
        provider = provider_for_site({"base_url": "https://miranime.to"})
        results = provider.parse_search_results(self.DATA_BG_POSTER_HTML)

        self.assertEqual([r.source_id for r in results], ["one-piece-100", "frieren-2"])
        self.assertEqual(results[0].poster_url, "https://miranime.to/covers/one-piece.jpg")
        self.assertEqual(results[1].poster_url, "https://miranime.to/covers/frieren.jpg")

    def test_episode_parsing(self):
        provider = provider_for_site({"base_url": "https://hianime.to", "source_type": "hianime"})
        episodes = provider.parse_episode_links(
            self.SEARCH_HTML, "https://hianime.to/watch/naruto-1234"
        )
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0].number, 5)
        self.assertEqual(episodes[0].url, "https://hianime.to/watch/naruto-1234?ep=5")
        self.assertEqual(episodes[0].title, "Episode 5")

    def test_search_handles_network_failure(self):
        provider = provider_for_site({"base_url": "https://hianime.to"})
        with mock.patch.object(provider, "_get_text", return_value=""):
            self.assertEqual(provider.search("naruto"), [])

    def test_stream_result_dict_roundtrip(self):
        result = StreamResult(
            source_type="hianime",
            source_id="x-1",
            title="Show",
            url="https://hianime.to/watch/x-1",
        )
        data = result.as_dict()
        rebuilt = StreamResult(**{k: data.get(k, "") for k in StreamResult.__dataclass_fields__})
        self.assertEqual(rebuilt, result)

        episode = StreamEpisode(title="Episode 1", url="https://cdn/e1.m3u8", number=1)
        self.assertEqual(episode.as_dict()["number"], 1)

    def test_one_tube_recent_uses_trending_feed(self):
        provider = OneTubeProvider("https://www.1tube.org", slug="1tube")
        payload = {
            "results": [
                {
                    "id": 100,
                    "name": "New Show",
                    "poster_path": "/new.jpg",
                    "first_air_date": "2026-10-01",
                },
                {"id": 200, "title": "New Movie", "poster_path": "/movie.jpg"},
            ]
        }
        with mock.patch.object(provider, "_get_json", return_value=payload) as api:
            results = provider.fetch_recent(limit=20, page=3)

        self.assertEqual([r.source_id for r in results], ["100", "200"])
        self.assertEqual(results[0].poster_url, "https://image.tmdb.org/t/p/w500/new.jpg")
        self.assertEqual(results[1].url, "https://www.1tube.org/watch/200")
        self.assertEqual(api.call_args[0][0], "https://www.1tube.org/api/discover/trending")
        self.assertEqual(api.call_args[1]["params"], {"page": 3})

    def test_flixbaba_recent_uses_trending_proxy(self):
        provider = FlixbabaProvider("https://flixbaba.org.uk", slug="flixbaba")
        payload = {
            "results": [
                {
                    "media_type": "tv",
                    "id": 42,
                    "name": "Fresh Show",
                    "poster_path": "/fresh.jpg",
                    "first_air_date": "2026-09-01",
                },
                {"media_type": "person", "id": 3, "name": "Someone"},
            ]
        }
        with mock.patch.object(provider, "_proxy", return_value=payload) as proxy:
            results = provider.fetch_recent(limit=20, page=2)

        self.assertEqual([r.source_id for r in results], ["tv:42"])
        self.assertEqual(proxy.call_args[0][0], "/trending/all/week")
        self.assertEqual(proxy.call_args[0][1], {"page": 2})

    def test_mmani_recent_uses_filter_api(self):
        provider = MManiProvider("https://mmani.com", slug="mmani")
        payload = {
            "data": [
                {
                    "postid": 900,
                    "postname": "Newest Anime",
                    "ani_cover_large": "https://cdn.example/cover.jpg",
                    "postyear": "2026",
                }
            ]
        }
        with mock.patch.object(provider, "_get_json", return_value=payload) as api:
            results = provider.fetch_recent(limit=20, page=4)

        self.assertEqual([r.source_id for r in results], ["900"])
        self.assertEqual(results[0].title, "Newest Anime")
        self.assertEqual(api.call_args[0][0], provider.FILTER_API)
        self.assertEqual(api.call_args[1]["params"], {"page": 4, "limit": 20})

    def test_animeidhentai_recent_reads_series_archive(self):
        provider = AnimeIDHentaiProvider(
            "https://animeidhentai.com", slug="animeidhentai"
        )
        html = """
        <div class="card">
          <a href="/series/new-show"><img class="poster-img" src="/uploads/new.jpg"></a>
          <div class="card-title">New Show</div>
        </div>
        """
        with mock.patch.object(provider, "_get_text", return_value=html) as get:
            results = provider.fetch_recent(limit=20, page=2)

        self.assertEqual([r.source_id for r in results], ["new-show"])
        self.assertEqual(results[0].poster_url, "https://animeidhentai.com/uploads/new.jpg")
        self.assertIn("/series?page=2", get.call_args[0][0])

    def test_elisworld_recent_reads_cartoon_archive(self):
        provider = ElisworldProvider("https://elisworld.tv", slug="elisworld")
        html = """
        <a href="https://elisworld.tv/cartoons/new-show/" class="archive-item show-card">
          <div class="show-thumb">
            <img src="https://elisworld.tv/uploads/new-show.png" />
          </div>
          <div class="ew-cw-title">New Show</div>
        </a>
        <a href="https://elisworld.tv/movies/a-movie/" class="ew-mv-card">
          <div class="ew-cw-title">A Movie</div>
        </a>
        """
        with mock.patch.object(provider, "_get_text", return_value=html) as get:
            results = provider.fetch_recent(limit=20, page=3)

        self.assertEqual(
            [r.source_id for r in results], ["cartoons/new-show", "movies/a-movie"]
        )
        self.assertEqual(results[0].title, "New Show")
        self.assertEqual(results[1].title, "A Movie")
        self.assertIn("/cartoons/page/3/", get.call_args[0][0])

    def test_miruro_recent_walks_catalog_cursors(self):
        provider = MiruroProvider("https://www.miruro.tv", slug="miruro")
        pages = {
            "": {
                "data": [{"id": "a1", "title": {"romaji": "First"}}],
                "next_cursor": "c2",
            },
            "c2": {
                "data": [{"id": "a2", "title": {"romaji": "Second"}}],
                "next_cursor": "",
            },
        }

        def fake_api(path, params=None, referer=""):
            return pages[(params or {}).get("cursor", "")]

        with mock.patch.object(provider, "_api_get", side_effect=fake_api):
            first = provider.fetch_recent(limit=15, page=1)
            second = provider.fetch_recent(limit=15, page=2)
            third = provider.fetch_recent(limit=15, page=3)

        self.assertEqual([r.source_id for r in first], ["a1"])
        self.assertEqual([r.source_id for r in second], ["a2"])
        self.assertEqual(third, [])

    def test_base_recent_falls_back_to_landing_page(self):
        provider = GenericStreamingProvider(
            "https://example.com", slug="example"
        )
        html = '<a href="/watch/recent-1"><img src="/covers/recent.jpg"></a>'
        with mock.patch.object(provider, "_get_text", return_value=html) as get:
            results = provider.fetch_recent(limit=20, page=1)

        self.assertEqual([r.source_id for r in results], ["recent-1"])
        self.assertEqual(get.call_args[0][0], "https://example.com/")

    def test_hanime_search_and_recent(self):
        provider = HanimeProvider("https://hanime.tv", slug="hanime")
        sample_catalog = [
            {
                "id": 1,
                "name": "Overflow Season 1",
                "slug": "overflow-season-1",
                "search_titles": "Overflow Season 1",
                "brand": "BrandA",
                "cover_url": "https://cdn.example/overflow.jpg",
                "created_at_unix": 100,
                "created_at": "2020-01-01T00:00:00Z",
                "views": 500000,
            },
            {
                "id": 2,
                "name": "Kotowari 1",
                "slug": "kotowari-1",
                "search_titles": "Kotowari 1 overflow",
                "brand": "BrandB",
                "cover_url": "https://cdn.example/kotowari.jpg",
                "created_at_unix": 200,
                "created_at": "2021-01-01T00:00:00Z",
                "views": 100000,
            },
        ]
        with mock.patch.object(provider, "_get_catalog", return_value=sample_catalog):
            # Test search: "overflow" matches both, but "Overflow Season 1" scores higher
            results = provider.search("overflow")
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].source_id, "overflow-season-1")
            self.assertEqual(results[0].title, "Overflow Season 1")
            self.assertEqual(results[0].url, "https://hanime.tv/videos/hentai/overflow-season-1")

            # Test recent: sorts by created_at_unix descending
            recent = provider.fetch_recent(limit=10, page=1)
            self.assertEqual(len(recent), 2)
            self.assertEqual(recent[0].source_id, "kotowari-1")
            self.assertEqual(recent[1].source_id, "overflow-season-1")

            # Test episode
            episodes = provider.fetch_episodes(results[0])
            self.assertEqual(len(episodes), 1)
            self.assertEqual(episodes[0].url, results[0].url)

    def test_hentaihaven_search_and_episodes(self):
        provider = HentaiHavenProvider("https://hentaihaven.xxx", slug="hentaihaven")
        search_payload = [
            {
                "id": 101,
                "slug": "kenki-virgo",
                "title": {"rendered": "Kenki Virgo"},
                "meta": {"vraven_remote_thumbnail": "images/kenki.jpg"},
                "date": "2026-08-20T17:00:00",
            }
        ]
        chapters_payload = [
            {
                "chapter_id": 1,
                "chapter_name": "Episode 1",
                "episode_slug": "episode-1",
                "indexable_content_url": "https://master-lengs.org/kenki/1/master.m3u8",
            },
            {
                "chapter_id": 2,
                "chapter_name": "Episode 2",
                "episode_slug": "episode-2",
                "indexable_content_url": "",
            },
        ]

        def fake_get_json(url, params=None, headers=None):
            if "wp-manga" in url:
                return search_payload
            if "chapters" in url:
                return chapters_payload
            return []

        with mock.patch.object(provider, "_get_json", side_effect=fake_get_json):
            results = provider.search("kenki")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].source_id, "kenki-virgo")
            self.assertEqual(results[0].title, "Kenki Virgo")
            self.assertEqual(results[0].url, "https://hentaihaven.xxx/watch/kenki-virgo/")
            self.assertEqual(results[0].poster_url, "https://img.hentaihaven.xxx/images/kenki.jpg")

            episodes = provider.fetch_episodes(results[0])
            self.assertEqual(len(episodes), 2)
            self.assertEqual(episodes[0].number, 1)
            self.assertEqual(episodes[0].url, "https://master-lengs.org/kenki/1/master.m3u8")
            self.assertEqual(episodes[1].number, 2)
            self.assertEqual(episodes[1].url, "https://hentaihaven.xxx/watch/kenki-virgo/episode-2/")


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

    def test_parse_season_folder(self):
        cases = {
            "Season 1": (1, "Season 1"),
            "Season 02": (2, "Season 2"),
            "S1": (1, "Season 1"),
            "S03": (3, "Season 3"),
            "2": (2, "Season 2"),
            "01": (1, "Season 1"),
            "Season 2 - Kyoto Arc": (2, "Season 2 - Kyoto Arc"),
            "Specials": (0, "Specials"),
            "OVA": (0, "OVAs"),
            "Movies": (0, "Movies"),
            "Extras": (0, "Extras"),
            "Arc 2": (2, "Arc 2"),
            "Part 1": (1, "Part 1"),
        }
        for folder, expected in cases.items():
            self.assertEqual(
                FilenameCleaner.parse_season_folder(folder), expected,
                f"Failed parsing season folder '{folder}'"
            )

        # Non-season folders must not be mis-detected
        for folder in ["Monster", "p2", "CD2NKOTTNN", "1080p", "Bunny"]:
            self.assertIsNone(
                FilenameCleaner.parse_season_folder(folder),
                f"'{folder}' should not be detected as a season folder"
            )


class TestSeasonScanning(unittest.TestCase):
    """Season detection from sub-folders inside a series folder."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.root = Path(self.temp_dir)
        self.db = Database(self.root / "test_seasons.db")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _mk(self, rel: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"0")

    def _scan(self):
        self.db.add_root_directory(str(self.root / "library"))
        LibraryScanner(self.db).scan_all()
        return self.db.get_all_series()

    def test_subfolders_become_seasons(self):
        self._mk("library/Multi Show/Season 1/Multi.Show.S01E01.1080p.mkv")
        self._mk("library/Multi Show/Season 1/Multi.Show.S01E02.1080p.mkv")
        self._mk("library/Multi Show/Season 2/Multi.Show.S02E01.1080p.mkv")
        self._mk("library/Multi Show/Specials/Multi.Show.S00E01.Special.mkv")
        self._mk("library/Flat Show/Flat.Show.S01E01.1080p.mkv")

        series = {s["folder_name"]: s for s in self._scan()}

        multi = series["Multi Show"]
        self.assertEqual(multi["has_seasons"], 1)

        eps = self.db.get_episodes_for_series(multi["id"])
        seasons = {(e["season_number"], e["season_name"]) for e in eps}
        self.assertIn((1, "Season 1"), seasons)
        self.assertIn((2, "Season 2"), seasons)
        self.assertIn((0, "Specials"), seasons)

        # A flat series has no season folders
        self.assertEqual(series["Flat Show"]["has_seasons"], 0)

    def test_single_season_subfolder_is_flagged(self):
        self._mk("library/Solo Show/Season 01/Solo.Show.S01E01.720p.mkv")
        series = {s["folder_name"]: s for s in self._scan()}
        self.assertEqual(series["Solo Show"]["has_seasons"], 1)


class TestScraperMatching(unittest.TestCase):
    """Fuzzy matching of folder names to online search results."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db = Database(Path(self.temp_dir) / "match.db")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_strip_year_and_normalize(self):
        self.assertEqual(strip_year("Spider Man (2002)"), "Spider Man")
        self.assertEqual(strip_year("Spider Man 2002"), "Spider Man")
        self.assertEqual(normalize_title("Spy\u00d7Family"), "spy family")
        self.assertEqual(normalize_title("Bleach 2004"), "bleach")

    def test_exact_match_wins_over_partial(self):
        results = [
            {"title": "Bleach: Thousand-Year Blood War"},
            {"title": "Bleach"},
        ]
        best = find_best_match("Bleach", results)
        self.assertEqual(best["title"], "Bleach")
        self.assertEqual(match_score("Bleach", "Bleach"), 1.0)

    def test_closest_match_is_preferred(self):
        results = [
            {"title": "Grand Blue Fantasy"},
            {"title": "Grand Blue"},
        ]
        self.assertEqual(find_best_match("Grand Blue", results)["title"], "Grand Blue")

    def test_year_is_ignored_when_matching(self):
        results = [{"title": "Spider Man"}]
        self.assertIsNotNone(find_best_match("Spider Man (2002)", results))

    def test_aliases_help_match_other_languages(self):
        results = [
            {"title": "Frieren: Beyond Journey's End",
             "aliases": ["Frieren: Beyond Journey's End", "Sousou no Frieren"]},
        ]
        best = find_best_match("Sousou no Frieren", results)
        self.assertIsNotNone(best)
        self.assertEqual(best["title"], "Frieren: Beyond Journey's End")

    def test_long_superset_does_not_beat_short_match(self):
        main = {"title": "Bleach"}
        spin_off = {"title": "Bleach: Thousand-Year Blood War - The Conflict"}
        best = find_best_match("Bleach", [spin_off, main])
        self.assertEqual(best["title"], "Bleach")

    def test_find_best_result_searches_multiple_providers(self):
        db = self.db
        scraper = OnlineMetadataScraper(db)

        def fake_search(query, provider):
            if provider == "anilist":
                return [{"provider": "AniList", "title": "Frieren: Beyond Journey's End",
                         "aliases": ["Sousou no Frieren"]}]
            return [{"provider": "TVMaze", "title": "Frieren: Beyond Journey's End"}]

        with mock.patch.object(scraper, "search_metadata", side_effect=fake_search):
            best = scraper.find_best_result("Sousou no Frieren")

        self.assertIsNotNone(best)
        self.assertEqual(best["provider"], "AniList")

    def test_find_best_result_returns_none_without_results(self):
        scraper = OnlineMetadataScraper(self.db)
        with mock.patch.object(scraper, "search_metadata", return_value=[]):
            self.assertIsNone(scraper.find_best_result("Some Obscure Show"))

    def test_no_results_returns_none(self):
        self.assertIsNone(find_best_match("Bleach", []))
        self.assertIsNone(find_best_match("Bleach", None))

    def test_unrelated_results_are_rejected(self):
        results = [{"title": "Completely Different Show"}]
        self.assertIsNone(find_best_match("Bleach", results))

    def test_apply_result_to_series_writes_metadata(self):
        r_id = self.db.add_root_directory("/media/tv")
        s_id = self.db.upsert_series(r_id, "/media/tv/Bleach", "Bleach", "Bleach")
        scraper = OnlineMetadataScraper(self.db)

        title = scraper.apply_result_to_series(s_id, {
            "title": "Bleach",
            "year": "2004",
            "description": "Soul reaper.",
            "tags": ["Action", "Supernatural"],
            "poster_url": "",
        })

        self.assertEqual(title, "Bleach (2004)")
        series = self.db.get_series_by_id(s_id)
        self.assertEqual(series["display_title"], "Bleach (2004)")
        self.assertIn("Supernatural", series["tags_list"])
        # No poster URL means the stored cover path is left alone.
        self.assertEqual(series["custom_cover_path"], "")

    def test_apply_result_skips_cover_when_local_artwork_exists(self):
        r_id = self.db.add_root_directory("/media/tv")
        s_id = self.db.upsert_series(r_id, "/media/tv/Show", "Show", "Show")
        scraper = OnlineMetadataScraper(self.db)

        with mock.patch.object(scraper, "download_poster") as download:
            scraper.apply_result_to_series(
                s_id,
                {"title": "Show", "poster_url": "https://example.test/p.jpg"},
                download_cover=False,
            )
            download.assert_not_called()


class TestAutoScrapeNewFolders(unittest.TestCase):
    """Newly recognised folders get auto-matched against online results."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.root = Path(self.temp_dir)
        self.db = Database(self.root / "auto.db")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _mk(self, rel: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"0")

    def test_scanner_tracks_only_new_series(self):
        self._mk("library/Frieren/Sousou.no.Frieren.S01E01.1080p.mkv")
        self.db.add_root_directory(str(self.root / "library"))

        scanner = LibraryScanner(self.db)
        scanner.scan_all()
        self.assertEqual([s["folder_name"] for s in scanner.new_series], ["Frieren"])

        # A second scan must not report the same folder as new again.
        scanner.scan_all()
        self.assertEqual(scanner.new_series, [])

    def test_new_folder_gets_closest_match_applied(self):
        self._mk("library/Grand Blue/Grand.Blue.S01E01.1080p.mkv")
        self.db.add_root_directory(str(self.root / "library"))

        results = [
            {"provider": "AniList", "title": "Grand Blue Fantasy", "year": "2018",
             "description": "wrong show", "tags": [], "poster_url": ""},
            {"provider": "AniList", "title": "Grand Blue", "year": "2018",
             "description": "Diving comedy.", "tags": ["Comedy"], "poster_url": ""},
        ]
        worker = ScanWorker(self.db)
        with mock.patch.object(OnlineMetadataScraper, "search_metadata", return_value=results):
            worker.run()

        series = self.db.get_all_series()
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["display_title"], "Grand Blue (2018)")
        self.assertIn("Comedy", series[0]["tags_list"])

    def test_folder_without_match_is_left_untouched(self):
        self._mk("library/Obscure Show/Obscure.Show.S01E01.mkv")
        self.db.add_root_directory(str(self.root / "library"))

        worker = ScanWorker(self.db)
        with mock.patch.object(OnlineMetadataScraper, "search_metadata", return_value=[]):
            worker.run()

        series = self.db.get_all_series()[0]
        self.assertEqual(series["display_title"], "Obscure Show")

    def test_existing_folders_are_not_rescraped(self):
        self._mk("library/Steins Gate/Steins.Gate.S01E01.mkv")
        self.db.add_root_directory(str(self.root / "library"))

        # First scan creates the series.
        worker = ScanWorker(self.db)
        with mock.patch.object(OnlineMetadataScraper, "search_metadata", return_value=[]) as search:
            worker.run()
            self.assertGreaterEqual(search.call_count, 1)

        # Second scan has no new folders, so no search happens at all.
        with mock.patch.object(OnlineMetadataScraper, "search_metadata", return_value=[]) as search:
            worker.run()
            search.assert_not_called()

    def test_auto_scrape_can_be_disabled(self):
        self._mk("library/New Show/New.Show.S01E01.mkv")
        self.db.add_root_directory(str(self.root / "library"))
        self.db.set_setting("auto_scrape_new_series", "false")

        worker = ScanWorker(self.db)
        with mock.patch.object(OnlineMetadataScraper, "search_metadata", return_value=[]) as search:
            worker.run()
            search.assert_not_called()

    def test_auto_match_returns_only_successful_count(self):
        r_id = self.db.add_root_directory("/media/tv")
        s1 = self.db.upsert_series(r_id, "/media/tv/Matched", "Matched", "Matched")
        s2 = self.db.upsert_series(r_id, "/media/tv/Unmatched", "Unmatched", "Unmatched")
        new = [
            {"series_id": s1, "display_title": "Matched", "folder_name": "Matched"},
            {"series_id": s2, "display_title": "Unmatched", "folder_name": "Unmatched"},
        ]

        def fake_find(scraper_self, query):
            if query == "Matched":
                return {"title": "Matched Show", "year": "", "poster_url": ""}
            return None

        with mock.patch.object(OnlineMetadataScraper, "find_best_result", fake_find):
            matched = auto_match_new_series(self.db, new)

        self.assertEqual(matched, 1)
        self.assertEqual(self.db.get_series_by_id(s1)["display_title"], "Matched Show")
        self.assertEqual(self.db.get_series_by_id(s2)["display_title"], "Unmatched")


class TestMediaPlayer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db = Database(Path(self.temp_dir) / "player.db")
        self.player = MediaPlayer(self.db)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_format_timestamp(self):
        self.assertEqual(MediaPlayer.format_timestamp(0), "00:00")
        self.assertEqual(MediaPlayer.format_timestamp(65), "01:05")
        self.assertEqual(MediaPlayer.format_timestamp(3665), "01:01:05")

    def test_stream_url_is_passed_to_launcher(self):
        series_id = self.db.add_streaming_series(
            "hianime",
            "s1",
            "Stream Show",
            source_url="https://hianime.to/watch/s1",
            episodes=[{"title": "Episode 1", "url": "https://cdn/x/e1.m3u8", "number": 1}],
        )
        episode = self.db.get_episodes_for_series(series_id)[0]

        with mock.patch.object(
            self.player, "_launch_system_player", return_value=(True, "")
        ) as launch:
            ok, err = self.player.play_episode(episode["id"])

        self.assertTrue(ok, err)
        args, kwargs = launch.call_args
        self.assertEqual(args[0], "https://cdn/x/e1.m3u8")
        self.assertTrue(kwargs.get("is_url"))

    def test_missing_local_file_still_reports_error(self):
        r_id = self.db.add_root_directory(self.temp_dir)
        s_id = self.db.upsert_series(r_id, self.temp_dir, "S", "S")
        ep_id = self.db.upsert_episode(
            s_id, str(Path(self.temp_dir) / "missing.mkv"), "missing.mkv", "E1", 1, 1
        )
        ok, err = self.player.play_episode(ep_id)
        self.assertFalse(ok)
        self.assertIn("not found", err)

    def test_custom_player_receives_stream_url(self):
        self.db.set_setting("media_player_mode", "custom")
        self.db.set_setting("media_player_path", "vlc")
        with mock.patch("nook.player.shutil.which", return_value="/usr/bin/vlc"), \
             mock.patch("nook.player.subprocess.Popen") as popen, \
             mock.patch("nook.player.Path.exists", return_value=True):
            ok, err = self.player.play_url("https://cdn/x/e1.m3u8", start_seconds=30)

        self.assertTrue(ok, err)
        command = popen.call_args[0][0]
        self.assertIn("--start-time=30", command)
        self.assertIn("https://cdn/x/e1.m3u8", command)

    def test_get_clean_env_restores_ld_path_and_strips_appimage(self):
        from nook.player import get_clean_env
        with mock.patch.dict(os.environ, {
            "LD_LIBRARY_PATH": "/tmp/.mount_Nook/usr/lib",
            "LD_LIBRARY_PATH_ORIG": "/usr/local/lib",
            "APPIMAGE": "/path/to/Nook.AppImage",
            "APPDIR": "/tmp/.mount_Nook",
            "PYTHONHOME": "/tmp/.mount_Nook/usr",
            "QT_PLUGIN_PATH": "/tmp/.mount_Nook/plugins",
        }, clear=True):
            clean = get_clean_env()
            self.assertEqual(clean.get("LD_LIBRARY_PATH"), "/usr/local/lib")
            self.assertNotIn("APPIMAGE", clean)
            self.assertNotIn("APPDIR", clean)
            self.assertNotIn("PYTHONHOME", clean)
            self.assertNotIn("QT_PLUGIN_PATH", clean)

    def test_get_clean_env_pops_empty_ld_path(self):
        from nook.player import get_clean_env
        with mock.patch.dict(os.environ, {
            "LD_LIBRARY_PATH": "/tmp/.mount_Nook/usr/lib",
            "LD_LIBRARY_PATH_ORIG": "",
        }, clear=True):
            clean = get_clean_env()
            self.assertNotIn("LD_LIBRARY_PATH", clean)

    def test_launch_system_player_passes_clean_env(self):
        with mock.patch("platform.system", return_value="Linux"), \
             mock.patch("nook.player.subprocess.Popen") as popen:
            ok, err = self.player._launch_system_player("/media/video.mp4", "Linux")
            self.assertTrue(ok)
            self.assertIn("env", popen.call_args.kwargs)

    def test_open_system_path_and_folder_pass_clean_env(self):
        from nook.player import open_system_path, open_file_folder
        with mock.patch("platform.system", return_value="Linux"), \
             mock.patch("nook.player.subprocess.Popen") as popen:
            open_system_path("/media/folder")
            self.assertIn("env", popen.call_args.kwargs)
            popen.reset_mock()
            open_file_folder("/media/folder/file.mkv")
            self.assertIn("env", popen.call_args.kwargs)

    def test_open_url_linux_invokes_opener_with_clean_env(self):
        from nook.player import open_url
        with mock.patch("platform.system", return_value="Linux"), \
             mock.patch("nook.player.shutil.which", return_value="/usr/bin/xdg-open"), \
             mock.patch("nook.player.subprocess.Popen") as popen:
            ok = open_url("https://hianime.to/watch/123")
            self.assertTrue(ok)
            self.assertEqual(popen.call_args[0][0], ["/usr/bin/xdg-open", "https://hianime.to/watch/123"])
            self.assertIn("env", popen.call_args.kwargs)

    def test_open_url_windows_invokes_registry_browser_command(self):
        from nook.player import open_url
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("nook.player._open_url_windows", return_value=True) as win_open:
            ok = open_url("https://hianime.to/watch/123")
            self.assertTrue(ok)
            win_open.assert_called_once_with("https://hianime.to/watch/123")

    def test_open_system_path_routes_urls_to_browser(self):
        from nook.player import open_system_path
        with mock.patch("nook.player.open_url", return_value=True) as mock_open:
            ok = open_system_path("https://hianime.to/watch/123")
            self.assertTrue(ok)
            mock_open.assert_called_once_with("https://hianime.to/watch/123")

        # Synthetic URI like hianime:// must not open in explorer
        ok_synth = open_system_path("hianime://naruto-123")
        self.assertFalse(ok_synth)

    def test_play_episode_browser_show_opens_in_browser(self):
        from nook.player import open_url
        series_id = self.db.add_streaming_series(
            "miruro",
            "show1",
            "Browser Show",
            source_url="https://miruro.tv/info/show1",
            episodes=[{"title": "Episode 1", "url": "https://miruro.tv/watch/show1?ep=1", "number": 1}],
        )
        episode = self.db.get_episodes_for_series(series_id)[0]

        with mock.patch("nook.player.open_url", return_value=True) as mock_open:
            ok, err = self.player.play_episode(episode["id"])
            self.assertTrue(ok, err)
            mock_open.assert_called_once_with("https://miruro.tv/watch/show1?ep=1")

    def test_play_episode_browser_show_without_ep_url_falls_back_to_series_page(self):
        from nook.player import open_url
        series_id = self.db.add_streaming_series(
            "miruro",
            "show2",
            "Browser Show 2",
            source_url="https://miruro.tv/info/show2",
            episodes=[],
        )
        # Manually create episode with empty file_path
        ep_id = self.db.upsert_episode(series_id, "", "Ep 1", "Ep 1", 1, 1)

        with mock.patch("nook.player.open_url", return_value=True) as mock_open:
            ok, err = self.player.play_episode(ep_id)
            self.assertTrue(ok, err)
            mock_open.assert_called_once_with("https://miruro.tv/info/show2")


class TestThemes(unittest.TestCase):
    def test_stylesheets_generate(self):
        dark_qss = CozyTheme.get_stylesheet("dark")
        light_qss = CozyTheme.get_stylesheet("light")
        # Dark mode is a true-black theme now.
        self.assertIn(CozyTheme.DARK_PALETTE["bg_base"], dark_qss)
        self.assertIn(CozyTheme.LIGHT_PALETTE["bg_base"], light_qss)
        self.assertIn("QScrollBar", dark_qss)
        self.assertIn("QPushButton", light_qss)
        # Frames are intentionally invisible - no visible borders on buttons.
        self.assertIn("border: none;", dark_qss)

    def test_surfaces_use_theme_background(self):
        """Pages/scroll areas must be pinned to the theme colour.

        Widgets built before the theme is applied can otherwise keep Qt's
        default light palette and paint grey behind the content.
        """
        dark_qss = CozyTheme.get_stylesheet("dark")
        self.assertIn("QStackedWidget > QWidget", dark_qss)
        self.assertIn("QScrollArea > QWidget", dark_qss)
        self.assertNotIn("#efefef", dark_qss)
        base = CozyTheme.DARK_PALETTE["bg_base"]
        surfaces = dark_qss.split("QMainWindow > QWidget")[1].split("}")[0]
        self.assertIn(base, surfaces)

    def test_qpalette_matches_theme(self):
        dark_pal = get_qpalette("dark")
        self.assertEqual(
            dark_pal.color(QPalette.ColorRole.Window).name().upper(),
            CozyTheme.DARK_PALETTE["bg_base"].upper(),
        )

    def test_active_palette_helpers(self):
        set_active_theme("light")
        self.assertEqual(color("bg_base"), CozyTheme.LIGHT_PALETTE["bg_base"])
        self.assertEqual(color_rgba("accent", 0.5), "rgba(200, 109, 81, 0.5)")
        set_active_theme("dark")
        self.assertEqual(color("bg_base"), CozyTheme.DARK_PALETTE["bg_base"])

    def test_accent_presets_available(self):
        names = accent_names()
        self.assertIn("amber", names)
        self.assertIn("blue", names)
        self.assertGreaterEqual(len(names), 8)
        self.assertEqual(normalize_accent_name("BLUE"), "blue")
        self.assertEqual(normalize_accent_name("  rose  "), "rose")
        self.assertEqual(normalize_accent_name("not-a-colour"), DEFAULT_ACCENT)

    def test_accent_overrides_only_accent_keys(self):
        blue = accent_palette("blue", "dark")
        self.assertEqual(blue["accent"], "#4C8DF6")
        self.assertEqual(blue["accent_text"], "#FFFFFF")

        amber = accent_palette("amber", "dark")
        self.assertEqual(amber["accent"], "#E5A93C")
        self.assertEqual(amber["accent_text"], "#0A0A0A")

        light = CozyTheme.get_palette("light", "blue")
        self.assertEqual(light["accent"], accent_palette("blue", "light")["accent"])
        # Backgrounds and typography are untouched by the accent choice.
        self.assertEqual(light["bg_base"], CozyTheme.LIGHT_PALETTE["bg_base"])
        self.assertEqual(light["text_primary"], CozyTheme.LIGHT_PALETTE["text_primary"])

    def test_accent_flows_into_stylesheet_and_helpers(self):
        qss = CozyTheme.get_stylesheet("dark", "cyan")
        self.assertIn(accent_palette("cyan", "dark")["accent"], qss)
        self.assertEqual(active_accent(), "cyan")
        self.assertEqual(color("accent"), accent_palette("cyan", "dark")["accent"])
        set_active_theme("dark", DEFAULT_ACCENT)
        self.assertEqual(active_accent(), DEFAULT_ACCENT)


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

    def test_accent_selection_applies_and_persists(self):
        window = MainWindow(self.db)
        window.settings_view._accent_buttons["violet"].click()

        self.assertEqual(self.db.get_setting("accent", ""), "violet")
        self.assertEqual(window._accent, "violet")
        self.assertEqual(
            color("accent"), accent_palette("violet", "dark")["accent"]
        )
        self.assertEqual(window.settings_view.accent_name_lbl.text(), "Violet")

        # A fresh window restores the saved accent.
        window2 = MainWindow(self.db)
        self.assertEqual(window2._accent, "violet")

        # Leave the palette in its default state for later tests.
        set_active_theme("dark", DEFAULT_ACCENT)

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

    def test_season_headers_in_detail_list(self):
        from nook.ui.series_detail import SeasonSectionHeader

        r_id = self.db.add_root_directory("/tmp/test_root")
        s_id = self.db.upsert_series(
            r_id, "/tmp/test_root/SeasonsShow", "SeasonsShow", "Seasons Show",
            has_seasons=True,
        )
        self.db.upsert_episode(s_id, "/tmp/test_root/SeasonsShow/Season 1/e1.mkv", "e1.mkv", "S01E01", 1, 1, season_name="Season 1")
        self.db.upsert_episode(s_id, "/tmp/test_root/SeasonsShow/Season 1/e2.mkv", "e2.mkv", "S01E02", 1, 2, season_name="Season 1")
        self.db.upsert_episode(s_id, "/tmp/test_root/SeasonsShow/Season 2/e1.mkv", "e1b.mkv", "S02E01", 2, 1, season_name="Season 2")

        detail = SeriesDetailView(self.db, self.player)
        self.db.set_setting("detail_view_mode", "list")
        detail.load_series(s_id)

        headers = []
        layout = detail.episodes_container.layout()
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if isinstance(w, SeasonSectionHeader):
                headers.append(w.season_name)
        self.assertEqual(headers, ["Season 1", "Season 2"])

        # Marking a whole season uses the actual episode rows
        detail._on_mark_season_watched("Season 2", True)
        eps = self.db.get_episodes_for_series(s_id)
        watched = {(e["season_name"], e["watched"]) for e in eps}
        self.assertIn(("Season 2", 1), watched)
        self.assertIn(("Season 1", 0), watched)

    def test_single_season_show_hides_header(self):
        from nook.ui.series_detail import SeasonSectionHeader

        r_id = self.db.add_root_directory("/tmp/test_root")
        s_id = self.db.upsert_series(r_id, "/tmp/test_root/FlatShow", "FlatShow", "Flat Show")
        self.db.upsert_episode(s_id, "/tmp/test_root/FlatShow/e1.mkv", "e1.mkv", "S01E01", 1, 1, season_name="Season 1")

        self.db.set_setting("detail_view_mode", "list")
        detail = SeriesDetailView(self.db, self.player)
        detail.load_series(s_id)

        layout = detail.episodes_container.layout()
        headers = [
            layout.itemAt(i).widget()
            for i in range(layout.count())
            if isinstance(layout.itemAt(i).widget(), SeasonSectionHeader)
        ]
        self.assertEqual(headers, [])

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

    def test_rescan_stability(self):
        window = MainWindow(self.db)
        # Scan 1
        window.settings_view.start_scan()
        while window.settings_view.scan_worker and window.settings_view.scan_worker.isRunning():
            self.app.processEvents()
        # Scan 2 immediately
        window.settings_view.start_scan()
        while window.settings_view.scan_worker and window.settings_view.scan_worker.isRunning():
            self.app.processEvents()
        self.assertTrue(True)

    def test_continue_watching_is_compact(self):
        from PyQt6.QtWidgets import QSizePolicy

        window = MainWindow(self.db)
        carousel = window.library_view.carousel
        # Must never be stretched by the surrounding layout.
        self.assertEqual(
            carousel.sizePolicy().verticalPolicy(), QSizePolicy.Policy.Maximum
        )
        self.assertLessEqual(carousel.height(), carousel.sizeHint().height())

    def test_remove_button_drops_card_from_continue_watching(self):
        r_id = self.db.add_root_directory("/tmp/test_root")
        s_id = self.db.upsert_series(r_id, "/tmp/test_root/Show", "Show", "Show")
        ep_id = self.db.upsert_episode(
            s_id, "/tmp/test_root/Show/e1.mkv", "e1.mkv", "Episode 1", 1, 1
        )
        self.db.update_episode_progress(
            ep_id, playback_position=100, duration_seconds=1000, increment_play_count=True
        )

        window = MainWindow(self.db)
        window.show()
        window.library_view.refresh()
        self.app.processEvents()

        carousel = window.library_view.carousel
        card = carousel.cards_layout.itemAt(0).widget()
        self.assertEqual(card.episode_id, ep_id)

        card.remove_btn.click()
        self.app.processEvents()

        self.assertEqual(self.db.get_recently_watched_episodes(), [])
        # Watch state survives; only the history entry is removed.
        self.assertEqual(self.db.get_episode_by_id(ep_id)["playback_position"], 100)

    def test_hide_and_unhide_flow(self):
        r_id = self.db.add_root_directory("/tmp/test_root")
        s_id = self.db.upsert_series(r_id, "/tmp/test_root/HiddenAnime", "HiddenAnime", "Hidden Anime")
        self.db.set_series_hidden(s_id, True)

        window = MainWindow(self.db)
        window.show()
        window.library_view.refresh()
        self.app.processEvents()

        # Check hidden button is not hidden
        self.assertFalse(window.library_view.show_hidden_btn.isHidden())

        # Toggle show hidden
        window.library_view.show_hidden_btn.click()
        self.app.processEvents()
        hidden_cards = [c for c in window.library_view._cards if c.series_id == s_id]
        self.assertEqual(len(hidden_cards), 1)

        # Unhide
        window.library_view._unhide_series(s_id)
        self.assertEqual(self.db.get_series_by_id(s_id)["is_hidden"], 0)

    def test_browse_tab_shows_configured_sites(self):
        self.db.add_streaming_site("https://hianime.to")
        window = MainWindow(self.db)
        window.switch_tab(window.TAB_BROWSE)
        self.app.processEvents()

        self.assertEqual(window.stack.currentIndex(), window.TAB_BROWSE)
        self.assertEqual(window.browse_view.site_combo.count(), 1)
        self.assertEqual(window.browse_view.site_combo.currentText(), "HiAnime")

    def test_browse_search_and_import(self):
        self.db.add_streaming_site("https://hianime.to")
        window = MainWindow(self.db)
        window.show()
        window.switch_tab(window.TAB_BROWSE)
        self.app.processEvents()
        browse = window.browse_view

        result = StreamResult(
            source_type="hianime",
            source_id="naruto-1",
            title="Naruto",
            url="https://hianime.to/watch/naruto-1",
            year="2002",
        )

        class FakeProvider:
            def search(self, query):
                return [result]

            def fetch_episodes(self, stream_result):
                return [StreamEpisode(title="Episode 1", url="https://cdn/e1.m3u8", number=1)]

        with mock.patch("nook.ui.browse_view.provider_for_site", return_value=FakeProvider()), \
             mock.patch.object(OnlineMetadataScraper, "find_best_result", return_value=None):
            browse.search_input.setText("naruto")
            browse.start_search()
            while browse.search_worker and browse.search_worker.isRunning():
                self.app.processEvents()
            self.app.processEvents()

            self.assertEqual(len(browse._results), 1)
            card = browse.grid_layout.itemAt(0).widget()
            self.assertIsInstance(card, StreamResultCard)
            self.assertEqual(card.title_lbl.text(), "Naruto")
            self.assertTrue(card.add_btn.isEnabled())

            card.add_btn.click()
            while browse.import_worker and browse.import_worker.isRunning():
                self.app.processEvents()
            self.app.processEvents()

        series = self.db.get_series_by_source("hianime", "naruto-1")
        self.assertIsNotNone(series)
        self.assertEqual(series["display_title"], "Naruto (2002)")
        episodes = self.db.get_episodes_for_series(series["id"])
        self.assertEqual(episodes[0]["file_path"], "https://cdn/e1.m3u8")

        # After importing, the freshly rendered card is flagged as already added.
        refreshed = browse.grid_layout.itemAt(0).widget()
        self.assertFalse(refreshed.add_btn.isEnabled())

    def test_browse_recent_shows_with_show_more(self):
        self.db.add_streaming_site("https://example.test")
        window = MainWindow(self.db)
        window.show()
        window.switch_tab(window.TAB_BROWSE)
        self.app.processEvents()
        browse = window.browse_view

        calls = []

        class FakeProvider:
            def fetch_recent(self, limit=20, page=1):
                calls.append(page)
                start = (page - 1) * 40
                count = {1: 40, 2: 2}.get(page, 0)
                return [
                    StreamResult(
                        source_type="example",
                        source_id=f"s{start + i}",
                        title=f"Show {start + i}",
                        url=f"https://example.test/show/{start + i}",
                    )
                    for i in range(count)
                ]

            def search(self, query):
                return []

        def wait_recent():
            for _ in range(300):
                self.app.processEvents()
                if (
                    not browse._recent_loading
                    and not (browse.recent_worker and browse.recent_worker.isRunning())
                ):
                    break
            self.app.processEvents()

        with mock.patch("nook.ui.browse_view.provider_for_site", return_value=FakeProvider()):
            # An empty search is treated as a request for the latest shows.
            browse.search_input.setText("")
            browse.start_search()
            wait_recent()

            self.assertTrue(browse._recent_mode)
            self.assertEqual(len(browse._results), 40)
            self.assertEqual(browse._visible_count, 20)
            self.assertEqual(browse.grid_layout.count(), 20)
            self.assertFalse(browse.show_more_row.isHidden())
            self.assertEqual(calls, [1])

            # The next clicks reveal five buffered cards at a time without
            # another network request.
            for expected in (25, 30, 35, 40):
                browse._show_more()
                wait_recent()
                self.assertEqual(browse._visible_count, expected)
                self.assertEqual(browse.grid_layout.count(), expected)
            self.assertEqual(calls, [1])

            # Once the buffer is empty, another click asks for page 2. It has
            # only two new shows, so both appear on that same click.
            browse._show_more()
            wait_recent()
            self.assertEqual(browse._visible_count, 42)
            self.assertEqual(len(browse._results), 42)
            self.assertEqual(browse.grid_layout.count(), 42)
            self.assertEqual(calls, [1, 2])

            # Page 3 is empty, so the button disappears for good.
            browse._show_more()
            wait_recent()
            self.assertEqual(browse._visible_count, 42)
            self.assertEqual(calls, [1, 2, 3])
            self.assertTrue(browse._recent_exhausted)
            self.assertTrue(browse.show_more_row.isHidden())

    def test_browse_site_change_loads_recent(self):
        self.db.add_streaming_site("https://one.test")
        self.db.add_streaming_site("https://two.test")
        window = MainWindow(self.db)
        window.show()
        window.switch_tab(window.TAB_BROWSE)
        self.app.processEvents()
        browse = window.browse_view

        calls = []

        class FakeProvider:
            def fetch_recent(self, limit=20, page=1):
                calls.append(page)
                return [
                    StreamResult(
                        source_type="example",
                        source_id=f"r{page}",
                        title=f"Recent {page}",
                        url=f"https://example.test/show/{page}",
                    )
                ]

            def search(self, query):
                return []

        with mock.patch("nook.ui.browse_view.provider_for_site", return_value=FakeProvider()):
            # Picking a different site in the dropdown immediately loads its
            # latest shows, with no need to press Search.
            browse.site_combo.setCurrentIndex(1)
            for _ in range(300):
                self.app.processEvents()
                if (
                    not browse._recent_loading
                    and not (browse.recent_worker and browse.recent_worker.isRunning())
                ):
                    break
            self.app.processEvents()

        self.assertTrue(browse._recent_mode)
        self.assertEqual(calls, [1])
        self.assertEqual([r["source_id"] for r in browse._results], ["r1"])

    def test_settings_streaming_site_manager(self):
        window = MainWindow(self.db)
        window.settings_view.stream_url_input.setText("https://miruru.tv")
        window.settings_view._add_streaming_site()

        sites = self.db.get_streaming_sites()
        self.assertEqual([s["name"] for s in sites], ["Miruru"])
        self.assertEqual(window.settings_view.stream_sites_list.count(), 1)
        # The Browse dropdown is refreshed through the signal.
        self.assertEqual(window.browse_view.site_combo.count(), 1)

        window.settings_view.stream_sites_list.setCurrentRow(0)
        window.settings_view._remove_streaming_site()
        self.assertEqual(self.db.get_streaming_sites(), [])
        self.assertEqual(window.browse_view.site_combo.count(), 0)

    def test_library_card_source_badges(self):
        r_id = self.db.add_root_directory("/tmp/lib")
        self.db.upsert_series(r_id, "/tmp/lib/LocalShow", "LocalShow", "Local Show")
        self.db.add_streaming_series(
            "hianime",
            "x1",
            "Stream Show",
            source_url="https://hianime.to/watch/x1",
            episodes=[],
        )

        window = MainWindow(self.db)
        window.library_view.refresh()
        self.app.processEvents()

        badges = {
            c.series_data["source_type"]: c.source_badge
            for c in window.library_view._cards
        }
        self.assertIn("local", badges)
        self.assertIn("hianime", badges)
        # The streaming badge carries a site label, so it is wider than the
        # bare local folder glyph.
        self.assertGreater(badges["hianime"].width(), badges["local"].width())

    def test_stream_series_detail_uses_show_page(self):
        s_id = self.db.add_streaming_series(
            "hianime",
            "s9",
            "Stream Show",
            source_url="https://hianime.to/watch/s9",
            episodes=[{"title": "Episode 1", "url": "https://cdn/e1.m3u8", "number": 1}],
        )
        detail = SeriesDetailView(self.db, self.player)
        detail.load_series(s_id)

        self.assertEqual(detail.open_folder_btn.text(), "Show Page")
        self.assertEqual(len(detail.episodes), 1)

    def test_browse_open_without_adding(self):
        self.db.add_streaming_site("https://hianime.to")
        window = MainWindow(self.db)
        browse = window.browse_view

        result = {
            "source_type": "hianime",
            "source_id": "x1",
            "title": "Some Show",
            "url": "https://hianime.to/watch/x1",
            "poster_url": "",
            "year": "",
            "description": "",
            "poster_path": "",
        }
        browse._on_results([result])
        self.app.processEvents()

        card = browse.grid_layout.itemAt(0).widget()
        with mock.patch("webbrowser.open") as open_mock:
            card.open_btn.click()
            self.app.processEvents()

        open_mock.assert_called_once_with("https://hianime.to/watch/x1")
        # Opening must NOT import anything into the library.
        self.assertIsNone(self.db.get_series_by_source("hianime", "x1"))

    def test_import_applies_closest_online_match(self):
        self.db.add_streaming_site("https://hianime.to")
        window = MainWindow(self.db)
        browse = window.browse_view

        result = StreamResult(
            source_type="hianime",
            source_id="solo-1",
            title="Solo Levelling",
            url="https://hianime.to/watch/solo-1",
        )

        class FakeProvider:
            def search(self, query):
                return [result]

            def fetch_episodes(self, stream_result):
                return [StreamEpisode(title="Episode 1", url="https://cdn/e1.m3u8", number=1)]

        online_match = {
            "provider": "TVMaze",
            "title": "Solo Leveling",
            "year": "2024",
            "description": "A weak hunter becomes the strongest.",
            "tags": ["Action", "Fantasy"],
            "poster_url": "",
        }

        with mock.patch("nook.ui.browse_view.provider_for_site", return_value=FakeProvider()), \
             mock.patch.object(
                 OnlineMetadataScraper, "find_best_result", return_value=online_match
             ):
            browse._add_result(result.as_dict())
            while browse.import_worker and browse.import_worker.isRunning():
                self.app.processEvents()
            self.app.processEvents()

        series = self.db.get_series_by_source("hianime", "solo-1")
        self.assertIsNotNone(series)
        detail = self.db.get_series_by_id(series["id"])
        # The online match's title/description/tags were applied automatically.
        self.assertEqual(detail["display_title"], "Solo Leveling (2024)")
        self.assertEqual(detail["description"], "A weak hunter becomes the strongest.")
        self.assertIn("Fantasy", detail["tags_list"])

    def test_remove_streaming_series_from_library(self):
        r_id = self.db.add_root_directory("/tmp/lib")
        local_id = self.db.upsert_series(r_id, "/tmp/lib/Local", "Local", "Local")
        stream_id = self.db.add_streaming_series(
            "hianime",
            "r1",
            "Removable Show",
            source_url="https://hianime.to/watch/r1",
            episodes=[{"title": "Episode 1", "url": "https://cdn/e1.m3u8", "number": 1}],
        )

        window = MainWindow(self.db)
        window.show()
        window.library_view.refresh()
        self.app.processEvents()

        stream_card = next(c for c in window.library_view._cards if c.series_id == stream_id)
        local_card = next(c for c in window.library_view._cards if c.series_id == local_id)
        # Only streaming shows expose the removal signal path.
        self.assertFalse(stream_card.is_local_source())
        self.assertTrue(local_card.is_local_source())

        with mock.patch(
            "nook.ui.library_view.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            stream_card.remove_requested.emit(stream_id)
        self.app.processEvents()

        self.assertIsNone(self.db.get_series_by_id(stream_id))
        self.assertEqual(self.db.get_episodes_for_series(stream_id), [])
        # The local series is untouched.
        self.assertIsNotNone(self.db.get_series_by_id(local_id))

    def test_local_series_removal_is_refused(self):
        r_id = self.db.add_root_directory("/tmp/lib")
        s_id = self.db.upsert_series(r_id, "/tmp/lib/Local", "Local", "Local")

        window = MainWindow(self.db)
        with mock.patch("nook.ui.library_view.QMessageBox.question") as question:
            window.library_view._remove_series(s_id)

        question.assert_not_called()
        self.assertIsNotNone(self.db.get_series_by_id(s_id))

    def test_browse_posters_are_display_only(self):
        self.db.add_streaming_site("https://hianime.to")
        window = MainWindow(self.db)
        browse = window.browse_view
        png = _make_png_bytes("#22AA55")

        result = StreamResult(
            source_type="hianime",
            source_id="p1",
            title="Poster Show",
            url="https://hianime.to/watch/p1",
            poster_url="https://cdn/p1.jpg",
        )

        class FakeProvider:
            def search(self, query):
                return [result]

            def fetch_episodes(self, stream_result):
                return []

        covers = Path(self.temp_dir) / "covers_search"
        covers.mkdir()

        with mock.patch("nook.ui.browse_view.provider_for_site", return_value=FakeProvider()), \
             mock.patch("nook.ui.browse_view.fetch_remote_image_bytes", return_value=png), \
             mock.patch("nook.database.get_covers_dir", return_value=covers):
            browse.search_input.setText("poster")
            browse.start_search()
            while browse.search_worker and browse.search_worker.isRunning():
                self.app.processEvents()
            self.app.processEvents()

        # The poster is held in memory...
        self.assertEqual(browse._results[0].get("poster_bytes"), png)
        # ...and nothing was written to disk just for searching.
        self.assertEqual(list(covers.iterdir()), [])

        # The card renders the in-memory image.
        card = browse.grid_layout.itemAt(0).widget()
        poster = card.findChild(PosterWidget)
        self.assertIsNotNone(poster._cached_pixmap)

    def test_import_persists_poster_to_covers(self):
        self.db.add_streaming_site("https://hianime.to")
        window = MainWindow(self.db)
        browse = window.browse_view
        png = _make_png_bytes("#AA3322")

        covers = Path(self.temp_dir) / "covers_import"
        covers.mkdir()

        result = {
            "source_type": "hianime",
            "source_id": "p2",
            "title": "Persist Show",
            "url": "https://hianime.to/watch/p2",
            "poster_url": "https://cdn/p2.jpg",
            "year": "",
            "description": "",
            "poster_path": "",
            "poster_bytes": png,
        }

        class FakeProvider:
            def fetch_episodes(self, stream_result):
                return []

        with mock.patch("nook.ui.browse_view.provider_for_site", return_value=FakeProvider()), \
             mock.patch("nook.database.get_covers_dir", return_value=covers), \
             mock.patch.object(OnlineMetadataScraper, "find_best_result", return_value=None):
            browse._add_result(result)
            while browse.import_worker and browse.import_worker.isRunning():
                self.app.processEvents()
            self.app.processEvents()

        series = self.db.get_series_by_source("hianime", "p2")
        self.assertIsNotNone(series)
        stored = series["detected_cover_path"]
        self.assertTrue(stored)
        self.assertTrue(Path(stored).exists())
        self.assertEqual(stored, str(covers / Path(stored).name))
        self.assertEqual(len(list(covers.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
