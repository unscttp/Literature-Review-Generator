"""Citations and reference lists from library records.

The model cites papers by their library id, ``[P12]`` or ``[P3, P7]``. When the
report is built these markers are replaced by in-text citations in the chosen
style and the reference list is generated from the records:

* ``apa``: APA 7th edition, author-date: (Austen & Brontë, 2001);
* ``gbt7714``: GB/T 7714-2015, numeric in order of first citation: [1], [2-4];
* ``mla``: MLA 9th edition, author: (Austen et al.).

Records come from OpenAlex and arXiv metadata, which is good but not perfect
(missing issue numbers, capitalisation as the publisher entered it). The
output follows the styles' rules for the fields that exist; check it before
submitting.
"""

from __future__ import annotations

import re
import unicodedata

STYLES = ("apa", "gbt7714", "mla")
CITATION = re.compile(r"[\[【]\s*(P\d+(?:\s*[,;，；、]\s*P\d+)*)\s*[\]】]")
CJK = re.compile(r"[㐀-鿿豈-﫿]")
PARTICLES = {"van", "von", "de", "der", "den", "da", "di", "du", "del", "della", "le", "la", "ter"}
HEADINGS = {
    ("apa", "en"): "References",
    ("gbt7714", "en"): "References",
    ("mla", "en"): "Works Cited",
    ("apa", "zh-CN"): "参考文献",
    ("gbt7714", "zh-CN"): "参考文献",
    ("mla", "zh-CN"): "引用文献",
}


def cited_ids(text: str) -> list[str]:
    """Paper ids cited in ``text``, in order of first appearance."""
    seen: list[str] = []
    for match in CITATION.finditer(text or ""):
        for paper_id in re.split(r"[,;，；、]", match.group(1)):
            paper_id = paper_id.strip()
            if paper_id not in seen:
                seen.append(paper_id)
    return seen


# -- names -------------------------------------------------------------------------


def split_name(name: str) -> tuple[str, str]:
    """(family, given). CJK names and single words are all family name."""
    name = " ".join((name or "").replace(",", " , ").split()).strip()
    if not name:
        return "", ""
    if CJK.search(name):
        return name.replace(" ", ""), ""
    if " , " in name:  # "Austen , Jane" (already family first)
        family, given = name.split(" , ", 1)
        return family.strip(), given.replace(" , ", " ").strip()
    parts = name.split()
    if len(parts) == 1:
        return parts[0], ""
    family = [parts[-1]]
    given = parts[:-1]
    while given and given[-1].lower() in PARTICLES:
        family.insert(0, given.pop())
    return " ".join(family), " ".join(given)


def initials(given: str, dots: bool = True) -> str:
    letters = []
    for part in re.split(r"\s+", given.strip()):
        if not part:
            continue
        pieces = [p for p in part.split("-") if p]
        joined = "-".join(p[0].upper() + ("." if dots else "") for p in pieces if p[0].isalpha())
        if joined:
            letters.append(joined)
    return " ".join(letters) if dots else "".join(letters)


def is_cjk(paper: dict) -> bool:
    authors = paper.get("authors") or []
    return bool(CJK.search(" ".join(authors[:1]) or paper.get("title", "")))


def _families(paper: dict) -> list[str]:
    return [split_name(a)[0] for a in paper.get("authors") or [] if split_name(a)[0]]


def _year(paper: dict) -> str:
    return str(paper["year"]) if paper.get("year") else "n.d."


def _doi_url(paper: dict) -> str:
    if paper.get("doi"):
        return f"https://doi.org/{paper['doi']}"
    return paper.get("url") or ""


