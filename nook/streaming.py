"""Online streaming site integration for Nook.

Nook is first and foremost a local library manager, but it can also *browse*
user-registered streaming sites (HiAnime, Miruru, …), search their catalogue,
and import a show into the library as a *stream series*.

Imported shows store their composite ``(source_type, source_id)`` identifier in
the database and keep the remote URL of every episode in ``file_path`` so the
:class:`~nook.player.MediaPlayer` can hand the URL straight to VLC/MPV or the
system default handler.

The HTML parsing here is intentionally heuristic (no BeautifulSoup dependency):
each provider exposes a search URL template plus a couple of patterns, and a
generic fallback provider is used for any site that is not explicitly known.
Everything degrades gracefully - network/parse failures simply yield no
results so the UI can show an empty state.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus, urlencode, urljoin, urlparse

import requests

from nook.database import Database

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
URL_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _curl_available() -> bool:
    """Return True when the system ``curl`` binary can be used."""
    return bool(shutil.which("curl"))


def _curl_fetch(url: str, headers: Dict[str, str], timeout: int = 15) -> bytes:
    """Fetch *url* with the system ``curl`` binary.

    Some sites (notably Miruro) sit behind a Cloudflare filter that rejects
    Python's TLS fingerprint while happily serving ``curl``. Using the binary
    as a fallback keeps those sites working without adding a new dependency.
    """
    merged = dict(DEFAULT_HEADERS)
    merged.update(headers)
    command = [
        "curl",
        "-sS",
        "-L",
        "--max-time",
        str(int(timeout)),
        "-A",
        merged["User-Agent"],
    ]
    for key, value in merged.items():
        if key.lower() == "user-agent":
            continue
        command.extend(["-H", f"{key}: {value}"])
    command.append(url)
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout + 5, check=False
        )
    except Exception:
        return b""
    if completed.returncode != 0 or not completed.stdout:
        return b""
    return completed.stdout

# Some poster CDNs reject requests that do not look like an image load from a
# browser, so image downloads get a browser-ish Accept header.
IMAGE_HEADERS = {
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}

# Link fragments that usually identify a *show* page on streaming sites.
DEFAULT_ITEM_PATTERNS: Sequence[str] = (
    "/watch/",
    "/anime/",
    "/series/",
    "/show/",
    "/tv/",
    "/movie/",
    "/film/",
    "/detail/",
    "/info/",
    "/media/",
    "/title/",
)

# Search URL shapes tried by the generic provider, in order. Sites differ wildly
# in what they call the query parameter, so we try the common ones until one
# yields parsed results.
GENERIC_SEARCH_PATHS: Sequence[str] = (
    "/search?q={query}",
    "/search?query={query}",
    "/search?keyword={query}",
    "/search?wd={query}",
    "/search/?q={query}",
    "/search/?wd={query}",
    "/?s={query}",
    "/search/{query}",
    "/browse?q={query}",
)

# Never spend more than this many HTTP requests on a single search.
MAX_SEARCH_ATTEMPTS = 4

# Give up on a search after this many seconds even if requests keep timing out.
SEARCH_DEADLINE_SECONDS = 22

# How far (in characters of source) an ``<img>`` may sit from a show link and
# still be treated as that card's poster. Streaming sites put the poster in a
# sibling element rather than inside the link, so this proximity match is what
# actually finds the artwork.
IMAGE_MATCH_WINDOW = 1600

# Cap how many episode pages we try to resolve into direct stream URLs. Each
# attempt costs one HTTP request, so we keep it small.
STREAM_RESOLVE_LIMIT = 4

# Player chrome sometimes ships a placeholder video (e.g. plyr's ``blank.mp4``)
# that naive resolution mistakes for the real stream. Never treat those as one.
_PLAYER_ASSET_RE = re.compile(
    r"/(?:blank|placeholder|sample|preview|poster|loading)\.(?:mp4|m3u8)$",
    re.IGNORECASE,
)

# Maximum number of search results rendered in the Browse grid.
MAX_RESULTS = 24

# How many shows a single "latest / recent" page request returns. The Browse
# tab shows the first RECENT_INITIAL_VISIBLE and then reveals five more per
# "Show More" click, requesting another page only when its local buffer runs
# dry.
RECENT_PAGE_SIZE = 20

# Sites we know a little more about (search template + display name).
KNOWN_SITES: Dict[str, Dict[str, Any]] = {
    "hianime": {
        "name": "HiAnime",
        "search_path": "/search?keyword={query}",
        "item_patterns": ("/watch/",),
    },
    "witanime": {
        "name": "WitAnime",
    },
    "mmani": {
        "name": "MMani",
        "search_path": "/search/?wd={query}",
        "item_patterns": ("/up/",),
    },
    "miruro": {
        "name": "Miruro",
        "search_path": "/search?query={query}",
        "item_patterns": ("/info/", "/watch/"),
    },
    "miruru": {
        "name": "Miruru",
        "search_path": "/search?q={query}",
        "item_patterns": ("/anime/", "/series/", "/watch/", "/show/", "/detail/"),
    },
    "flixer": {
        "name": "Flixer",
        "search_path": "/search?q={query}",
        "item_patterns": ("/watch/", "/movie/", "/tv/", "/show/", "/film/"),
    },
    "1tube": {
        "name": "1Tube",
        "search_path": "/search?q={query}",
        "item_patterns": ("/watch/",),
    },
    "animeidhentai": {
        "name": "AnimeIDHentai",
        "search_path": "/explore?q={query}",
        "item_patterns": ("/series/",),
    },
    "flixbaba": {
        "name": "Flixbaba",
        "search_path": "/search?q={query}",
        "item_patterns": ("/details/",),
    },
    "elisworld": {
        "name": "Elisworld",
        "search_path": "/?s={query}",
        "item_patterns": ("/cartoons/", "/movies/"),
    },
    "hanime": {
        "name": "Hanime",
        "item_patterns": ("/videos/hentai/",),
    },
    "hentaihaven": {
        "name": "Hentai Haven",
        "search_path": "/search/?q={query}",
        "item_patterns": ("/watch/",),
    },
    "hentaiheaven": {
        "name": "Hentai Haven",
        "search_path": "/search/?q={query}",
        "item_patterns": ("/watch/",),
    },
}


# ---------------------------------------------------------------------------
# URL / slug helpers
# ---------------------------------------------------------------------------
def is_stream_url(value: Optional[str]) -> bool:
    """Return True when ``value`` looks like an http(s) URL."""
    return bool(value and URL_SCHEME_RE.match(value.strip()))


def site_slug(name_or_url: str) -> str:
    """Derive a short, filesystem-safe slug from a site name or URL.

    ``https://hianime.to`` -> ``hianime``; ``www.miruru.tv`` -> ``miruru``.
    """
    text = (name_or_url or "").strip().lower()
    if not text:
        return "stream"
    host = urlparse(text).netloc if "://" in text else text
    host = host.split("/")[0].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    first_label = host.split(".")[0] if host else "stream"
    slug = re.sub(r"[^a-z0-9]+", "", first_label)
    return slug or "stream"


def normalize_site_url(base_url: str) -> str:
    """Normalise a base URL to ``scheme://host`` (no trailing slash).

    Returns an empty string when the value cannot be interpreted as a URL.
    """
    url = (base_url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    netloc = parsed.netloc
    if not netloc or any(char.isspace() for char in netloc):
        return ""
    return f"{parsed.scheme}://{netloc}".rstrip("/")


def site_display_name(base_url: str, slug: str = "") -> str:
    """Human friendly name for a site (e.g. ``HiAnime``)."""
    key = (slug or site_slug(base_url)).lower()
    known = KNOWN_SITES.get(key)
    if known and known.get("name"):
        return known["name"]
    if not key:
        return "Stream"
    return key[:1].upper() + key[1:]


def extract_source_id(url: str) -> str:
    """Return a stable id for a show from its page URL.

    Uses the last path segment (e.g. ``/watch/naruto-1234`` -> ``naruto-1234``).
    """
    path = urlparse(url or "").path.strip("/")
    if not path:
        return ""
    segment = path.split("/")[-1]
    return re.sub(r"[?#].*$", "", segment)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------
@dataclass
class StreamResult:
    """A single search result from a streaming site."""

    source_type: str
    source_id: str
    title: str
    url: str
    poster_url: str = ""
    year: str = ""
    description: str = ""
    poster_path: str = ""  # local cached copy, filled after download

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "poster_url": self.poster_url,
            "year": self.year,
            "description": self.description,
            "poster_path": self.poster_path,
        }


@dataclass
class StreamEpisode:
    """A single episode link discovered on a show page."""

    title: str
    url: str
    number: int = 0
    season_number: int = 1
    season_name: str = "Season 1"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "number": self.number,
            "season_number": self.season_number,
            "season_name": self.season_name,
        }


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
class BaseStreamingProvider:
    """Base class for streaming site providers."""

    name = "Stream"
    SEARCH_PATH = "/search?q={query}"
    ITEM_PATTERNS: Sequence[str] = DEFAULT_ITEM_PATTERNS

    def __init__(self, base_url: str, slug: str = "", name: str = ""):
        self.base_url = normalize_site_url(base_url)
        self.slug = slug or site_slug(base_url)
        self.name = name or site_display_name(base_url, self.slug)
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._request_failed = False

    # -- HTTP helpers -------------------------------------------------
    def _get_text(self, url: str, referer: str = "") -> str:
        self._request_failed = False
        try:
            headers = {"Referer": referer} if referer else None
            resp = self.session.get(url, timeout=8, headers=headers)
            if resp.status_code == 200 and resp.text:
                return resp.text
            if resp.status_code >= 500:
                self._request_failed = True
        except Exception:
            # Connection refused / DNS failure / timeout: trying other URL
            # shapes on the same host cannot help, so remember the failure.
            self._request_failed = True
        return ""

    def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None,
                  headers: Optional[Dict[str, str]] = None) -> Any:
        """GET a JSON payload, returning ``None`` on any failure."""
        request_headers = dict(headers or {})
        use_curl = False
        try:
            resp = self.session.get(
                url, params=params, headers=request_headers or None, timeout=15
            )
            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception:
                    use_curl = True
            elif resp.status_code in (403, 429, 503):
                use_curl = True
        except Exception:
            use_curl = True

        # Cloudflare sometimes rejects Python clients but allows curl.
        if use_curl and _curl_available():
            final_url = url
            if params:
                final_url = f"{url}?{urlencode(params)}"
            body = _curl_fetch(final_url, request_headers)
            if body:
                try:
                    return json.loads(body.decode("utf-8", "replace"))
                except Exception:
                    return None
        return None

    def _absolute(self, href: str) -> str:
        if not href:
            return ""
        if is_stream_url(href):
            return href
        return urljoin(self.base_url + "/", href.lstrip("/"))

    def _search_url(self, query: str, path: Optional[str] = None) -> str:
        path = path or self.SEARCH_PATH
        if "{query}" in path:
            return self.base_url + path.format(query=quote_plus(query))
        joiner = "&" if "?" in path else "?"
        return f"{self.base_url}{path}{joiner}keyword={quote_plus(query)}"

    def _search_paths(self) -> List[str]:
        """Ordered list of search URL shapes to try."""
        paths: List[str] = [self.SEARCH_PATH]
        paths.extend(GENERIC_SEARCH_PATHS)
        ordered: List[str] = []
        for path in paths:
            if path and path not in ordered:
                ordered.append(path)
        return ordered[:MAX_SEARCH_ATTEMPTS]

    # -- Public API ---------------------------------------------------
    def search(self, query: str) -> List[StreamResult]:
        query = (query or "").strip()
        if not query or not self.base_url:
            return []
        deadline = time.monotonic() + SEARCH_DEADLINE_SECONDS
        for path in self._search_paths():
            if time.monotonic() > deadline:
                break
            html_text = self._get_text(self._search_url(query, path))
            if not html_text:
                if self._request_failed:
                    # The host itself is unreachable; stop retrying.
                    break
                continue
            results = self.parse_search_results(html_text)[:MAX_RESULTS]
            if results:
                return results
        return []

    def fetch_recent(self, limit: int = RECENT_PAGE_SIZE,
                     page: int = 1) -> List[StreamResult]:
        """Return the site's latest show listing, best effort.

        The default implementation reads the landing page (page 1) or common
        pagination paths and parses them heuristically. Providers backed by a
        JSON catalog override this with their real "latest" feed.
        """
        if not self.base_url or limit <= 0:
            return []
        page = max(1, int(page or 1))
        if page == 1:
            urls = [self.base_url + "/"]
        else:
            urls = [
                f"{self.base_url}/page/{page}/",
                f"{self.base_url}/page/{page}",
                f"{self.base_url}/?page={page}",
                f"{self.base_url}/?paged={page}",
            ]
        for url in urls:
            html_text = self._get_text(url)
            if not html_text:
                if self._request_failed:
                    break
                continue
            results = _dedupe_results(self.parse_search_results(html_text))
            if results:
                return results[:limit]
        return []

    def fetch_episodes(self, result: StreamResult) -> List[StreamEpisode]:
        """Best-effort episode discovery for an imported show."""
        if not result.url:
            return []
        page = self._get_text(result.url)
        if not page:
            return []
        episodes = self.parse_episode_links(page, result.url)
        # Try to upgrade the first few page links into direct stream URLs.
        for episode in episodes[:STREAM_RESOLVE_LIMIT]:
            direct = self.resolve_stream_url(episode.url)
            if direct:
                episode.url = direct
        return episodes

    # -- Parsing ------------------------------------------------------
    def parse_search_results(self, html_text: str) -> List[StreamResult]:
        """Heuristically extract show cards (link + poster) from a page.

        Streaming sites rarely nest the poster ``<img>`` inside the show link -
        it usually sits in a sibling element - and often expose two links per
        card (a poster link and a title link). This method therefore:

        * collects every show link and every ``<img>`` with its position;
        * merges links that point at the same show;
        * attaches the nearest image to each card as its poster.
        """
        text = html_text or ""

        anchors: List[Dict[str, Any]] = []
        for match in _ANCHOR_RE.finditer(text):
            attrs = _parse_attrs(match.group(1))
            href = attrs.get("href", "")
            lowered_href = href.lower()
            if (
                not href
                or lowered_href.startswith(("#", "javascript:", "mailto:", "tel:"))
                or "?ep=" in href
                or "/episode" in lowered_href
            ):
                continue
            absolute = self._absolute(href)
            if not absolute:
                continue
            path = urlparse(absolute).path.lower()
            if not any(pattern in path for pattern in self.ITEM_PATTERNS):
                continue
            source_id = extract_source_id(absolute)
            if not source_id:
                continue
            anchors.append({
                "source_id": source_id,
                "url": absolute,
                "attrs": attrs,
                "inner": match.group(2),
                "pos": match.start(),
            })

        if not anchors:
            return []

        # Every plausible poster URL in the document, with its position, so a
        # card's artwork can be found even when it is not inside the link.
        images = _iter_document_images(text)

        def nearest_image(position: int):
            best_url = ""
            best_alt = ""
            best_distance: Optional[int] = None
            for img_pos, img_url, img_alt in images:
                distance = abs(img_pos - position)
                if best_distance is None or distance < best_distance:
                    best_distance, best_url, best_alt = distance, img_url, img_alt
            if best_distance is not None and best_distance <= IMAGE_MATCH_WINDOW:
                return best_url, best_alt
            return "", ""

        cards: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []

        for anchor in anchors:
            source_id = anchor["source_id"]
            card = cards.get(source_id)
            if card is None:
                card = {
                    "url": anchor["url"],
                    "titles": [],
                    "image_titles": [],
                    "poster": "",
                    "year": "",
                }
                cards[source_id] = card
                order.append(source_id)

            title = _extract_title(anchor["attrs"], anchor["inner"])
            if title:
                card["titles"].append(title)

            # Poster: first look inside the link, then at the nearest image.
            poster = _extract_poster(anchor["attrs"], anchor["inner"])
            if not poster:
                poster, alt = nearest_image(anchor["pos"])
                if alt:
                    card["image_titles"].append(_unescape(alt))
            if poster and not card["poster"]:
                card["poster"] = self._absolute(poster)

            if not card["year"]:
                card["year"] = _extract_year(anchor["inner"])

        results: List[StreamResult] = []
        for source_id in order:
            card = cards[source_id]
            title = _pick_title(card["titles"], card["image_titles"], source_id)
            results.append(
                StreamResult(
                    source_type=self.slug,
                    source_id=source_id,
                    title=title,
                    url=card["url"],
                    poster_url=card["poster"],
                    year=card["year"] or _extract_year(title),
                )
            )
        return results

    def parse_episode_links(self, html_text: str, show_url: str) -> List[StreamEpisode]:
        """Extract episode links from a show page."""
        episodes: List[StreamEpisode] = []
        seen: set = set()

        for attrs, inner in _iter_anchors(html_text):
            href = attrs.get("href", "")
            if not href:
                continue
            absolute = self._absolute(href)
            if absolute == show_url:
                continue

            ep_match = re.search(r"[?&]ep(?:isode)?=(\d+)", href, re.IGNORECASE)
            is_episode = bool(ep_match) or "/episode/" in href.lower()
            if not is_episode:
                continue

            number = int(ep_match.group(1)) if ep_match else 0
            if number == 0:
                number = _extract_episode_number(inner) or (len(episodes) + 1)

            if absolute in seen:
                continue
            seen.add(absolute)

            title = _extract_title(attrs, inner) or f"Episode {number}"
            episodes.append(
                StreamEpisode(title=title, url=absolute, number=number)
            )

        episodes.sort(key=lambda e: e.number)
        return episodes

    def resolve_stream_url(self, page_url: str) -> str:
        """Try to find a direct ``.m3u8``/``.mp4`` link inside an episode page."""
        page = self._get_text(page_url)
        if not page:
            return ""
        match = re.search(
            r"""['"](https?://[^'"\s\\]+?\.(?:m3u8|mp4)(?:\?[^'"\s\\]*)?)['"]""",
            page,
            re.IGNORECASE,
        )
        if match and not _PLAYER_ASSET_RE.search(match.group(1)):
            return match.group(1)
        return ""


