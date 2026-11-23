"""Where papers come from: OpenAlex and arXiv, through their public APIs.

* **OpenAlex** (api.openalex.org) indexes most journals, conferences, books and
  theses in every field and language. It works without a key; a free key
  (``LRG_OPENALEX_API_KEY`` or the settings dialog) gives a larger daily
  budget.
* **arXiv** (export.arxiv.org) has preprints in physics, mathematics,
  computer science and related fields, often before they are published.

Both return records in the same shape (see ``Library``). Requests are spaced
out process-wide (OpenAlex asks for no more than a few per second, arXiv for
one every three seconds) and errors become ``SearchError`` with a message the
model can act on. Only the standard library is used.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable

OPENALEX_WORKS = "https://api.openalex.org/works"
ARXIV_QUERY = "https://export.arxiv.org/api/query"
USER_AGENT = (
    "literature-review-generator/1.0 (+https://github.com/unscttp/Literature-Review-Generator)"
)
TIMEOUT_SECONDS = 30
MAX_AUTHORS = 25
OPENALEX_FIELDS = (
    "id,doi,display_name,publication_year,authorships,primary_location,type,biblio,"
    "cited_by_count,abstract_inverted_index,language"
)
OPENALEX_SORTS = {
    "relevance": None,
    "cited": "cited_by_count:desc",
    "recent": "publication_date:desc",
}
ARXIV_SORTS = {"relevance": "relevance", "recent": "submittedDate"}
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
QUOTA_PAUSE_SECONDS = 3600
MAX_RETRY_AFTER_SECONDS = 10

Fetch = Callable[[str, dict], bytes]


class SearchError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str = "", retry_after=None):
        super().__init__(message)
        self.status = status
        self.body = body
        self.retry_after = retry_after


class Pacer:
    """Keeps a minimum interval between requests to one service, across threads."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.lock = threading.Lock()
        self.last = 0.0
        self.paused_until: dict[str, tuple[float, str]] = {}

    def wait(self) -> None:
        with self.lock:
            delay = self.last + self.interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self.last = time.monotonic()


OPENALEX_PACER = Pacer(0.25)
ARXIV_PACER = Pacer(3.0)