def _end(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".?!。？！" else text + "."


# -- APA 7 -------------------------------------------------------------------------


def _apa_author(name: str) -> str:
    family, given = split_name(name)
    return f"{family}, {initials(given)}" if given else family


def apa_authors(paper: dict) -> str:
    names = [_apa_author(a) for a in paper.get("authors") or []]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if is_cjk(paper):
        return ", ".join(names[:20]) + (" 等" if len(names) > 20 else "")
    if len(names) > 20:
        return ", ".join(names[:19]) + ", . . . " + names[-1]
    return ", ".join(names[:-1]) + ", & " + names[-1]


def apa_label(paper: dict) -> str:
    families = _families(paper)
    cjk = is_cjk(paper)
    if not families:
        title = paper.get("title", "")
        return f'"{title[:40]}"' if not cjk else f"《{title[:20]}》"
    if len(families) == 1:
        return families[0]
    if len(families) == 2:
        return f"{families[0]}、{families[1]}" if cjk else f"{families[0]} & {families[1]}"
    return f"{families[0]}等" if cjk else f"{families[0]} et al."


def apa_reference(paper: dict, year: str) -> str:
    authors = apa_authors(paper)
    title = (paper.get("title") or "").strip()
    venue = paper.get("venue") or ""
    kind = paper.get("type")
    head = (
        f"{_end(authors) if is_cjk(paper) else authors} ({year}). "
        if authors
        else f"{title} ({year}). "
    )
    title_part = "" if not authors else title
    link = _doi_url(paper)
    if kind in ("book", "dissertation"):
        text = head + (f"*{_end(title_part)[:-1]}*" if title_part else "")
        if kind == "dissertation":
            text += " [Doctoral dissertation]"
        text = _end(text)
        if paper.get("publisher") or venue:
            text += f" {_end(paper.get('publisher') or venue)}"
    elif kind == "preprint":
        text = head + _end(f"{title_part} [Preprint]" if title_part else "[Preprint]")
        text += f" {_end(venue or 'arXiv')}"
    elif kind in ("proceedings-article", "book-chapter"):
        text = head + (_end(title_part) if title_part else "")
        if venue:
            pages = f" (pp. {paper['pages']})" if paper.get("pages") else ""
            text += f" In *{venue}*{pages}."
    else:
        text = head + (_end(title_part) if title_part else "")
        if venue:
            text += f" *{venue}*"
            if paper.get("volume"):
                text += f", *{paper['volume']}*"
                if paper.get("issue"):
                    text += f"({paper['issue']})"
            if paper.get("pages"):
                text += f", {paper['pages']}"
            text += "."
    if link:
        text += f" {link}"
    return " ".join(text.split())


# -- GB/T 7714-2015 ------------------------------------------------------------------

GBT_TYPES = {
    "journal-article": "J",
    "proceedings-article": "C",
    "book": "M",
    "book-chapter": "M",
    "dissertation": "D",
    "dataset": "DS",
}


def _gbt_author(name: str) -> str:
    family, given = split_name(name)
    if not given:
        return family
    return f"{family.upper()} {initials(given, dots=False)}"


def gbt_reference(paper: dict) -> str:
    authors = [_gbt_author(a) for a in paper.get("authors") or []]
    cjk = is_cjk(paper)
    if len(authors) > 3:
        authors = authors[:3] + ["等" if cjk else "et al"]
    text = ", ".join(authors)
    text = _end(text) + " " if text else ""
    kind = paper.get("type")
    code = GBT_TYPES.get(kind, "EB/OL")
    title = (paper.get("title") or "").strip().rstrip(".")
    venue = paper.get("venue") or ""
    year = str(paper.get("year") or "")
    text += f"{title}[{code}]"
    if code == "J":
        text += f". {venue}" if venue else ""
        text += f", {year}" if year else ""
        if paper.get("volume"):
            text += f", {paper['volume']}"
            if paper.get("issue"):
                text += f"({paper['issue']})"
        if paper.get("pages"):
            text += f": {paper['pages']}"
    elif code == "C":
        text = text.replace("[C]", "[C]//" + venue) if venue else text
        text += f", {year}" if year else ""
        if paper.get("pages"):
            text += f": {paper['pages']}"
    elif code in ("M", "D"):
        if kind == "book-chapter" and venue:
            text += f"//{venue}"
        place = paper.get("publisher") or (venue if kind != "book-chapter" else "")
        text += f". {place}" if place else ""
        text += f", {year}" if year else ""
        if paper.get("pages"):
            text += f": {paper['pages']}"
    else:
        text += f". {venue}" if venue else ""
        text += f", {year}" if year else ""
        if paper.get("url") and not paper.get("doi"):
            text += f". {paper['url']}"
    text = _end(text)
    if paper.get("doi"):
        text += f" DOI:{paper['doi']}."
    return " ".join(text.split())


def gbt_marker(numbers: list[int]) -> str:
    """[1], [1, 2], [2-4]: three or more consecutive numbers become a range."""
    numbers = sorted(set(numbers))
    groups, start = [], None
    for index, number in enumerate(numbers):
        if start is None:
            start = number
        if index + 1 == len(numbers) or numbers[index + 1] != number + 1:
            if number - start >= 2:
                groups.append(f"{start}-{number}")
            else:
                groups.extend(str(n) for n in range(start, number + 1))
            start = None
    return "[" + ", ".join(groups) + "]"


# -- MLA 9 ---------------------------------------------------------------------------


def mla_authors(paper: dict) -> str:
    names = paper.get("authors") or []
    if not names:
        return ""
    family, given = split_name(names[0])
    first = f"{family}, {given}" if given else family
    if len(names) == 1:
        return first
    if len(names) == 2:
        return f"{first}, {names[1]}" if is_cjk(paper) else f"{first}, and {names[1]}"
    return f"{first}, 等" if is_cjk(paper) else f"{first}, et al"


def mla_label(paper: dict) -> str:
    families = _families(paper)
    if not families:
        return f'"{(paper.get("title") or "")[:40]}"'
    if len(families) == 1:
        return families[0]
    if len(families) == 2:
        joiner = "、" if is_cjk(paper) else " and "
        return f"{families[0]}{joiner}{families[1]}"
    return f"{families[0]}等" if is_cjk(paper) else f"{families[0]} et al."


def mla_reference(paper: dict) -> str:
    authors = mla_authors(paper)
    text = _end(authors) + " " if authors else ""
    title = (paper.get("title") or "").strip()
    kind = paper.get("type")
    venue = paper.get("venue") or ""
    if kind in ("book", "dissertation"):
        text += f"*{title.rstrip('.')}*. "
        if paper.get("publisher"):
            text += f"{paper['publisher']}, "
    else:
        text += f'"{_end(title)}" '
        if venue:
            text += f"*{venue}*, "
        if paper.get("volume"):
            text += f"vol. {paper['volume']}, "
        if paper.get("issue"):
            text += f"no. {paper['issue']}, "
    if paper.get("year"):
        text += f"{paper['year']}, "
    if paper.get("pages"):
        pages = str(paper["pages"])
        text += f"{'pp.' if '-' in pages else 'p.'} {pages}, "
    text = text.rstrip(", ").rstrip() + "."
    link = _doi_url(paper)
    if link:
        text += f" {link.removeprefix('https://')}."
    return " ".join(text.split())


# -- whole documents ------------------------------------------------------------------


def _sort_key(paper: dict) -> tuple:
    families = _families(paper)
    first = families[0] if families else paper.get("title", "")
    plain = unicodedata.normalize("NFKD", first).encode("ascii", "ignore").decode().lower()
    return (plain or first, paper.get("year") or 0, paper.get("title", ""))


class Citations:
    """Replaces ``[P..]`` markers in text and lists the cited papers.

    Feed every section through ``render`` in document order, then call
    ``reference_list``. Unknown ids are kept visibly as ``[P99?]``.
    """

    def __init__(self, papers: dict[str, dict], style: str) -> None:
        if style not in STYLES:
            raise ValueError(f"style must be one of {STYLES}.")
        self.papers = papers
        self.style = style
        self.order: list[str] = []
        self.years: dict[str, str] = {}
        if style == "apa":
            self._disambiguate()

    def _disambiguate(self) -> None:
        """APA: two works with the same authors and year get 2020a and 2020b."""
        groups: dict[tuple, list[dict]] = {}
        for paper in self.papers.values():
            groups.setdefault((apa_label(paper), _year(paper)), []).append(paper)
        for (_, year), group in groups.items():
            group.sort(key=lambda p: p.get("title", ""))
            for index, paper in enumerate(group):
                suffix = "abcdefghijklmnopqrstuvwxyz"[index] if len(group) > 1 else ""
                self.years[paper["id"]] = year + ("-" if year == "n.d." and suffix else "") + suffix

    def _marker(self, ids: list[str]) -> str:
        known = [i for i in ids if i in self.papers]
        unknown = [f"{i}?" for i in ids if i not in self.papers]
        for paper_id in known:
            if paper_id not in self.order:
                self.order.append(paper_id)
        parts = []
        if known:
            if self.style == "gbt7714":
                parts.append(gbt_marker([self.order.index(i) + 1 for i in known]))
            elif self.style == "apa":
                inner = "; ".join(f"{apa_label(self.papers[i])}, {self.years[i]}" for i in known)
                parts.append(f"({inner})")
            else:
                parts.append("(" + "; ".join(mla_label(self.papers[i]) for i in known) + ")")
        if unknown:
            parts.append("[" + ", ".join(unknown) + "]")
        return " ".join(parts)

    def render(self, text: str) -> str:
        def replace(match):
            ids = [part.strip() for part in re.split(r"[,;，；、]", match.group(1))]
            return self._marker(ids)

        return CITATION.sub(replace, text or "")

    def reference_list(self) -> list[str]:
        cited = [self.papers[i] for i in self.order]
        if self.style == "gbt7714":
            return [f"[{n}] {gbt_reference(p)}" for n, p in enumerate(cited, 1)]
        cited.sort(key=_sort_key)
        if self.style == "apa":
            return [apa_reference(p, self.years[p["id"]]) for p in cited]
        return [mla_reference(p) for p in cited]


def heading(style: str, language: str) -> str:
    return HEADINGS.get((style, language), HEADINGS[(style, "en")])


# -- BibTeX ----------------------------------------------------------------------------

BIBTEX_TYPES = {
    "journal-article": "article",
    "proceedings-article": "inproceedings",
    "book": "book",
    "book-chapter": "incollection",
    "dissertation": "phdthesis",
}


def _bib_escape(value: str) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("{", "\\{").replace("}", "\\}")


def bibtex(papers: list[dict]) -> str:
    entries, keys = [], set()
    for paper in papers:
        families = _families(paper)
        base = unicodedata.normalize("NFKD", families[0] if families else "anon")
        base = re.sub(r"[^A-Za-z]", "", base.encode("ascii", "ignore").decode()) or "ref"
        word = next((w for w in re.findall(r"[A-Za-z]{4,}", paper.get("title", ""))), "").lower()
        key = f"{base.lower()}{paper.get('year') or ''}{word}"
        candidate, n = key, 2
        while candidate in keys:
            candidate, n = f"{key}{n}", n + 1
        keys.add(candidate)
        kind = BIBTEX_TYPES.get(paper.get("type"), "misc")
        fields = {
            "title": paper.get("title"),
            "author": " and ".join(paper.get("authors") or []),
            "year": paper.get("year"),
            "volume": paper.get("volume"),
            "number": paper.get("issue"),
            "pages": (paper.get("pages") or "").replace("-", "--") or None,
            "doi": paper.get("doi"),
            "url": paper.get("url"),
            "publisher": paper.get("publisher"),
        }
        venue_field = {
            "article": "journal",
            "inproceedings": "booktitle",
            "incollection": "booktitle",
            "phdthesis": "school",
        }.get(kind, "howpublished")
        fields[venue_field] = paper.get("venue")
        if paper.get("arxiv_id"):
            fields.update(eprint=paper["arxiv_id"], archiveprefix="arXiv")
        body = ",\n".join(
            f"  {name} = {{{_bib_escape(value)}}}" for name, value in fields.items() if value
        )
        entries.append(f"@{kind}{{{candidate},\n{body}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")