class GenericStreamingProvider(BaseStreamingProvider):
    """Fallback provider using pure heuristics for unknown sites.

    Besides scraping HTML it probes a handful of common JSON search endpoints,
    which covers the many TMDB-backed Next.js streaming clones (``flixer`` and
    friends) that render every result client-side.
    """

    JSON_SEARCH_PATHS = ("/api/search", "/api/v1/search")

    def search(self, query: str) -> List[StreamResult]:
        results = super().search(query)
        if results:
            return results
        if self._request_failed:
            # The host is unreachable; do not probe JSON endpoints either.
            return []
        return self._search_json(query)

    def _search_json(self, query: str) -> List[StreamResult]:
        query = (query or "").strip()
        if not query or not self.base_url:
            return []
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.base_url}/search?q={quote_plus(query)}",
        }
        for path in self.JSON_SEARCH_PATHS:
            for param in ("query", "q"):
                payload = self._get_json(
                    self.base_url + path,
                    params={param: query, "page": 1},
                    headers=headers,
                )
                items = _json_item_list(payload)
                if items:
                    mapped = self._map_json_items(items)
                    if mapped:
                        return mapped
        return []

    def _map_json_items(self, items: List[Dict[str, Any]]) -> List[StreamResult]:
        results: List[StreamResult] = []
        for item in items:
            source_id = str(item.get("id") or item.get("tmdb_id") or "").strip()
            title = _first_nonempty(
                item.get("name"),
                item.get("title"),
                item.get("original_name"),
                item.get("original_title"),
            )
            if not source_id or not title:
                continue
            poster = _first_nonempty(
                item.get("poster_path"),
                item.get("poster"),
                item.get("cover"),
                item.get("image"),
            )
            if poster and not is_stream_url(poster):
                if poster.startswith("/"):
                    poster = "https://image.tmdb.org/t/p/w500" + poster
                else:
                    poster = self._absolute(poster)
            year = str(
                item.get("first_air_date")
                or item.get("release_date")
                or item.get("year")
                or ""
            )[:4]
            results.append(
                StreamResult(
                    source_type=self.slug,
                    source_id=source_id,
                    title=_unescape(title),
                    url=f"{self.base_url}/watch/{source_id}",
                    poster_url=poster,
                    year=year,
                    description=str(
                        item.get("overview") or item.get("description") or ""
                    ),
                )
            )
        return results[:MAX_RESULTS]


