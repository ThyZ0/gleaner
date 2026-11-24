"""A made-up report edited in several copies, with a known history, checked end to end."""
import os
import zipfile

import pytest

from gleaner import core
from gleaner.extract import extract

A = "The wind tunnel tests were carried out at three different speeds to measure the lift of the wing profile."
B = "Our results show that the lift coefficient grows linearly with the angle of attack until the stall point."
B2 = "Our results show that the lift coefficient grows almost linearly with the angle of attack until the stall point near fifteen degrees."
C = "A short paragraph about the measurement uncertainty of the balance used during the whole campaign of tests."
D = "We then compared these measurements with the values predicted by thin airfoil theory and found good agreement."
E = "In conclusion the profile behaves as expected and the method can be reused for the next semester projects."
P = "Note from the teacher review: the Reynolds number must be stated explicitly for every configuration tested here."
OTHER = ["Recipe for a lemon tart with a crisp pastry and a soft curd that sets overnight in the fridge.",
         "Mix the butter, the flour and a pinch of salt until it looks like sand, then add one egg yolk.", A]


def docx(path, paras, modified):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f"<w:body>{body}</w:body></w:document>")
        z.writestr("docProps/core.xml",
                   '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   'xmlns:dcterms="http://purl.org/dc/terms/">'
                   f"<dcterms:modified>{modified}</dcterms:modified></cp:coreProperties>")


@pytest.fixture
def story(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "cache_path", lambda: str(tmp_path / "cache.json"))
    d = tmp_path / "docs"
    (d / "old").mkdir(parents=True)
    docx(d / "old" / "report.docx", [A, B, C], "2025-01-01T10:00:00Z")
    docx(d / "report_teacher.docx", [A, B, C, P], "2025-01-02T10:00:00Z")      # side copy
    docx(d / "report_v2.docx", ["Title", A, B2, C, D], "2025-01-03T10:00:00Z")  # main line
    docx(d / "report_final.docx", [A, B2, D, E], "2025-01-04T10:00:00Z")        # C deleted on purpose
    # same text as the final, other format, paragraphs cut differently: an export, not a version
    (d / "report_final.md").write_text(f"{A} {B2}\n\n{D}\n\n{E}\n", encoding="utf-8")
    docx(d / "tart.docx", OTHER, "2025-01-02T12:00:00Z")                        # shares one paragraph only
    return d


def test_extract_reads_docx_paragraphs_and_metadata_time(story):
    paras, t, src = extract(str(story / "report_teacher.docx"))
    assert paras == [A, B, C, P]
    assert src == "document"
    assert t == pytest.approx(1735812000)


def test_family_story(story):
    docs, problems = core.scan([str(story)])
    assert not problems
    fams = core.families(docs)
    assert len(fams) == 1, "the tart recipe shares one paragraph only and must stay out"
    r = core.report(fams[0])
    names = [[os.path.basename(f["path"]) for f in v["files"]] for v in r["versions"]]
    assert names[0] == ["report.docx"]
    assert sorted(names[-1]) == ["report_final.docx", "report_final.md"], "export merged with its source"
    assert r["versions"][-1]["files"][0]["ext"] in (".docx", ".md")
    head = r["versions"][r["head"]]
    assert head["is_head"] and head["n"] == len(r["versions"]) - 1

    parents = {names[v["n"]][0]: v["parent"] for v in r["versions"]}
    assert parents["report_teacher.docx"] == 0
    assert parents["report_v2.docx"] == 0, "v2 descends from the original, not from the teacher's copy"

    assert [s["text"] for s in r["stranded"]] == [P]
    assert r["stranded"][0]["after"] == B, "anchored on the paragraph before it that the head still has"
    assert [s["text"] for s in r["removed"]] == [C]


def test_choosing_another_head_changes_what_is_missing(story):
    docs, _ = core.scan([str(story)])
    fam = core.families(docs)[0]
    teacher = next(d for d in fam if d.path.endswith("report_teacher.docx"))
    r = core.report(fam, head_id=teacher.id)
    texts = {s["text"] for s in r["stranded"] + r["removed"]}
    assert D in texts and E in texts and P not in texts


