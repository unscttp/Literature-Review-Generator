"""Citation styles, reference lists and BibTeX."""

import unittest

from tests.support import ROOT  # noqa: F401  (sets up the path)
from lrg.references import (
    Citations,
    apa_reference,
    bibtex,
    cited_ids,
    gbt_marker,
    gbt_reference,
    mla_reference,
    split_name,
)

ARTICLE = {
    "id": "P1",
    "title": "Irony and Voice",
    "authors": ["Jane Q. Smith", "Ludwig van Beethoven", "Wei Zhang"],
    "year": 2019,
    "venue": "Studies in the Novel",
    "type": "journal-article",
    "volume": "51",
    "issue": "2",
    "pages": "100-120",
    "doi": "10.1/abc",
}
CHINESE = {
    "id": "P2",
    "title": "奥斯丁小说中的反讽",
    "authors": ["王小明", "李华", "张三", "赵四"],
    "year": 2021,
    "venue": "外国文学研究",
    "type": "journal-article",
    "volume": "43",
    "issue": "1",
    "pages": "1-10",
}
PREPRINT = {
    "id": "P3",
    "title": "Detecting Irony",
    "authors": ["Ada Lovelace"],
    "year": 2023,
    "venue": "arXiv",
    "type": "preprint",
    "arxiv_id": "2301.00001",
    "url": "https://arxiv.org/abs/2301.00001",
}


class ReferenceTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(split_name("Ludwig van Beethoven"), ("van Beethoven", "Ludwig"))
        self.assertEqual(split_name("Smith, Jane"), ("Smith", "Jane"))
        self.assertEqual(split_name("王小明"), ("王小明", ""))
        self.assertEqual(split_name("Plato"), ("Plato", ""))

    def test_cited_ids(self):
        text = "As shown [P3, P1] and 【P2，P1】 and [P3; P4]; not [x] or [P]."
        self.assertEqual(cited_ids(text), ["P3", "P1", "P2", "P4"])

    def test_apa(self):
        self.assertEqual(
            apa_reference(ARTICLE, "2019"),
            "Smith, J. Q., van Beethoven, L., & Zhang, W. (2019). Irony and Voice. "
            "*Studies in the Novel*, *51*(2), 100-120. https://doi.org/10.1/abc",
        )
        self.assertTrue(
            apa_reference(CHINESE, "2021").startswith("王小明, 李华, 张三, 赵四. (2021).")
        )
        self.assertIn("[Preprint]. arXiv.", apa_reference(PREPRINT, "2023"))

    def test_gbt7714(self):
        self.assertEqual(
            gbt_reference(ARTICLE),
            "SMITH JQ, VAN BEETHOVEN L, ZHANG W. Irony and Voice[J]. Studies in the Novel, "
            "2019, 51(2): 100-120. DOI:10.1/abc.",
        )
        self.assertTrue(
            gbt_reference(CHINESE).startswith("王小明, 李华, 张三, 等. 奥斯丁小说中的反讽[J].")
        )
        self.assertIn("[EB/OL]", gbt_reference(PREPRINT))
        self.assertEqual(gbt_marker([1, 2]), "[1, 2]")
        self.assertEqual(gbt_marker([3, 1, 2, 5]), "[1-3, 5]")

    def test_mla(self):
        self.assertEqual(
            mla_reference(ARTICLE),
            'Smith, Jane Q., et al. "Irony and Voice." *Studies in the Novel*, vol. 51, no. 2, '
            "2019, pp. 100-120. doi.org/10.1/abc.",
        )

    def test_citations_in_text(self):
        papers = {p["id"]: p for p in (ARTICLE, CHINESE, PREPRINT)}
        numeric = Citations(papers, "gbt7714")
        self.assertEqual(numeric.render("A [P2]. B [P1, P2]. C [P9]."), "A [1]. B [1, 2]. C [P9?].")
        self.assertEqual([r[:3] for r in numeric.reference_list()], ["[1]", "[2]"])
        apa = Citations(papers, "apa")
        self.assertEqual(apa.render("[P1; P3]"), "(Smith et al., 2019; Lovelace, 2023)")
        self.assertEqual(apa.render("[P2]"), "(王小明等, 2021)")
        mla = Citations(papers, "mla")
        self.assertEqual(mla.render("[P3]"), "(Lovelace)")

    def test_apa_same_author_and_year(self):
        a = {**PREPRINT, "id": "P1", "title": "A first"}
        b = {**PREPRINT, "id": "P2", "title": "B second"}
        citations = Citations({"P1": a, "P2": b}, "apa")
        self.assertEqual(citations.render("[P2, P1]"), "(Lovelace, 2023b; Lovelace, 2023a)")

    def test_bibtex(self):
        text = bibtex([ARTICLE, PREPRINT, {**ARTICLE, "id": "P9", "title": "Irony {braces}"}])
        self.assertIn("@article{smith2019irony,", text)
        self.assertIn("@misc{lovelace2023detecting,", text)
        self.assertIn("eprint = {2301.00001}", text)
        self.assertIn("@article{smith2019irony2,", text)
        self.assertIn("Irony \\{braces\\}", text)
        self.assertIn("pages = {100--120}", text)


if __name__ == "__main__":
    unittest.main()