def http_get(url: str, params: dict, secret: str = "") -> bytes:
    """GET ``url`` with ``params``; errors never contain ``secret``."""
    full = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        if secret:
            body = body.replace(secret, "[key]")
        try:
            retry_after = float(exc.headers.get("Retry-After", ""))
        except (TypeError, ValueError):
            retry_after = None
        raise SearchError(
            f"HTTP {exc.code}: {' '.join(body.split())[:200]}",
            status=exc.code,
            body=body[:1000],
            retry_after=retry_after,
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise SearchError(f"Could not reach the service ({reason}).") from None


# -- OpenAlex --------------------------------------------------------------------


def _abstract(inverted: dict | None) -> str:
    """OpenAlex stores abstracts as word -> positions; rebuild the text."""
    if not inverted:
        return ""
    words = sorted((pos, word) for word, positions in inverted.items() for pos in positions)
    return " ".join(word for _, word in words)


def _openalex_type(work: dict) -> str:
    kind = work.get("type") or ""
    source = ((work.get("primary_location") or {}).get("source") or {}).get("type") or ""
    if kind in ("book", "book-chapter", "dissertation", "preprint", "dataset"):
        return kind
    if kind in ("article", "review", "letter", "editorial"):
        if source == "conference":
            return "proceedings-article"
        if source == "repository":
            return "preprint"
        return "journal-article"
    return kind or "other"


def openalex_record(work: dict) -> dict:
    authors = [
        ((a.get("author") or {}).get("display_name") or "").strip()
        for a in work.get("authorships") or []
    ]
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    biblio = work.get("biblio") or {}
    first, last = biblio.get("first_page"), biblio.get("last_page")
    pages = f"{first}-{last}" if first and last and first != last else (first or None)
    doi = work.get("doi") or None
    if doi:
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return {
        "title": " ".join((work.get("display_name") or "").split()),
        "authors": [a for a in authors if a][:MAX_AUTHORS],
        "year": work.get("publication_year"),
        "venue": source.get("display_name"),
        "publisher": source.get("host_organization_name"),
        "type": _openalex_type(work),
        "volume": biblio.get("volume"),
        "issue": biblio.get("issue"),
        "pages": pages,
        "doi": doi,
        "url": f"https://doi.org/{doi}"
        if doi
        else location.get("landing_page_url") or work.get("id"),
        "abstract": _abstract(work.get("abstract_inverted_index")),
        "cited_by": work.get("cited_by_count"),
        "language": work.get("language"),
        "openalex_id": (work.get("id") or "").rsplit("/", 1)[-1] or None,
        "source": "openalex",
    }


def openalex_search(
    query: str,
    *,
    max_results: int = 15,
    from_year: int | None = None,
    to_year: int | None = None,
    sort: str = "relevance",
    language: str | None = None,
    api_key: str | None = None,
    fetch: Fetch | None = None,
) -> list[dict]:
    fetch = fetch or (lambda url, params: http_get(url, params, api_key or ""))
    budget = "key" if api_key else "shared"
    until, message = OPENALEX_PACER.paused_until.get(budget, (0.0, ""))
    if time.monotonic() < until:
        raise SearchError(message)
    params: dict = {"search": query, "per-page": max_results, "select": OPENALEX_FIELDS}
    filters = []
    if from_year:
        filters.append(f"from_publication_date:{from_year}-01-01")
    if to_year:
        filters.append(f"to_publication_date:{to_year}-12-31")
    if language:
        filters.append(f"language:{language}")
    if filters:
        params["filter"] = ",".join(filters)
    if OPENALEX_SORTS.get(sort):
        params["sort"] = OPENALEX_SORTS[sort]
    if api_key:
        params["api_key"] = api_key
    for attempt in range(2):
        OPENALEX_PACER.wait()
        try:
            data = json.loads(fetch(OPENALEX_WORKS, params))
            break
        except SearchError as exc:
            if exc.status != 429:
                raise SearchError(f"OpenAlex search failed: {exc}") from None
            body = exc.body.lower()
            if "budget" in body or "daily" in body or "limit exceeded" in body:
                fix = (
                    "the OpenAlex key's daily budget is used up"
                    if api_key
                    else "the shared daily budget is used up; add a free OpenAlex API key "
                    "in the settings (openalex.org) for a larger one"
                )
                message = (
                    f"OpenAlex refused the request: {fix}. Do not call it again in this "
                    "run; continue with arXiv or the papers found so far."
                )
                OPENALEX_PACER.paused_until[budget] = (
                    time.monotonic() + QUOTA_PAUSE_SECONDS,
                    message,
                )
                raise SearchError(message) from None
            if attempt == 1:
                raise SearchError(
                    "OpenAlex is limiting requests (HTTP 429); wait and retry later."
                ) from None
            time.sleep(min(exc.retry_after or 2.0, MAX_RETRY_AFTER_SECONDS))
        except ValueError:
            raise SearchError("OpenAlex did not return JSON.") from None
    return [openalex_record(work) for work in data.get("results") or []]


# -- arXiv -----------------------------------------------------------------------

_FIELD_QUERY = re.compile(r"\b(ti|au|abs|co|jr|cat|rn|all):|\b(AND|OR|ANDNOT)\b")


def arxiv_query(query: str, category: str | None = None) -> str:
    """Plain keywords become ``all:`` terms joined with AND; quoted phrases stay
    phrases; queries already in arXiv syntax are passed on."""
    query = query.strip()
    if not _FIELD_QUERY.search(query):
        parts = re.findall(r'"[^"]+"|\S+', query)
        query = " AND ".join(f"all:{part}" for part in parts)
    if category:
        query = f"({query}) AND cat:{category}"
    return query


def _text(element, path: str) -> str:
    found = element.find(path, ATOM)
    return " ".join((found.text or "").split()) if found is not None else ""


def arxiv_records(xml: bytes) -> list[dict]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise SearchError("arXiv did not return a valid feed.") from None
    records = []
    for entry in root.findall("a:entry", ATOM):
        abs_url = _text(entry, "a:id")
        match = re.search(r"arxiv\.org/abs/([^v]+?)(v\d+)?$", abs_url)
        if not match:
            continue  # an error entry
        arxiv_id = match.group(1)
        doi = _text(entry, "arxiv:doi") or None
        journal = _text(entry, "arxiv:journal_ref") or None
        published = _text(entry, "a:published")
        category = entry.find("arxiv:primary_category", ATOM)
        records.append(
            {
                "title": _text(entry, "a:title"),
                "authors": [_text(author, "a:name") for author in entry.findall("a:author", ATOM)][
                    :MAX_AUTHORS
                ],
                "year": int(published[:4]) if published[:4].isdigit() else None,
                "venue": journal or "arXiv",
                "publisher": None,
                "type": "journal-article" if journal else "preprint",
                "volume": None,
                "issue": None,
                "pages": None,
                "doi": doi,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "abstract": _text(entry, "a:summary"),
                "cited_by": None,
                "language": "en",
                "arxiv_id": arxiv_id,
                "category": category.get("term") if category is not None else None,
                "source": "arxiv",
            }
        )
    return records


def arxiv_search(
    query: str,
    *,
    max_results: int = 15,
    sort: str = "relevance",
    category: str | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    fetch: Fetch | None = None,
) -> list[dict]:
    fetch = fetch or http_get
    params = {
        "search_query": arxiv_query(query, category),
        "start": 0,
        "max_results": max_results,
        "sortBy": ARXIV_SORTS.get(sort, "relevance"),
        "sortOrder": "descending",
    }
    ARXIV_PACER.wait()
    try:
        records = arxiv_records(fetch(ARXIV_QUERY, params))
    except SearchError as exc:
        if exc.status in (429, 503):
            raise SearchError(
                "arXiv is busy (rate limited); wait a moment before retrying."
            ) from None
        raise SearchError(f"arXiv search failed: {exc}") from None
    return [
        record
        for record in records
        if record["year"] is None
        or (
            (not from_year or record["year"] >= from_year)
            and (not to_year or record["year"] <= to_year)
        )
    ]
