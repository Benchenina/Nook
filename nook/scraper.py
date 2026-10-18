"""Online metadata scrapers for Nook (TVMaze, AniList, TMDB).

TVMaze and AniList operate without requiring any API keys.
TMDB operates with an optional user-provided API key.
"""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional

import requests

from nook.database import Database


def strip_html_tags(text: str) -> str:
    """Remove HTML tags and unescape HTML entities."""
    if not text:
        return ""
    clean = re.sub(r"<[^<]+?>", "", text)
    return html.unescape(clean).strip()


class OnlineMetadataScraper:
    """Fetches series descriptions and poster artwork from public APIs."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Nook-Video-Library/1.0 (Cozy Desktop App)"
        })

    def search_metadata(self, query: str, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search across providers for matching metadata."""
        if not provider:
            provider = self.db.get_setting("preferred_scraper", "tvmaze")

        query = query.strip()
        if not query:
            return []

        results = []
        if provider == "anilist":
            results = self._search_anilist(query)
            if not results:
                # Fallback to TVMaze if anilist returned nothing
                results = self._search_tvmaze(query)
        elif provider == "tmdb":
            tmdb_key = self.db.get_setting("tmdb_api_key", "").strip()
            if tmdb_key:
                results = self._search_tmdb(query, tmdb_key)
            else:
                # Fallback to TVMaze if no key provided
                results = self._search_tvmaze(query)
        else:
            # Default TVMaze
            results = self._search_tvmaze(query)
            if not results:
                # Try AniList as fallback
                results = self._search_anilist(query)

        return results

    def _search_tvmaze(self, query: str) -> List[Dict[str, Any]]:
        """Search TVMaze API (no API key required)."""
        url = "https://api.tvmaze.com/search/shows"
        try:
            resp = self.session.get(url, params={"q": query}, timeout=8)
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = []
            for item in data[:5]:
                show = item.get("show", {})
                images = show.get("image") or {}
                poster_url = images.get("original") or images.get("medium") or ""
                summary = strip_html_tags(show.get("summary") or "")
                premiered = (show.get("premiered") or "")[:4]

                results.append({
                    "provider": "TVMaze",
                    "title": show.get("name") or query,
                    "year": premiered,
                    "description": summary,
                    "tags": show.get("genres") or [],
                    "poster_url": poster_url,
                    "rating": (show.get("rating") or {}).get("average"),
                    "external_url": show.get("url") or ""
                })
            return results
        except Exception:
            return []

    def _search_anilist(self, query: str) -> List[Dict[str, Any]]:
        """Search AniList GraphQL API (no API key required)."""
        url = "https://graphql.anilist.co"
        gql_query = """
        query ($search: String) {
          Page(page: 1, perPage: 5) {
            media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
              id
              title {
                romaji
                english
                native
              }
              description(asHtml: false)
              genres
              seasonYear
              averageScore
              coverImage {
                extraLarge
                large
              }
              siteUrl
            }
          }
        }
        """
        try:
            resp = self.session.post(url, json={"query": gql_query, "variables": {"search": query}}, timeout=8)
            if resp.status_code != 200:
                return []
            data = resp.json()
            media_list = data.get("data", {}).get("Page", {}).get("media", [])
            results = []
            for m in media_list:
                titles = m.get("title", {})
                best_title = titles.get("english") or titles.get("romaji") or titles.get("native") or query
                images = m.get("coverImage", {})
                poster_url = images.get("extraLarge") or images.get("large") or ""
                score = m.get("averageScore")
                rating = f"{score/10:.1f}" if score else None

                results.append({
                    "provider": "AniList",
                    "title": best_title,
                    "year": str(m.get("seasonYear") or ""),
                    "description": strip_html_tags(m.get("description") or ""),
                    "tags": m.get("genres") or [],
                    "poster_url": poster_url,
                    "rating": rating,
                    "external_url": m.get("siteUrl") or ""
                })
            return results
        except Exception:
            return []

    def _search_tmdb(self, query: str, api_key: str) -> List[Dict[str, Any]]:
        """Search TMDB multi-search API with user's API key."""
        url = "https://api.themoviedb.org/3/search/multi"
        try:
            resp = self.session.get(url, params={"query": query, "api_key": api_key}, timeout=8)
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = []
            for item in data.get("results", [])[:5]:
                title = item.get("title") or item.get("name") or query
                date = item.get("release_date") or item.get("first_air_date") or ""
                year = date[:4] if date else ""
                poster_path = item.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""

                results.append({
                    "provider": "TMDB",
                    "title": title,
                    "year": year,
                    "description": item.get("overview") or "",
                    "tags": [],
                    "poster_url": poster_url,
                    "rating": item.get("vote_average"),
                    "external_url": f"https://www.themoviedb.org/{item.get('media_type', 'movie')}/{item.get('id')}"
                })
            return results
        except Exception:
            return []

    def download_poster(self, image_url: str, series_name: str = "series") -> Optional[str]:
        """Download image from URL and save to Nook managed covers directory."""
        if not image_url:
            return None
        try:
            resp = self.session.get(image_url, timeout=12)
            if resp.status_code == 200 and len(resp.content) > 0:
                safe_prefix = re.sub(r"[^a-zA-Z0-9]", "_", series_name)[:20]
                saved_path = self.db.save_cover_image(resp.content, prefix=f"poster_{safe_prefix}")
                return saved_path
        except Exception:
            pass
        return None
