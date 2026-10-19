"""Online metadata scrapers for Nook (TVMaze, AniList, TMDB).

TVMaze and AniList operate without requiring any API keys.
TMDB operates with an optional user-provided API key.
"""

from __future__ import annotations

import difflib
import html
import re
from typing import Any, Callable, Dict, List, Optional

import requests

from nook.database import Database

# Minimum name similarity required before an online result is trusted enough
# to be applied to a folder automatically. Below this the folder is left
# untouched rather than being renamed to something unrelated.
MATCH_THRESHOLD = 0.45


def strip_html_tags(text: str) -> str:
    """Remove HTML tags and unescape HTML entities."""
    if not text:
        return ""
    clean = re.sub(r"<[^<]+?>", "", text)
    return html.unescape(clean).strip()


def strip_year(text: str) -> str:
    """Remove a trailing ``(YYYY)`` (or bare year) from a title."""
    cleaned = re.sub(r"\s*[\(\[]?(?:19|20)\d{2}[\)\]]?\s*$", "", (text or "").strip())
    return cleaned.strip(" -_.")


def normalize_title(text: str) -> str:
    """Lowercase a title and drop years/punctuation for fuzzy comparison."""
    text = strip_year(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def match_score(query: str, candidate: str) -> float:
    """Return a 0-1 similarity between a folder name and a result title."""
    q = normalize_title(query)
    c = normalize_title(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0

    ratio = difflib.SequenceMatcher(None, q, c).ratio()
    q_tokens = set(q.split())
    c_tokens = set(c.split())
    coverage = len(q_tokens & c_tokens) / len(q_tokens) if q_tokens else 0.0

    score = 0.6 * ratio + 0.4 * coverage
    # A title contained in the other (e.g. "Show" vs "Show Season 2 Preview")
    # is a strong signal, but a long superset should not outrank a near-exact
    # match, so the bonus scales with how much extra text it carries.
    if q in c or c in q:
        shorter, longer = sorted((q, c), key=len)
        score = max(score, 0.75 + 0.2 * (len(shorter) / len(longer)))
    return min(score, 1.0)


def find_best_match(
    query: str,
    results: Optional[List[Dict[str, Any]]],
    threshold: float = MATCH_THRESHOLD,
) -> Optional[Dict[str, Any]]:
    """Pick the result whose title is closest to ``query``.

    Returns ``None`` when there are no results (or the closest match is too
    dissimilar), so callers can leave the folder exactly as it was found.
    """
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for result in results or []:
        score = best_result_score(query, result)
        if score > best_score:
            best, best_score = result, score
    if best is not None and best_score >= threshold:
        return best
    return None


def best_result_score(query: str, result: Dict[str, Any]) -> float:
    """Highest match score across a result's title and any aliases.

    Providers only expose one display title but may carry alternate names
    (e.g. AniList romaji/native titles), which helps folders named in a
    different language still find the right entry.
    """
    candidates = [result.get("title") or ""]
    candidates.extend(result.get("aliases") or [])
    return max((match_score(query, title) for title in candidates if title), default=0.0)


def auto_match_new_series(
    db: Database,
    new_series: Optional[List[Dict[str, Any]]],
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> int:
    """Fetch and apply the closest online match for newly discovered folders.

    ``new_series`` is the list produced by :class:`~nook.scanner.LibraryScanner`
    (each entry carries ``series_id``, ``display_title`` etc). Folders whose
    best match is too weak are left exactly as scanned. Honours the
    ``auto_scrape_new_series`` setting and never raises on network errors.

    ``on_progress(index, total, message)`` is called before each lookup.

    Returns how many folders were successfully updated.
    """
    if not new_series:
        return 0
    if db.get_setting("auto_scrape_new_series", "true") != "true":
        return 0

    scraper = OnlineMetadataScraper(db)
    total = len(new_series)
    matched = 0
    for index, item in enumerate(new_series, start=1):
        query = item.get("display_title") or item.get("folder_name") or ""
        if on_progress:
            on_progress(index, total, f"Fetching online info {index}/{total}: {query}")
        try:
            best = scraper.find_best_result(query)
            if not best:
                continue
            scraper.apply_result_to_series(
                item["series_id"],
                best,
                fallback_title=item.get("display_title") or item.get("folder_name"),
                fallback_description=item.get("description", ""),
                fallback_tags=item.get("tags"),
                # Keep locally supplied artwork when the folder has any.
                download_cover=not item.get("has_local_cover"),
            )
            matched += 1
        except Exception:
            # Network hiccups must never abort the scan itself.
            continue
    return matched


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

    def find_best_result(self, query: str) -> Optional[Dict[str, Any]]:
        """Return the online result whose title is closest to ``query``.

        The user's preferred provider is consulted first; if it cannot offer
        an exact name match the remaining providers are tried as well and the
        closest overall result wins. Returns ``None`` when nothing matches
        closely enough, in which case the caller should leave the folder as-is.
        """
        query = (query or "").strip()
        if not query:
            return None

        search_query = strip_year(query) or query
        preferred = self.db.get_setting("preferred_scraper", "tvmaze")
        providers = [preferred] + [
            p for p in ("tvmaze", "anilist", "tmdb") if p != preferred
        ]

        best: Optional[Dict[str, Any]] = None
        best_score = 0.0
        seen = set()

        for provider in providers:
            if provider == "tmdb" and not self.db.get_setting("tmdb_api_key", "").strip():
                continue
            try:
                results = self.search_metadata(search_query, provider)
            except Exception:
                results = []

            for result in results or []:
                # AniList falls back to TVMaze when empty, so skip duplicates.
                key = (result.get("provider"), normalize_title(result.get("title") or ""))
                if key in seen:
                    continue
                seen.add(key)
                score = best_result_score(query, result)
                if score > best_score:
                    best, best_score = result, score

            # An exact name match cannot be beaten, so stop early.
            if best_score >= 1.0:
                break

        if best is not None and best_score >= MATCH_THRESHOLD:
            return best
        return None

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
                english = titles.get("english")
                romaji = titles.get("romaji")
                native = titles.get("native")
                best_title = english or romaji or native or query
                images = m.get("coverImage", {})
                poster_url = images.get("extraLarge") or images.get("large") or ""
                score = m.get("averageScore")
                rating = f"{score/10:.1f}" if score else None

                results.append({
                    "provider": "AniList",
                    "title": best_title,
                    # All known names help match folders named in any language.
                    "aliases": [t for t in (english, romaji, native) if t],
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

    def apply_result_to_series(
        self,
        series_id: int,
        result: Dict[str, Any],
        fallback_title: Optional[str] = None,
        fallback_description: str = "",
        fallback_tags: Optional[List[str]] = None,
        download_cover: bool = True,
    ) -> Optional[str]:
        """Apply a scraped result (title/year/tags/description/poster) to a series.

        Used both by the manual "Apply to Series" button and by the automatic
        matching of newly added folders. Returns the applied display title.

        ``download_cover=False`` keeps any locally supplied artwork in place
        while still importing the textual metadata.
        """
        saved_cover = None
        poster_url = result.get("poster_url")
        if poster_url and download_cover:
            saved_cover = self.download_poster(
                poster_url, series_name=result.get("title", "series")
            )

        title = result.get("title")
        year = str(result.get("year") or "")
        if year and title and year not in title:
            final_title = f"{title} ({year})"
        else:
            final_title = title or fallback_title

        description = result.get("description") or fallback_description
        tags = result.get("tags") or fallback_tags or []

        self.db.update_series_customization(
            series_id=series_id,
            display_title=final_title,
            custom_cover_path=saved_cover if saved_cover else None,
            tags=tags,
            description=description,
        )
        return final_title