class OneTubeProvider(BaseStreamingProvider):
    """1Tube search provider (TMDB-backed Next.js site)."""

    SEARCH_PATH = "/search?q={query}"
    ITEM_PATTERNS = ("/watch/",)
    POSTER_BASE = "https://image.tmdb.org/t/p/w500"
    MAX_SEASONS = 30
    DISCOVER_TRENDING = "/api/discover/trending"

    def _json_headers(self, query: str = "") -> Dict[str, str]:
        referer = (
            f"{self.base_url}/search?q={quote_plus(query)}"
            if query
            else self.base_url + "/"
        )
        return {"Accept": "application/json, text/plain, */*", "Referer": referer}

    def _map_items(self, items: Iterable[Dict[str, Any]]) -> List[StreamResult]:
        results: List[StreamResult] = []
        for item in items:
            source_id = str(item.get("id") or "").strip()
            title = _first_nonempty(
                item.get("name"),
                item.get("title"),
                item.get("original_name"),
                item.get("original_title"),
            )
            if not source_id or not title:
                continue
            poster = item.get("poster_path") or ""
            if poster and not is_stream_url(poster):
                poster = (
                    self.POSTER_BASE + poster
                    if poster.startswith("/")
                    else self._absolute(poster)
                )
            year = str(item.get("first_air_date") or item.get("release_date") or "")[:4]
            results.append(
                StreamResult(
                    source_type=self.slug,
                    source_id=source_id,
                    title=_unescape(title),
                    url=f"{self.base_url}/watch/{source_id}",
                    poster_url=poster,
                    year=year,
                    description=str(item.get("overview") or ""),
                )
            )
        return results

    def search(self, query: str) -> List[StreamResult]:
        query = (query or "").strip()
        if not query or not self.base_url:
            return []
        payload = self._get_json(
            self.base_url + "/api/search",
            params={"query": query},
            headers=self._json_headers(query),
        )
        results = self._map_items(_json_item_list(payload))
        if results:
            return results[:MAX_RESULTS]
        return super().search(query)

    def fetch_recent(self, limit: int = RECENT_PAGE_SIZE,
                     page: int = 1) -> List[StreamResult]:
        if not self.base_url:
            return []
        payload = self._get_json(
            self.base_url + self.DISCOVER_TRENDING,
            params={"page": max(1, int(page or 1))},
            headers=self._json_headers(),
        )
        results = self._map_items(_json_item_list(payload))
        if results:
            return results[:limit]
        return super().fetch_recent(limit=limit, page=page)

    def fetch_episodes(self, result: StreamResult) -> List[StreamEpisode]:
        if not result.source_id:
            return super().fetch_episodes(result)

        episodes: List[StreamEpisode] = []
        for season in range(1, self.MAX_SEASONS + 1):
            payload = self._get_json(
                f"{self.base_url}/api/tv/{result.source_id}/season/{season}",
                headers=self._json_headers(),
            )
            if not isinstance(payload, dict):
                break
            items = payload.get("episodes") or []
            if not items:
                break
            for item in items:
                try:
                    number = int(
                        item.get("episode_number") or item.get("episode_num") or 0
                    )
                except (TypeError, ValueError):
                    number = 0
                if number <= 0:
                    continue
                title = _first_nonempty(
                    item.get("name"), item.get("title"), f"Episode {number}"
                )
                episodes.append(
                    StreamEpisode(
                        title=_unescape(title),
                        url=(
                            f"{self.base_url}/watch/{result.source_id}/"
                            f"{season}/{number}"
                        ),
                        number=number,
                        season_number=season,
                        season_name=f"Season {season}",
                    )
                )

        if episodes:
            episodes.sort(key=lambda episode: (episode.season_number, episode.number))
            return episodes
        # Movies have no season endpoint; expose the watch page as one entry.
        return [
            StreamEpisode(
                title=result.title or "Watch", url=result.url, number=1
            )
        ]


class AnimeIDHentaiProvider(BaseStreamingProvider):
    """AnimeIDHentai search provider.

    The site is a Next.js app whose search lives at ``/api/search?q=`` and
    returns ``{"videos": [...]}`` — one entry per *episode*, carrying its show's
    ``titleSlug``. Search results are therefore grouped by show, and a show's
    episode list is read from the embedded RSC payload of its ``/series/<slug>``
    page.
    """

    SEARCH_PATH = "/explore?q={query}"
    ITEM_PATTERNS = ("/series/",)
    RESULTS_LIMIT = 24
    EPISODE_WINDOW = 2200

    def _api_headers(self, query: str = "") -> Dict[str, str]:
        referer = f"{self.base_url}/explore"
        if query:
            referer = f"{referer}?q={quote_plus(query)}"
        return {"Accept": "application/json, text/plain, */*", "Referer": referer}

    def search(self, query: str) -> List[StreamResult]:
        query = (query or "").strip()
        if not query or not self.base_url:
            return []
        payload = self._get_json(
            self.base_url + "/api/search",
            params={"q": query, "limit": self.RESULTS_LIMIT},
            headers=self._api_headers(query),
        )
        videos = payload.get("videos") if isinstance(payload, dict) else None
        if not isinstance(videos, list):
            return super().search(query)

        results: List[StreamResult] = []
        seen: set = set()
        for item in videos:
            if not isinstance(item, dict):
                continue
            title_slug = str(item.get("titleSlug") or "").strip()
            if not title_slug or title_slug in seen:
                continue
            seen.add(title_slug)
            poster = _first_nonempty(
                item.get("cover"),
                item.get("featureImage"),
                item.get("thumb"),
                item.get("backdrop"),
            )
            if poster:
                poster = self._absolute(poster)
            title = _unescape(str(item.get("title") or "")) or title_slug
            results.append(
                StreamResult(
                    source_type=self.slug,
                    source_id=title_slug,
                    title=title,
                    url=f"{self.base_url}/series/{title_slug}",
                    poster_url=poster,
                    year=str(item.get("year") or "")[:4],
                    description=str(item.get("description") or ""),
                )
            )
        if results:
            return results[:MAX_RESULTS]
        return super().search(query)

    def fetch_recent(self, limit: int = RECENT_PAGE_SIZE,
                     page: int = 1) -> List[StreamResult]:
        if not self.base_url:
            return []
        page = max(1, int(page or 1))
        html_text = self._get_text(
            f"{self.base_url}/series?page={page}",
            referer=self.base_url + "/explore",
        )
        if not html_text:
            return super().fetch_recent(limit=limit, page=page)
        results = _dedupe_results(self.parse_search_results(html_text))
        if results:
            return results[:limit]
        return super().fetch_recent(limit=limit, page=page)

    def fetch_episodes(self, result: StreamResult) -> List[StreamEpisode]:
        slug = (result.source_id or "").strip()
        if not slug:
            return super().fetch_episodes(result)

        episodes = self._series_episodes(slug)
        if not episodes:
            episodes = self._search_episodes(slug, result.title)
        if episodes:
            episodes.sort(key=lambda episode: episode.number)
            return episodes
        return super().fetch_episodes(result)

    def _series_episodes(self, slug: str) -> List[StreamEpisode]:
        html_text = self._get_text(f"{self.base_url}/series/{slug}")
        if not html_text:
            return []
        raw = html_text.replace('\\"', '"')
        episodes: List[StreamEpisode] = []
        seen: set = set()
        previous_end = 0
        for match in re.finditer(r'"embedUrl"\s*:\s*"([^"]+)"', raw):
            chunk = raw[previous_end:match.start()][-self.EPISODE_WINDOW:]
            previous_end = match.end()
            if self._last_field(chunk, "titleSlug") != slug:
                continue
            episode_slug = self._last_field(chunk, "slug")
            number = self._to_int(self._last_field(chunk, "ep"))
            key = episode_slug or number
            if not key or key in seen:
                continue
            seen.add(key)
            label = self._last_field(chunk, "title")
            label = _unescape(label)
            title = f"{label} Episode {number}" if label and number else label
            episodes.append(
                StreamEpisode(
                    title=title or (f"Episode {number}" if number else "Episode"),
                    url=match.group(1),
                    number=number,
                    season_number=1,
                    season_name="Season 1",
                )
            )
        return episodes

    def _search_episodes(self, slug: str, title: str) -> List[StreamEpisode]:
        payload = self._get_json(
            self.base_url + "/api/search",
            params={"q": title or slug, "limit": 40},
            headers=self._api_headers(),
        )
        videos = payload.get("videos") if isinstance(payload, dict) else None
        if not isinstance(videos, list):
            return []
        episodes: List[StreamEpisode] = []
        seen: set = set()
        for item in videos:
            if not isinstance(item, dict):
                continue
            if str(item.get("titleSlug") or "") != slug:
                continue
            embed = str(item.get("embedUrl") or "").strip()
            if not embed or embed in seen:
                continue
            seen.add(embed)
            number = self._to_int(item.get("ep"))
            episodes.append(
                StreamEpisode(
                    title=(
                        f"Episode {number}"
                        if number
                        else _unescape(str(item.get("title") or "")) or "Episode"
                    ),
                    url=embed,
                    number=number,
                    season_number=1,
                    season_name="Season 1",
                )
            )
        return episodes

    @staticmethod
    def _last_field(chunk: str, name: str) -> str:
        quoted = re.compile(r'"%s"\s*:\s*"([^"]*)"' % re.escape(name))
        value = ""
        for match in quoted.finditer(chunk):
            value = match.group(1).strip()
        if value:
            return value
        plain = re.compile(r'"%s"\s*:\s*([^,}]+)' % re.escape(name))
        for match in plain.finditer(chunk):
            value = match.group(1).strip().strip('"')
        return value

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


