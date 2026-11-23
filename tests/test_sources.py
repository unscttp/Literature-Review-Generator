"""OpenAlex and arXiv responses become library records; errors become messages."""

import json
import unittest
from unittest.mock import patch

from tests.support import ROOT  # noqa: F401
from lrg import sources
from lrg.sources import SearchError, arxiv_query, arxiv_search, openalex_search

WORK = {
    "id": "https://openalex.org/W1",
    "doi": "https://doi.org/10.1/ABC",
    "display_name": "Irony   and Voice",
    "publication_year": 2019,
    "type": "article",
    "authorships": [{"author": {"display_name": "Jane Smith"}}, {"author": {"display_name": ""}}],
    "primary_location": {
        "source": {
            "display_name": "Studies in the Novel",
            "type": "journal",
            "host_organization_name": "JHU Press",
        }
    },
    "biblio": {"volume": "51", "issue": "2", "first_page": "100", "last_page": "120"},
    "cited_by_count": 7,
    "abstract_inverted_index": {"Irony": [0], "matters.": [1]},
    "language": "en",
}
FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v2</id>
    <published>2023-01-01T00:00:00Z</published>
    <title>Detecting
      Irony</title>
    <summary>A corpus method.</summary>
    <author><name>Ada Lovelace</name></author>
    <arxiv:primary_category term="cs.CL"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/1999.00002v1</id>
    <published>1999-05-01T00:00:00Z</published>
    <title>Old</title><summary>x</summary>
    <arxiv:journal_ref>J. Old 1 (1999)</arxiv:journal_ref>
    <arxiv:doi>10.2/old</arxiv:doi>
  </entry>
</feed>"""


class SourceTests(unittest.TestCase):
    def setUp(self):
        for pacer in (sources.OPENALEX_PACER, sources.ARXIV_PACER):
            pacer.interval = 0
            pacer.paused_until.clear()

    def test_openalex_record(self):
        seen = {}

        def fetch(url, params):
            seen.update(params)
            return json.dumps({"results": [WORK]}).encode()

        [record] = openalex_search(
            "irony", from_year=2000, language="en", sort="cited", api_key="k", fetch=fetch
        )
        self.assertEqual(seen["filter"], "from_publication_date:2000-01-01,language:en")
        self.assertEqual((seen["sort"], seen["api_key"]), ("cited_by_count:desc", "k"))
        self.assertEqual(record["title"], "Irony and Voice")
        self.assertEqual(record["authors"], ["Jane Smith"])
        self.assertEqual((record["doi"], record["url"]), ("10.1/ABC", "https://doi.org/10.1/ABC"))
        self.assertEqual((record["pages"], record["type"]), ("100-120", "journal-article"))
        self.assertEqual(record["abstract"], "Irony matters.")
        work = dict(WORK, primary_location={"source": {"type": "repository"}})
        self.assertEqual(sources.openalex_record(work)["type"], "preprint")

    def test_openalex_budget_pauses_the_source(self):
        calls = []

        def fetch(url, params):
            calls.append(1)
            raise SearchError("HTTP 429", status=429, body="Insufficient budget for today")

        with self.assertRaises(SearchError) as caught:
            openalex_search("irony", fetch=fetch)
        self.assertIn("settings", str(caught.exception))
        with self.assertRaises(SearchError):
            openalex_search("irony", fetch=fetch)
        self.assertEqual(len(calls), 1)  # paused: not asked again

    def test_openalex_rate_limit_retries_once(self):
        replies = [
            SearchError("HTTP 429", status=429, body="slow", retry_after=0),
            json.dumps({"results": []}).encode(),
        ]

        def fetch(url, params):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        with patch("time.sleep"):
            self.assertEqual(openalex_search("irony", fetch=fetch), [])

    def test_arxiv(self):
        self.assertEqual(arxiv_query('irony "free indirect"'), 'all:irony AND all:"free indirect"')
        self.assertEqual(
            arxiv_query("ti:irony AND au:smith", "cs.CL"), "(ti:irony AND au:smith) AND cat:cs.CL"
        )
        records = arxiv_search("irony", fetch=lambda url, params: FEED)
        self.assertEqual([r["arxiv_id"] for r in records], ["2301.00001", "1999.00002"])
        self.assertEqual((records[0]["title"], records[0]["type"]), ("Detecting Irony", "preprint"))
        self.assertEqual((records[1]["type"], records[1]["doi"]), ("journal-article", "10.2/old"))
        self.assertEqual(len(arxiv_search("irony", from_year=2000, fetch=lambda u, p: FEED)), 1)
        with self.assertRaises(SearchError):
            arxiv_search("irony", fetch=lambda u, p: b"<not xml")

    def test_errors_hide_the_key(self):
        import io
        import urllib.error

        error = urllib.error.HTTPError("u", 403, "no", {}, io.BytesIO(b"bad key SECRET"))
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(SearchError) as caught:
                sources.http_get("https://x", {}, "SECRET")
        self.assertNotIn("SECRET", str(caught.exception) + caught.exception.body)


if __name__ == "__main__":
    unittest.main()