def test_cache_reuses_unchanged_files(story, monkeypatch):
    core.scan([str(story)])
    calls = []
    monkeypatch.setattr(core, "extract", lambda p: calls.append(p) or ([], 0, "file"))
    docs, _ = core.scan([str(story)])
    assert calls == [] and len(docs) == 6


def test_broken_file_is_reported_not_fatal(story):
    (story / "broken.docx").write_bytes(b"not a zip")
    docs, problems = core.scan([str(story)], use_cache=False)
    assert [os.path.basename(p["path"]) for p in problems] == ["broken.docx"]
    assert len(docs) == 6


def test_diff_marks_edits_additions_and_removals(story):
    docs, _ = core.scan([str(story)])
    by = {os.path.basename(d.path): d for d in docs}
    blocks = core.diff(by["report_v2.docx"], by["report_final.docx"])
    kinds = [b["t"] for b in blocks]
    assert "del" in kinds and "add" in kinds
    assert any(b["t"] == "del" and b["text"] == C for b in blocks)
    assert any(b["t"] == "add" and b["text"] == E for b in blocks)


def test_word_diff():
    assert core.word_diff("a b c", "a x c") == [["=", "a "], ["-", "b"], ["+", "x"], ["=", " c"]]


def test_skip_names_keeps_french_licence_reports():
    assert core.SKIP_NAMES.match("LICENSE.txt") and core.SKIP_NAMES.match("ThirdPartyNotices.txt")
    assert not core.SKIP_NAMES.match("licence_rapport.docx")


def test_one_added_paragraph_in_a_long_report_is_not_a_copy(tmp_path, monkeypatch):
    # regression: a 90% "same text" rule merged this side copy into its original and hid the paragraph
    monkeypatch.setattr(core, "cache_path", lambda: str(tmp_path / "cache.json"))
    topics = ["wing", "tail", "fuselage", "landing gear", "propeller", "battery", "camera", "aileron", "rudder", "flap"]
    body = [f"For the {t} at setting {k}, the measured drag {'matches' if n % 2 else 'exceeds'} the predicted value "
            f"and the {topics[(n + 3) % 10]} was checked again." for n, (t, k) in
            enumerate((t, k) for k in ("low", "medium", "high", "maximum") for t in topics)]
    docx(tmp_path / "long.docx", body, "2025-02-01T10:00:00Z")
    docx(tmp_path / "long_side.docx", body[:20] + [P] + body[20:], "2025-02-02T10:00:00Z")
    docx(tmp_path / "long_v2.docx", body + [E], "2025-02-03T10:00:00Z")
    docs, _ = core.scan([str(tmp_path)])
    r = core.report(core.families(docs)[0])
    assert len(r["versions"]) == 3
    assert [s["text"] for s in r["stranded"]] == [P]
    assert r["stranded"][0]["after"] == body[19]


def test_pdf_running_header_does_not_split_an_export(story):
    # same text as the final, plus a header line repeated on each "page": still the same version
    final = [A, B2, D, E]
    paras = []
    for p in final:
        paras += ["Drone project report page header", p]
    (story / "report_final.txt").write_text("\n\n".join(paras), encoding="utf-8")
    docs, _ = core.scan([str(story)])
    r = core.report(core.families(docs)[0])
    head = r["versions"][r["head"]]
    assert {os.path.basename(f["path"]) for f in head["files"]} >= {"report_final.docx", "report_final.txt"}


def test_page_footers_are_layout_but_two_similar_rows_are_not():
    paras = [A, "Jane Doe Sam Page 1 sur 9", B, "Jane Doe Sam Page 2 sur 9", C, "Jane Doe Sam Page 3 sur 9",
             "First run water mass 807 grams measured", "Second run water mass 606 grams measured"]
    d = core.Doc(0, "x.pdf", 0, 0, "file", paras)
    assert {paras[i] for i in d.layout} == {p for p in paras if "Page" in p}