class FlixbabaProvider(BaseStreamingProvider):
    """Flixbaba search provider (single-page app over a TMDB proxy).

    The site renders nothing server-side; it proxies TMDB through
    ``/api/tmdb/<endpoint>`` and images through ``/api/tmdb-img/<size><path>``.
    Playback uses a shared list of embed servers, the first of which is used
    here so every episode points at a specific season/episode.
    """

    SEARCH_PATH = "/search?q={query}"
    ITEM_PATTERNS = ("/details/",)
    IMAGE_BASE = "/api/tmdb-img/w500"
    MOVIE_EMBED = "https://player.cinezo.live/embed/movie/{id}"
    TV_EMBED = "https://player.cinezo.live/embed/tv/{id}/{season}/{episode}"
    MAX_SEASONS = 30
    TRENDING_PATH = "/trending/all/week"

    def _api_headers(self, query: str = "") -> Dict[str, str]:
        referer = f"{self.base_url}/search?q={quote_plus(query)}" if query else self.base_url + "/"
        return {"Accept": "application/json, text/plain, */*", "Referer": referer}

    def _proxy(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None, referer_query: str = ""
    ) -> Any:
        payload: Dict[str, Any] = {"language": "en-US"}
        payload.update(params or {})
        return self._get_json(
            self.base_url + "/api/tmdb" + endpoint,
            params=payload,
            headers=self._api_headers(referer_query),
        )

    def search(self, query: str) -> List[StreamResult]:
        query = (query or "").strip()
        if not query or not self.base_url:
            return []
        payload = self._proxy("/search/multi", {"query": query}, referer_query=query)
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            return super().search(query)

        mapped = self._map_items(results)
        if mapped:
            return mapped[:MAX_RESULTS]
        return super().search(query)

    def _map_items(self, results: Iterable[Dict[str, Any]]) -> List[StreamResult]:
        mapped: List[StreamResult] = []
        seen: set = set()
        for item in results:
            if not isinstance(item, dict):
                continue
            media_type = str(item.get("media_type") or "").strip()
            if media_type and media_type not in ("movie", "tv"):
                # Explicit non-title results (e.g. people) are not importable.
                continue
            if not media_type:
                # ``trending/all`` usually carries media_type, but TMDB omits
                # it for some rows; infer it from the shape of the payload.
                if item.get("name") or item.get("first_air_date"):
                    media_type = "tv"
                elif item.get("title") or item.get("release_date"):
                    media_type = "movie"
                else:
                    continue
            tmdb_id = str(item.get("id") or "").strip()
            if not tmdb_id or (media_type, tmdb_id) in seen:
                continue
            seen.add((media_type, tmdb_id))
            title = _first_nonempty(
                item.get("name"),
                item.get("title"),
                item.get("original_name"),
                item.get("original_title"),
            )
            if not title:
                continue
            poster = str(item.get("poster_path") or "").strip()
            if poster:
                poster = self.base_url + self.IMAGE_BASE + poster
            mapped.append(
                StreamResult(
                    source_type=self.slug,
                    source_id=f"{media_type}:{tmdb_id}",
                    title=_unescape(title),
                    url=f"{self.base_url}/details/{media_type}/{tmdb_id}",
                    poster_url=poster,
                    year=str(
                        item.get("first_air_date") or item.get("release_date") or ""
                    )[:4],
                    description=str(item.get("overview") or ""),
                )
            )
        return mapped

    def fetch_recent(self, limit: int = RECENT_PAGE_SIZE,
                     page: int = 1) -> List[StreamResult]:
        if not self.base_url:
            return []
        payload = self._proxy(
            self.TRENDING_PATH, {"page": max(1, int(page or 1))}
        )
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list) or not results:
            return super().fetch_recent(limit=limit, page=page)
        return self._map_items(results)[:limit]

    def fetch_episodes(self, result: StreamResult) -> List[StreamEpisode]:
        media_type, tmdb_id = self._split_source(result)
        if not tmdb_id:
            return super().fetch_episodes(result)
        if media_type == "movie":
            return [
                StreamEpisode(
                    title=result.title or "Watch Movie",
                    url=self.MOVIE_EMBED.format(id=tmdb_id),
                    number=1,
                )
            ]

        episodes: List[StreamEpisode] = []
        for season in range(1, self.MAX_SEASONS + 1):
            payload = self._proxy(
                f"/tv/{tmdb_id}/season/{season}", referer_query=result.title
            )
            items = payload.get("episodes") if isinstance(payload, dict) else None
            if not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                number = self._to_int(item.get("episode_number"))
                if number <= 0:
                    continue
                name = _first_nonempty(item.get("name"), f"Episode {number}")
                episodes.append(
                    StreamEpisode(
                        title=_unescape(name),
                        url=self.TV_EMBED.format(
                            id=tmdb_id, season=season, episode=number
                        ),
                        number=number,
                        season_number=season,
                        season_name=f"Season {season}",
                    )
                )
        if episodes:
            episodes.sort(key=lambda episode: (episode.season_number, episode.number))
            return episodes
        return [
            StreamEpisode(
                title=result.title or "Watch",
                url=f"{self.base_url}/play/{media_type}/{tmdb_id}",
                number=1,
            )
        ]

    @staticmethod
    def _split_source(result: StreamResult) -> Tuple[str, str]:
        source_id = (result.source_id or "").strip()
        if ":" in source_id:
            media_type, tmdb_id = source_id.split(":", 1)
            return media_type.strip().lower(), tmdb_id.strip()
        match = re.search(r"/(movie|tv)/([0-9]+)", result.url or "")
        if match:
            return match.group(1), match.group(2)
        return "", source_id

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


class ElisworldProvider(BaseStreamingProvider):
    """Elisworld search provider (WordPress site with client-rendered episodes).

    Search results are ordinary WordPress links (``/cartoons/<slug>/`` and
    ``/movies/<slug>/``), but a show's episode grid is built in JavaScript from
    the TMDB API. The page exposes its TMDB id, API key and season list, so we
    can rebuild the same episode links (``/watch/<slug>/s<season>e<episode>/``)
    without a browser.
    """

    SEARCH_PATH = "/?s={query}"
    ITEM_PATTERNS = ("/cartoons/", "/movies/")
    TMDB_SEASON_URL = "https://api.themoviedb.org/3/tv/{id}/season/{season}"

    def search(self, query: str) -> List[StreamResult]:
        query = (query or "").strip()
        if not query or not self.base_url:
            return []
        html_text = self._get_text(
            f"{self.base_url}/?s={quote_plus(query)}"
        )
        if not html_text:
            return []
        return self._parse_cards(html_text)[:MAX_RESULTS]

    def fetch_recent(self, limit: int = RECENT_PAGE_SIZE,
                     page: int = 1) -> List[StreamResult]:
        if not self.base_url:
            return []
        page = max(1, int(page or 1))
        url = (
            f"{self.base_url}/cartoons/"
            if page == 1
            else f"{self.base_url}/cartoons/page/{page}/"
        )
        html_text = self._get_text(url)
        if not html_text:
            return super().fetch_recent(limit=limit, page=page)
        results = self._parse_cards(html_text)
        if results:
            return results[:limit]
        return super().fetch_recent(limit=limit, page=page)

    def _parse_cards(self, html_text: str) -> List[StreamResult]:
        """Parse Elisworld's card markup (search, home and archive pages).

        Cards share the ``ew-cw-title`` heading and a ``show-card`` /
        ``ew-mv-card`` wrapper, while the wrapper class differs per page
        (``search-item``, ``homepage-item``, ``archive-item``).
        """
        results: List[StreamResult] = []
        seen: set = set()
        for match in re.finditer(r"<a\b([^>]*)>(.*?)</a>", html_text, re.S):
            attrs, inner = match.group(1), match.group(2)
            if not any(
                marker in attrs
                for marker in ("search-item", "show-card", "ew-mv-card")
            ):
                continue
            href_match = re.search(r'href="([^"]+)"', attrs)
            if not href_match:
                continue
            href = _unescape(href_match.group(1))
            show_url = urljoin(self.base_url + "/", href)
            path = urlparse(show_url).path
            if not re.match(r"^/(?:cartoons|movies)/[^/]+/?$", path):
                continue
            if not show_url.endswith("/"):
                show_url += "/"
            if show_url in seen:
                continue
            seen.add(show_url)
            title = self._inner_text(
                inner, r'class="ew-cw-title"[^>]*>(.*?)</div>'
            )
            if not title:
                title = self._inner_text(inner, r"<h[234][^>]*>(.*?)</h[234]>")
            if not title:
                continue
            poster_match = re.search(
                r'<img[^>]+(?:src|data-src)="([^"]+)"', inner
            )
            poster = ""
            if poster_match:
                poster = self._absolute(_unescape(poster_match.group(1)))
            else:
                bg_match = re.search(
                    r"background-image\s*:\s*url\(['\"]?([^'\")]+)", inner
                )
                if bg_match:
                    poster = self._absolute(_unescape(bg_match.group(1)))
            results.append(
                StreamResult(
                    source_type=self.slug,
                    source_id=path.strip("/"),
                    title=_unescape(title),
                    url=show_url,
                    poster_url=poster,
                )
            )
        return results

    def fetch_episodes(self, result: StreamResult) -> List[StreamEpisode]:
        if "/movies/" in (result.url or ""):
            return self._movie_episode(result)
        episodes = self._tv_episodes(result)
        if episodes:
            return episodes
        return super().fetch_episodes(result)

    def resolve_stream_url(self, page_url: str) -> str:
        """Keep the watch page.

        Elisworld's TV player is an iframe whose ``src`` is signed with a
        short-lived ``exp``/``sig`` pair, so caching it would break playback
        later. Opening the watch page lets the site mint a fresh URL.
        """
        return ""

    def _movie_episode(self, result: StreamResult) -> List[StreamEpisode]:
        html_text = self._get_text(result.url)
        if not html_text:
            return super().fetch_episodes(result)
        embed = ""
        for tag in re.finditer(r"<iframe\b[^>]*>", html_text, re.I):
            src = re.search(r'src="([^"]+)"', tag.group(0))
            if not src:
                continue
            candidate = _unescape(src.group(1))
            if "recaptcha" in candidate or "google.com" in candidate:
                continue
            embed = self._absolute(candidate)
            break
        return [
            StreamEpisode(
                title=result.title or "Watch Movie",
                url=embed or result.url,
                number=1,
            )
        ]

    def _tv_episodes(self, result: StreamResult) -> List[StreamEpisode]:
        html_text = self._get_text(result.url)
        if not html_text:
            return []
        id_match = re.search(r'const\s+id\s*=\s*"(\d+)"', html_text)
        slug_match = re.search(r'const\s+showSlug\s*=\s*"([^"]+)"', html_text)
        if not id_match or not slug_match:
            return []
        tmdb_id = id_match.group(1)
        show_slug = slug_match.group(1)
        key_match = re.search(r'const\s+apiKey\s*=\s*"([^"]*)"', html_text)
        api_key = key_match.group(1) if key_match else ""

        seasons_block = re.search(
            r'<select[^>]+id="season-select"[^>]*>(.*?)</select>',
            html_text,
            re.S,
        )
        seasons = (
            [int(value) for value in re.findall(r'<option value="(\d+)"', seasons_block.group(1))]
            if seasons_block
            else [1]
        )
        if not seasons:
            seasons = [1]

        episodes: List[StreamEpisode] = []
        for season in seasons:
            payload = self._get_json(
                self.TMDB_SEASON_URL.format(id=tmdb_id, season=season),
                params={"api_key": api_key} if api_key else None,
                headers={"Accept": "application/json"},
            )
            items = payload.get("episodes") if isinstance(payload, dict) else None
            if not items:
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                number = self._to_int(item.get("episode_number"))
                if number <= 0:
                    continue
                name = _first_nonempty(item.get("name"), f"Episode {number}")
                episodes.append(
                    StreamEpisode(
                        title=_unescape(name),
                        url=(
                            f"{self.base_url}/watch/{show_slug}/"
                            f"s{season}e{number}/"
                        ),
                        number=number,
                        season_number=season,
                        season_name=f"Season {season}",
                    )
                )
        episodes.sort(key=lambda episode: (episode.season_number, episode.number))
        return episodes

    @staticmethod
    def _inner_text(inner: str, pattern: str) -> str:
        match = re.search(pattern, inner, re.S)
        if not match:
            return ""
        text = re.sub(r"<[^>]+>", " ", match.group(1))
        return re.sub(r"\s+", " ", _unescape(text)).strip()

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


class HiAnimeProvider(BaseStreamingProvider):
    """HiAnime search and recent provider.

    HiAnime renders its landing page client-side, so the generic "parse the
    home page" strategy finds no shows. The site exposes each homepage section
    as a small AJAX fragment whose JSON payload contains ready-made card HTML;
    ``recent-added`` is the newest-shows feed.
    """

    SEARCH_PATH = "/search?keyword={query}"
    ITEM_PATTERNS = ("/watch/",)
    RECENT_PATHS = (
        "/ajax/v2/recent-added",
        "/ajax/v2/latest-episodes",
        "/ajax/v2/trending",
        "/ajax/v2/most-popular",
        "/ajax/v2/top-airing",
    )
    AJAX_HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    }

    def _ajax_fragment(self, path: str, page: int) -> str:
        """Return the card HTML from one HiAnime AJAX endpoint."""
        headers = dict(self.AJAX_HEADERS)
        headers["Referer"] = f"{self.base_url}/"
        payload = self._get_json(
            self.base_url + path, params={"page": page}, headers=headers
        )
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            for key in ("html", "data", "result"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
                if isinstance(value, dict):
                    nested = value.get("html")
                    if isinstance(nested, str):
                        return nested
        return ""

    def fetch_recent(self, limit: int = RECENT_PAGE_SIZE,
                     page: int = 1) -> List[StreamResult]:
        if not self.base_url or limit <= 0:
            return []
        page = max(1, int(page or 1))
        for path in self.RECENT_PATHS:
            fragment = self._ajax_fragment(path, page)
            if not fragment:
                continue
            results = _dedupe_results(self.parse_search_results(fragment))
            if results:
                return results[:limit]
        # Last resort: the generic landing-page scrape.
        return super().fetch_recent(limit=limit, page=page)


class MiruruProvider(BaseStreamingProvider):
    """Miruru search provider."""

    SEARCH_PATH = "/search?q={query}"
    ITEM_PATTERNS = ("/anime/", "/series/", "/watch/", "/show/", "/detail/")


class MManiProvider(BaseStreamingProvider):
    """MMani search provider.

    The site renders its results client-side from a JSON API whose endpoint is
    advertised in the page's ``AppConfig``/``KF`` script block. We discover
    that endpoint from the site root and query it directly.
    """

    SEARCH_PATH = "/search/?wd={query}"
    ITEM_PATTERNS = ("/up/",)
    API_FALLBACK = "https://eng.animeapps.top/api/search3.php"
    SINGLE_API_FALLBACK = "https://eng.animeapps.top/api/single.php"
    FILTER_API = "https://mmani.com/ajax.php?filter"
    EPISODES_API = "https://epeng.animeapps.top/api2.php"
    SOURCE_API = "https://epeng.animeapps.top/apilink.php"

    def __init__(self, base_url: str, slug: str = "mmani", name: str = "MMani"):
        super().__init__(base_url, slug=slug, name=name)
        self._kf_token: Optional[str] = None

    def _discover_endpoint(self, key: str, fallback: str) -> str:
        page = self._get_text(self.base_url + "/")
        for pattern in (
            rf'"{key}"\s*:\s*"(https?://[^"]+)"',
            rf'"{key}"\s*:\s*"([^"]+)"',
        ):
            match = re.search(pattern, page or "")
            if match:
                return self._absolute(match.group(1))
        return fallback

    def _discover_api(self) -> str:
        return self._discover_endpoint("search", f"{self.base_url}/ajax.php?search")

    def _get_kf_token(self) -> str:
        if self._kf_token:
            return self._kf_token
        page = self._get_text(self.base_url + "/")
        match = re.search(r'\}\)\(window\.fetch,\s*["\']([^"\']+)["\']\)', page or "")
        self._kf_token = match.group(1) if match else ""
        return self._kf_token

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": self.base_url + "/",
            "Origin": self.base_url,
            "X-Requested-With": "XMLHttpRequest",
        }
        token = self._get_kf_token()
        if token:
            headers["X-KF-Req"] = token
        return headers

    def _map_items(self, items: List[Dict[str, Any]],
                   limit: int = MAX_RESULTS) -> List[StreamResult]:
        results: List[StreamResult] = []
        for item in items:
            source_id = str(
                item.get("postid") or item.get("id") or item.get("slug") or ""
            ).strip()
            title = _first_nonempty(
                item.get("postname", ""),
                item.get("name", ""),
                item.get("post_title", ""),
                _object_title(item.get("title")),
            )
            if not source_id or not title:
                continue

            poster = _first_nonempty(
                item.get("ani_cover_large", ""),
                item.get("cover", ""),
                item.get("cover_url", ""),
                item.get("image", ""),
                item.get("poster", ""),
            )
            if poster and not is_stream_url(poster):
                # MMani stores a bare AniList cover path; the CDN prefix is
                # used by the site itself.
                poster = "https://rez1.ims1.top/350x/" + poster.lstrip("/")
            elif poster:
                poster = self._absolute(poster)

            year = str(item.get("postyear") or item.get("year") or "")
            results.append(
                StreamResult(
                    source_type=self.slug,
                    source_id=source_id,
                    title=_unescape(title),
                    url=f"{self.base_url}/up/{source_id}",
                    poster_url=poster,
                    year=year,
                    description=str(item.get("description") or ""),
                )
            )
        return results[:limit]

    def search(self, query: str) -> List[StreamResult]:
        query = (query or "").strip()
        if not query or not self.base_url:
            return []

        api = self._discover_api()
        for param in ("keyword", "q", "wd", "search"):
            payload = self._get_json(
                api,
                params={param: query, "page": 1, "limit": MAX_RESULTS},
                headers=self._headers(),
            )
            items = _json_item_list(payload)
            if items:
                return self._map_items(items)

        # Fallback to older API fallback
        for param in ("keyword", "q", "wd", "search"):
            payload = self._get_json(
                self.API_FALLBACK,
                params={param: query, "page": 1, "limit": MAX_RESULTS},
                headers=self._headers(),
            )
            items = _json_item_list(payload)
            if items:
                return self._map_items(items)

        # If the JSON API is unavailable, fall back to heuristic HTML parsing.
        return super().search(query)

    def fetch_recent(self, limit: int = RECENT_PAGE_SIZE,
                     page: int = 1) -> List[StreamResult]:
        if not self.base_url:
            return []
        filter_api = self._discover_endpoint("filter", f"{self.base_url}/ajax.php?filter")
        payload = self._get_json(
            filter_api,
            params={"page": max(1, int(page or 1)), "limit": limit},
            headers=self._headers(),
        )
        items = _json_item_list(payload)
        if items:
            return self._map_items(items, limit=limit)
        payload = self._get_json(
            self.FILTER_API,
            params={"page": max(1, int(page or 1)), "limit": limit},
            headers=self._headers(),
        )
        items = _json_item_list(payload)
        if items:
            return self._map_items(items, limit=limit)
        return super().fetch_recent(limit=limit, page=page)

    def _resolve_episode_link(self, link: str) -> str:
        """Turn MMani's opaque episode id into a direct HLS URL, if possible."""
        if not link:
            return ""
        source_api = self._discover_endpoint("eplink", self.SOURCE_API)
        sources = self._get_json(
            source_api, params={"data": link}, headers=self._headers()
        )
        if not isinstance(sources, list):
            sources = self._get_json(
                self.SOURCE_API, params={"data": link}, headers=self._headers()
            )
        if not isinstance(sources, list):
            return ""
        for source in sources:
            if not isinstance(source, dict):
                continue
            page_url = source.get("link") or ""
            if not page_url:
                continue
            page = self._get_text(page_url, referer=self.base_url + "/")
            match = re.search(
                r"""["']videoUrl["']\s*:\s*["']([^"']+)["']""", page or ""
            )
            if match:
                url = match.group(1)
                return url if is_stream_url(url) else urljoin(page_url, url)
            direct = re.search(
                r"""https?://[^'"\s\\]+?\.(?:m3u8|mp4)(?:\?[^'"\s\\]*)?""",
                page or "",
                re.IGNORECASE,
            )
            if direct:
                return direct.group(0)
        return ""

    def fetch_episodes(self, result: StreamResult) -> List[StreamEpisode]:
        if not result.source_id:
            return super().fetch_episodes(result)

        single_api = self._discover_endpoint("single", f"{self.base_url}/ajax.php?single")
        details = self._get_json(
            single_api,
            params={"postid": result.source_id},
            headers=self._headers(),
        )
        if not details:
            details = self._get_json(
                self.SINGLE_API_FALLBACK,
                params={"postid": result.source_id},
                headers=self._headers(),
            )
        show = details.get("data") if isinstance(details, dict) else None
        anilist_id = str((show or {}).get("anilist") or "").strip()
        if not anilist_id:
            return super().fetch_episodes(result)

        episodes_api = self._discover_endpoint("episodes", f"{self.base_url}/ajax.php?episodes")
        servers = self._get_json(
            episodes_api, params={"epid": anilist_id}, headers=self._headers()
        )
        if not isinstance(servers, list):
            servers = self._get_json(
                self.EPISODES_API, params={"epid": anilist_id}, headers=self._headers()
            )
        if not isinstance(servers, list):
            return super().fetch_episodes(result)

        server_id = ""
        entries: List[Dict[str, Any]] = []
        for server in servers:
            if isinstance(server, dict) and server.get("server_data"):
                server_id = str(server.get("id") or "")
                entries = server["server_data"]
                break
        if not entries:
            return super().fetch_episodes(result)

        episodes: List[StreamEpisode] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "")
            slug = str(entry.get("slug") or "")
            if not slug:
                continue

            number = int(name) if name.strip().isdigit() else _extract_episode_number(name)
            if number <= 0:
                number = len(episodes) + 1

            if server_id:
                watch_url = (
                    f"{self.base_url}/up/{result.source_id}/watch/"
                    f"?server={server_id}&slug={slug}"
                )
            else:
                watch_url = f"{self.base_url}/up/{result.source_id}/watch/?slug={slug}"
            url = watch_url
            if index < STREAM_RESOLVE_LIMIT:
                direct = self._resolve_episode_link(str(entry.get("link") or ""))
                if direct:
                    url = direct

            episodes.append(
                StreamEpisode(
                    title=name or f"Episode {number}",
                    url=url,
                    number=number,
                )
            )

        episodes.sort(key=lambda episode: episode.number)
        return episodes


# Miruro obfuscates ``application/octet-stream`` API responses with a repeating
# XOR key, then gzips the result.
MIRURO_XOR_KEY = b"miruro/catalog"


def _decode_miruro_payload(body: bytes) -> Any:
    """Decode Miruro's obfuscated (or plain) JSON API response."""
    if not body:
        return None
    try:
        raw = bytes(
            byte ^ MIRURO_XOR_KEY[index % len(MIRURO_XOR_KEY)]
            for index, byte in enumerate(body)
        )
        return json.loads(gzip.decompress(raw).decode("utf-8", "replace"))
    except Exception:
        pass
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return None


class MiruroProvider(BaseStreamingProvider):
    """Miruro search provider backed by its JSON catalog API."""

    SEARCH_PATH = "/search?query={query}"
    ITEM_PATTERNS = ("/info/", "/watch/")

    def __init__(self, base_url: str, slug: str = "", name: str = ""):
        super().__init__(base_url, slug=slug, name=name)
        # Miruro's canonical host is www.miruro.tv and its catalog API validates
        # the Origin/Referer headers, so normalise a bare ``miruro.tv``.
        parsed = urlparse(self.base_url)
        if parsed.netloc == "miruro.tv":
            self.base_url = self.base_url.replace("//miruro.tv", "//www.miruro.tv", 1)

    def _api_get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        referer: str = "",
    ) -> Any:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Cache-Control": "no-cache",
            "Referer": referer or (self.base_url + "/"),
            "Origin": self.base_url,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        url = self.base_url + path
        if params:
            url = f"{url}?{urlencode(params)}"

        # Cloudflare rejects Python's TLS fingerprint here but allows curl, so
        # prefer the system binary when it exists and fall back to requests.
        if _curl_available():
            return _decode_miruro_payload(_curl_fetch(url, headers))

        try:
            resp = self.session.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return None
            return _decode_miruro_payload(resp.content)
        except Exception:
            return None

    def search(self, query: str) -> List[StreamResult]:
        query = (query or "").strip()
        if not query or not self.base_url:
            return []

        payload = self._api_get(
            "/api/v1/anime",
            # Miruro's catalog rejects limits above 15 with a 400.
            {"q": query, "limit": min(MAX_RESULTS, 15)},
            referer=f"{self.base_url}/search?query={quote_plus(query)}",
        )
        items = _json_item_list(payload)
        if not items:
            return super().search(query)
        results = self._map_items(items)
        if results:
            return results[:MAX_RESULTS]
        return super().search(query)

    def _map_items(self, items: Iterable[Dict[str, Any]]) -> List[StreamResult]:
        results: List[StreamResult] = []
        for item in items:
            source_id = str(item.get("id") or "").strip()
            title = _first_nonempty(
                _object_title(item.get("title")),
                item.get("title_english", ""),
                item.get("title_romaji", ""),
            )
            if not source_id or not title:
                continue

            poster = _first_nonempty(
                item.get("cover_url", ""),
                item.get("cover", ""),
                item.get("poster", ""),
            )
            if poster:
                poster = self._absolute(poster)

            results.append(
                StreamResult(
                    source_type=self.slug,
                    source_id=source_id,
                    title=_unescape(title),
                    url=f"{self.base_url}/info/{source_id}",
                    poster_url=poster,
                    year=str(item.get("season_year") or item.get("year") or ""),
                    description=str(item.get("description") or ""),
                )
            )
        return results

    def fetch_recent(self, limit: int = RECENT_PAGE_SIZE,
                     page: int = 1) -> List[StreamResult]:
        if not self.base_url:
            return []
        page = max(1, int(page or 1))
        # The catalog is cursor-paginated. Walk cursors from the first page so
        # callers can ask for page N without having to persist cursor state.
        per_page = max(1, min(limit, 15))
        cursor = ""
        results: List[StreamResult] = []
        for index in range(page):
            params: Dict[str, Any] = {"limit": per_page}
            if cursor:
                params["cursor"] = cursor
            payload = self._api_get(
                "/api/v1/anime",
                params,
                referer=f"{self.base_url}/",
            )
            items = _json_item_list(payload)
            if not items:
                return []
            results = self._map_items(items)
            next_cursor = str((payload or {}).get("next_cursor") or "")
            if not next_cursor:
                # No more pages: only the last requested page is meaningful.
                return results[:limit] if index == page - 1 else []
            cursor = next_cursor
        return results[:limit]

    def fetch_episodes(self, result: StreamResult) -> List[StreamEpisode]:
        if not result.source_id:
            return super().fetch_episodes(result)

        payload = self._api_get(
            f"/api/v1/anime/{result.source_id}/episodes",
            referer=f"{self.base_url}/watch/{result.source_id}",
        )
        items = _json_item_list(payload)
        episodes: List[StreamEpisode] = []
        for item in items:
            try:
                number = int(item.get("episode_number") or item.get("number") or 0)
            except (TypeError, ValueError):
                number = 0
            if number <= 0:
                continue
            title = _first_nonempty(item.get("title", ""), f"Episode {number}")
            episodes.append(
                StreamEpisode(
                    title=_unescape(title),
                    url=f"{self.base_url}/watch/{result.source_id}?ep={number}",
                    number=number,
                )
            )
        episodes.sort(key=lambda episode: episode.number)
        if episodes:
            return episodes

        # The per-episode endpoint is not always exposed; fall back to the
        # show's episode count so the library still gets a usable episode list.
        detail = self._api_get(
            f"/api/v1/anime/{result.source_id}",
            referer=f"{self.base_url}/info/{result.source_id}",
        )
        if isinstance(detail, dict):
            try:
                count = int(detail.get("episode_count") or 0)
            except (TypeError, ValueError):
                count = 0
            if 0 < count <= 2000:
                return [
                    StreamEpisode(
                        title=f"Episode {number}",
                        url=f"{self.base_url}/watch/{result.source_id}?ep={number}",
                        number=number,
                    )
                    for number in range(1, count + 1)
                ]
        return super().fetch_episodes(result)



class HanimeProvider(BaseStreamingProvider):
    """Hanime provider backed by the guest catalog API."""

    CATALOG_API = "https://guest.freeanimehentai.net/api/v11/search_hvs"
    _catalog_cache: Optional[List[Dict[str, Any]]] = None
    _catalog_cache_time: float = 0.0
    _CACHE_TTL: float = 600.0  # 10 minutes

    @classmethod
    def _get_catalog(cls, session: Optional[requests.Session] = None) -> List[Dict[str, Any]]:
        now = time.time()
        if cls._catalog_cache is not None and (now - cls._catalog_cache_time) < cls._CACHE_TTL:
            return cls._catalog_cache
        try:
            client = session if session is not None else requests
            headers = dict(DEFAULT_HEADERS)
            headers["Accept"] = "application/json, text/plain, */*"
            resp = client.get(cls.CATALOG_API, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") if isinstance(data, dict) else data
                if isinstance(items, list) and items:
                    cls._catalog_cache = items
                    cls._catalog_cache_time = now
                    return items
        except Exception:
            pass
        return cls._catalog_cache or []

    def _item_to_result(self, item: Dict[str, Any]) -> Optional[StreamResult]:
        slug = str(item.get("slug") or "").strip()
        name = str(item.get("name") or "").strip()
        if not slug or not name:
            return None
        poster = item.get("cover_url") or item.get("poster_url") or ""
        created = str(item.get("created_at") or "")
        year = created[:4] if len(created) >= 4 and created[:4].isdigit() else ""
        desc = item.get("description") or ""
        if desc:
            desc = _TAG_RE.sub(" ", desc).strip()
        base = self.base_url or "https://hanime.tv"
        return StreamResult(
            source_type=self.slug,
            source_id=slug,
            title=_unescape(name),
            url=f"{base}/videos/hentai/{slug}",
            poster_url=poster,
            year=year,
            description=desc,
        )

    def search(self, query: str) -> List[StreamResult]:
        query = (query or "").strip()
        if not query:
            return []
        catalog = self._get_catalog(self.session)
        if not catalog:
            return super().search(query)

        tokens = [t.lower() for t in query.split() if t.strip()]
        scored: List[Tuple[float, Dict[str, Any]]] = []
        q_lower = query.lower()

        for item in catalog:
            name = (item.get("name") or "").lower()
            slug = (item.get("slug") or "").lower()
            search_titles = (item.get("search_titles") or "").lower()
            brand = (item.get("brand") or "").lower()
            tags = " ".join(item.get("tags") or []).lower() if isinstance(item.get("tags"), list) else ""
            haystack = f"{name} {slug} {search_titles} {brand} {tags}"

            if all(t in haystack for t in tokens):
                score = 0.0
                if q_lower == name:
                    score += 50.0
                elif name.startswith(q_lower):
                    score += 30.0
                elif q_lower in name:
                    score += 15.0
                if q_lower in slug:
                    score += 10.0
                views = item.get("views") or 0
                if isinstance(views, (int, float)):
                    score += min(views / 100000.0, 20.0)
                scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: List[StreamResult] = []
        for _, item in scored[:MAX_RESULTS]:
            res = self._item_to_result(item)
            if res:
                results.append(res)
        return results

    def fetch_recent(self, limit: int = RECENT_PAGE_SIZE, page: int = 1) -> List[StreamResult]:
        catalog = self._get_catalog(self.session)
        if not catalog:
            return super().fetch_recent(limit=limit, page=page)
        by_date = sorted(
            catalog,
            key=lambda x: x.get("created_at_unix") or x.get("released_at_unix") or 0,
            reverse=True,
        )
        offset = max(0, (page - 1) * limit)
        page_items = by_date[offset : offset + limit]
        results: List[StreamResult] = []
        for item in page_items:
            res = self._item_to_result(item)
            if res:
                results.append(res)
        return results

    def fetch_episodes(self, result: StreamResult) -> List[StreamEpisode]:
        base = self.base_url or "https://hanime.tv"
        return [
            StreamEpisode(
                title=result.title or "Watch",
                url=result.url or f"{base}/videos/hentai/{result.source_id}",
                number=1,
            )
        ]


class HentaiHavenProvider(BaseStreamingProvider):
    """HentaiHaven search provider backed by the CMS REST API."""

    CMS_API = "https://cms.hentaihaven.xxx"
    IMG_CDN = "https://img.hentaihaven.xxx/"

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
        }
        if self.base_url:
            headers["Referer"] = self.base_url + "/"
            headers["Origin"] = self.base_url
        return headers

    def _item_to_result(self, item: Dict[str, Any]) -> Optional[StreamResult]:
        slug = str(item.get("slug") or "").strip()
        title_obj = item.get("title")
        if isinstance(title_obj, dict):
            title = title_obj.get("rendered") or ""
        else:
            title = str(title_obj or "")
        title = title.strip()
        if not slug or not title:
            return None

        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        poster = (
            meta.get("vraven_remote_thumbnail")
            or item.get("thumbnail_url")
            or item.get("thumbnail")
            or ""
        )
        if poster and not is_stream_url(poster):
            poster = urljoin(self.IMG_CDN, poster.lstrip("/"))

        date_str = str(item.get("date") or "")
        year = date_str[:4] if len(date_str) >= 4 and date_str[:4].isdigit() else ""

        desc_obj = item.get("content")
        desc = ""
        if isinstance(desc_obj, dict):
            desc = desc_obj.get("rendered") or ""
        elif isinstance(desc_obj, str):
            desc = desc_obj
        if desc:
            desc = _TAG_RE.sub(" ", desc).strip()

        base = self.base_url or "https://hentaihaven.xxx"
        return StreamResult(
            source_type=self.slug,
            source_id=slug,
            title=_unescape(title),
            url=f"{base}/watch/{slug}/",
            poster_url=poster,
            year=year,
            description=desc,
        )

    def search(self, query: str) -> List[StreamResult]:
        query = (query or "").strip()
        if not query:
            return []

        url = f"{self.CMS_API}/wp-json/wp/v2/wp-manga"
        payload = self._get_json(
            url,
            params={"search": query, "per_page": MAX_RESULTS},
            headers=self._headers(),
        )
        if isinstance(payload, list) and payload:
            results: List[StreamResult] = []
            for item in payload:
                if isinstance(item, dict):
                    res = self._item_to_result(item)
                    if res:
                        results.append(res)
            if results:
                return results

        return super().search(query)

    def fetch_recent(self, limit: int = RECENT_PAGE_SIZE, page: int = 1) -> List[StreamResult]:
        url = f"{self.CMS_API}/wp-json/wp/v2/wp-manga"
        payload = self._get_json(
            url,
            params={
                "per_page": limit,
                "page": max(1, int(page or 1)),
                "orderby": "date",
                "order": "desc",
            },
            headers=self._headers(),
        )
        if isinstance(payload, list) and payload:
            results: List[StreamResult] = []
            for item in payload:
                if isinstance(item, dict):
                    res = self._item_to_result(item)
                    if res:
                        results.append(res)
            if results:
                return results

        if page == 1:
            trend = self._get_json(
                f"{self.CMS_API}/wp-json/hhaven/v1/catalog/trending",
                headers=self._headers(),
            )
            if isinstance(trend, dict) and isinstance(trend.get("items"), list):
                results = []
                for item in trend["items"]:
                    if isinstance(item, dict):
                        res = self._item_to_result(item)
                        if res:
                            results.append(res)
                if results:
                    return results[:limit]

        return super().fetch_recent(limit=limit, page=page)

    def fetch_episodes(self, result: StreamResult) -> List[StreamEpisode]:
        if not result.source_id:
            return super().fetch_episodes(result)

        chapters_url = f"{self.CMS_API}/wp-json/hhaven/v1/manga/by-slug/{result.source_id}/chapters"
        payload = self._get_json(chapters_url, headers=self._headers())
        base = self.base_url or "https://hentaihaven.xxx"
        if isinstance(payload, list) and payload:
            episodes: List[StreamEpisode] = []
            for index, chap in enumerate(payload):
                if not isinstance(chap, dict):
                    continue
                name = str(chap.get("chapter_name") or chap.get("episode_slug") or "").strip()
                ep_slug = str(chap.get("episode_slug") or chap.get("chapter_slug") or "").strip()
                number = _extract_episode_number(name)
                if number <= 0:
                    number = index + 1
                stream_url = str(chap.get("indexable_content_url") or "")
                if not stream_url or not is_stream_url(stream_url):
                    stream_url = (
                        f"{base}/watch/{result.source_id}/{ep_slug}/"
                        if ep_slug
                        else f"{base}/watch/{result.source_id}/"
                    )
                episodes.append(
                    StreamEpisode(
                        title=name or f"Episode {number}",
                        url=stream_url,
                        number=number,
                    )
                )
            if episodes:
                episodes.sort(key=lambda ep: ep.number)
                return episodes

        return [
            StreamEpisode(
                title=result.title or "Watch",
                url=result.url or f"{base}/watch/{result.source_id}/",
                number=1,
            )
        ]


_PROVIDER_BY_SLUG = {
    "1tube": OneTubeProvider,
    "animeidhentai": AnimeIDHentaiProvider,
    "elisworld": ElisworldProvider,
    "flixbaba": FlixbabaProvider,
    "hanime": HanimeProvider,
    "hentaihaven": HentaiHavenProvider,
    "hentaiheaven": HentaiHavenProvider,
    "hianime": HiAnimeProvider,
    "mmani": MManiProvider,
    "miruro": MiruroProvider,
    "miruru": MiruruProvider,
    "onetube": OneTubeProvider,
}


def provider_for_site(site: Dict[str, Any]) -> BaseStreamingProvider:
    """Build the best provider for a configured streaming site."""
    base_url = site.get("base_url") or ""
    slug = (site.get("source_type") or site_slug(base_url)).lower()
    name = site.get("name") or ""
    provider_cls = _PROVIDER_BY_SLUG.get(slug)
    if not provider_cls:
        host = urlparse(base_url).netloc.lower() if "://" in base_url else base_url.lower()
        for key, cls in _PROVIDER_BY_SLUG.items():
            if key in slug or key in host or key in name.lower():
                provider_cls = cls
                break
    if not provider_cls:
        provider_cls = GenericStreamingProvider
    return provider_cls(base_url, slug=slug, name=name)


# ---------------------------------------------------------------------------
# Remote image helpers
# ---------------------------------------------------------------------------
# Poster images are only ever needed for display while browsing, so they are
# fetched into memory and thrown away with the results. Nothing is written to
# disk unless the show is actually added to the library.
MAX_IMAGE_BYTES = 12 * 1024 * 1024  # 12 MB safety cap


def fetch_remote_image_bytes(
    image_url: str,
    timeout: int = 10,
    referer: str = "",
    session: Optional[requests.Session] = None,
) -> Optional[bytes]:
    """Download raw image bytes for temporary, display-only use.

    Returns ``None`` when the URL is empty, the request fails, or the payload
    is unreasonably large. Callers are expected to keep the bytes in memory
    (e.g. for a ``QPixmap``) rather than saving them to disk.

    ``referer`` (usually the streaming site's base URL) is sent along because
    many poster CDNs reject hotlink requests that lack it. Passing a shared
    ``session`` lets a batch of posters reuse connections, which is much faster
    than a fresh TCP/TLS handshake per image.
    """
    if not image_url:
        return None
    headers = dict(DEFAULT_HEADERS)
    headers.update(IMAGE_HEADERS)
    if referer:
        headers["Referer"] = referer
    client = session if session is not None else requests
    try:
        resp = client.get(image_url, headers=headers, timeout=timeout)
        if resp.status_code == 200 and resp.content and len(resp.content) <= MAX_IMAGE_BYTES:
            return resp.content
    except Exception:
        pass
    return None


def cache_remote_image(db: Database, image_url: str, prefix: str = "stream", referer: str = "") -> str:
    """Download a remote image into Nook's managed covers cache.

    Used when a show is *added* to the library (the artwork should stick
    around). Returns the local path, or an empty string when it fails.
    """
    data = fetch_remote_image_bytes(image_url, referer=referer)
    if not data:
        return ""
    try:
        return db.save_cover_image(data, prefix=prefix)
    except Exception:
        return ""



# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------
_ANCHOR_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*("([^"]*)"|'([^']*)')""")
_IMG_RE = re.compile(r"<img\b([^>]*)>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_BG_IMAGE_RE = re.compile(r"background-image\s*:\s*url\(\s*['\"]?([^'\")]+)", re.IGNORECASE)
_YEAR_RE = re.compile(r"(19|20)\d{2}")
# Any element carrying a lazy-loaded image URL (not just ``<img>`` tags).
_LAZY_ATTR_RE = re.compile(
    r"""(?:data-src|data-original|data-lazy-src|data-lazy|data-echo|data-setbg|data-bg|data-image)"""
    r"""\s*=\s*("([^"]*)"|'([^']*)')""",
    re.IGNORECASE,
)


def _parse_attrs(raw: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for match in _ATTR_RE.finditer(raw or ""):
        value = match.group(3) if match.group(3) is not None else match.group(4)
        attrs[match.group(1).lower()] = value or ""
    return attrs


def _iter_anchors(html_text: str) -> Iterable[tuple]:
    for match in _ANCHOR_RE.finditer(html_text or ""):
        yield _parse_attrs(match.group(1)), match.group(2)


def _first_nonempty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = value if isinstance(value, str) else str(value)
        if text.strip():
            return text.strip()
    return ""


def _object_title(value: Any) -> str:
    """Return a display title from a string or an ``{english, romaji, native}`` dict."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _first_nonempty(
            value.get("english"), value.get("romaji"), value.get("native")
        )
    return ""


def _json_item_list(payload: Any) -> List[Dict[str, Any]]:
    """Extract a list of item dicts from common JSON response shapes."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in (
            "data",
            "results",
            "items",
            "videos",
            "anime",
            "list",
            "response",
            "records",
            "entries",
        ):
            value = payload.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return [item for item in value if isinstance(item, dict)]
    return []


def _dedupe_results(results: Iterable[StreamResult]) -> List[StreamResult]:
    """Keep the first occurrence of each source id (or URL for id-less rows)."""
    seen = set()
    unique: List[StreamResult] = []
    for result in results:
        key = (
            result.source_type,
            result.source_id,
        ) if result.source_id else result.url
        if key in seen:
            continue
        seen.add(key)
        unique.append(result)
    return unique


# Image attributes that commonly hold the *real* poster on lazy-loading sites.
_POSTER_ATTRS = (
    "data-src",
    "data-original",
    "data-lazy-src",
    "data-lazy",
    "data-echo",
    "data-setbg",
    "data-bg",
    "data-image",
    "data-img",
    "data-poster",
    "data-thumb",
    "data-url",
    "data-original-src",
)

# Substrings that mark a placeholder/tracking pixel rather than real artwork.
_PLACEHOLDER_HINTS = ("data:image", "blank.gif", "spacer.gif", "pixel.gif", "1x1.")


def _poster_from_img_attrs(attrs: Dict[str, str]) -> str:
    """Pull a usable poster URL out of an ``<img>`` tag's attributes."""
    if not attrs:
        return ""
    srcset = attrs.get("srcset", "") or attrs.get("data-srcset", "")
    srcset_first = ""
    if srcset:
        # srcset entries look like "url 1x, url2 2x" - take the first URL.
        srcset_first = srcset.split(",")[0].strip().split(" ")[0]

    poster = _first_nonempty(
        *[attrs.get(name, "") for name in _POSTER_ATTRS],
        srcset_first,
        attrs.get("src", ""),
    )
    if not poster:
        return ""
    if not _is_usable_image_url(poster):
        return ""
    return poster


def _extract_poster(attrs: Dict[str, str], inner: str) -> str:
    # Poster may live in a ``data-*`` attribute on the anchor itself.
    poster = _first_nonempty(*[attrs.get(name, "") for name in _POSTER_ATTRS])
    if poster:
        return poster

    bg_match = _BG_IMAGE_RE.search(inner or "")
    if bg_match:
        return bg_match.group(1)

    img_match = _IMG_RE.search(inner or "")
    if img_match:
        return _poster_from_img_attrs(_parse_attrs(img_match.group(1)))
    return ""


def _is_usable_image_url(url: str) -> bool:
    if not url or not url.strip():
        return False
    lowered = url.lower()
    return not any(hint in lowered for hint in _PLACEHOLDER_HINTS)


def _iter_document_images(text: str) -> List[tuple]:
    """Return ``(position, url, alt)`` for every plausible poster in a page.

    Covers ``<img>`` tags (including lazy ``data-src``), lazy image URLs on any
    other element (e.g. ``data-setbg`` on a ``<div>``), and CSS
    ``background-image`` declarations. Positions let callers match a poster to
    the card it visually belongs to.
    """
    images: List[tuple] = []

    for match in _IMG_RE.finditer(text or ""):
        attrs = _parse_attrs(match.group(1))
        url = _poster_from_img_attrs(attrs)
        if url:
            alt = _first_nonempty(attrs.get("alt", ""), attrs.get("title", ""))
            images.append((match.start(), url, _unescape(alt)))

    for match in _LAZY_ATTR_RE.finditer(text or ""):
        url = (match.group(2) if match.group(2) is not None else match.group(3)) or ""
        if _is_usable_image_url(url):
            images.append((match.start(), url.strip(), ""))

    for match in _BG_IMAGE_RE.finditer(text or ""):
        url = match.group(1).strip()
        if _is_usable_image_url(url):
            images.append((match.start(), url, ""))

    images.sort(key=lambda item: item[0])
    return images


def _extract_title(attrs: Dict[str, str], inner: str) -> str:
    title = _first_nonempty(attrs.get("title", ""), attrs.get("data-title", ""))
    if title:
        return _unescape(title)

    img_match = _IMG_RE.search(inner or "")
    if img_match:
        img_attrs = _parse_attrs(img_match.group(1))
        alt = _first_nonempty(img_attrs.get("alt", ""), img_attrs.get("title", ""))
        if alt:
            return _unescape(alt)

    text = _TAG_RE.sub(" ", inner or "")
    return _unescape(re.sub(r"\s+", " ", text).strip())


def _pick_title(link_titles: List[str], image_titles: List[str], source_id: str) -> str:
    """Choose the most useful title for a card.

    Titles extracted from the show link itself are trusted ahead of an image's
    ``alt`` text, and a bare URL slug is only used as a last resort.
    """
    slug_default = source_id.replace("-", " ").title()
    for candidate in list(link_titles) + list(image_titles):
        text = (candidate or "").strip()
        if not text or text.isdigit():
            continue
        if text.lower() == slug_default.lower():
            continue
        return text
    return slug_default


def _extract_episode_number(text: str) -> int:
    match = re.search(r"(?:episode|ep\.?|e)\s*0*(\d{1,4})", text or "", re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 0


def _extract_year(text: str) -> str:
    match = _YEAR_RE.search(text or "")
    return match.group(0) if match else ""


def _unescape(text: str) -> str:
    import html as _html

    return _html.unescape(text or "").strip()
