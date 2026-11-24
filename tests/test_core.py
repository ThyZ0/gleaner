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


def test_merged_copy_puts_passages_back_without_touching_the_original(story):
    from gleaner import merge
    docs, _ = core.scan([str(story)])
    fam = core.families(docs)[0]
    versions, head, strays = core.analyse(fam)
    head_doc = next(c for c in head["copies"] if c.path.endswith(".docx"))
    before = open(head_doc.path, "rb").read()
    stranded = [s for s in strays if s["status"] == "stranded"]
    out = merge.merged_copy(head_doc, stranded)
    assert open(head_doc.path, "rb").read() == before
    assert out.endswith("report_final (gleaned).docx")
    paras, _, _ = extract(out)
    assert paras == [A, B2, P, D, E], "after the paragraph that replaced its anchor"
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        assert '<w:highlight w:val="yellow"/>' in z.read("word/document.xml").decode()
    assert merge.merged_copy(head_doc, stranded).endswith("(gleaned 2).docx"), "never overwrites"


def test_merged_copy_of_a_text_file(tmp_path):
    from gleaner import merge
    (tmp_path / "notes.md").write_text(f"{A}\n\n{B}\n\n{C}\n", encoding="utf-8")
    head = core.Doc(0, str(tmp_path / "notes.md"), 0, 0, "file", [A, B, C])
    out = merge.merged_copy(head, [{"text": P, "after": B}, {"text": E, "after": None}])
    assert open(out, encoding="utf-8").read().split("\n\n") == [E, A, B, P, C + "\n"]


def test_lone_files_leave_no_text_in_the_cache_and_secret_names_are_never_read(story):
    (story / "my passwords.txt").write_text("bank account pass is hunter2 and the mail one is the same\n", encoding="utf-8")
    core.scan([str(story)])
    cache = core.load_cache()
    assert not any("passwords" in p for p in cache)
    tart = next(e for p, e in cache.items() if p.endswith("tart.docx"))
    assert "paras" not in tart and tart["sh"], "a lone document is cached as numbers only"
    final = next(e for p, e in cache.items() if p.endswith("report_final.docx"))
    assert final["paras"], "documents with versions keep their text so rescans stay fast"


def test_head_contained_in_a_richer_version_is_suspect(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "cache_path", lambda: str(tmp_path / "cache.json"))
    docx(tmp_path / "full.docx", [A, B, C, D, E], "2025-03-01T10:00:00Z")
    (tmp_path / "old.md").write_text(f"{A}\n\n{B}\n\n{C}\n", encoding="utf-8")  # file date = now: newest
    docs, _ = core.scan([str(tmp_path)])
    r = core.report(core.families(docs)[0])
    head = r["versions"][r["head"]]
    assert head["files"][0]["path"].endswith("old.md")
    assert r["versions"][r["suspect"]]["files"][0]["path"].endswith("full.docx")


def test_an_old_pdf_downloaded_today_does_not_make_its_version_new(story):
    # text identical to v1, file date = now: it joins v1 but must not move v1 to the top
    (story / "report_from_mail.md").write_text(f"{A}\n\n{B}\n\n{C}\n", encoding="utf-8")
    docs, _ = core.scan([str(story)])
    r = core.report(core.families(docs)[0])
    head = r["versions"][r["head"]]
    assert any(f["path"].endswith("report_final.docx") for f in head["files"])
    v1 = next(v for v in r["versions"] if any(f["path"].endswith("report_from_mail.md") for f in v["files"]))
    assert v1["n"] == 0


def test_diff_between_differently_cut_files_shows_only_real_changes():
    a = core.Doc(0, "a.docx", 0, 0, "document", ["Introduction", A, B, C])
    b = core.Doc(1, "a.txt", 0, 0, "file", ["Introduction " + A + " " + B2 + " " + C])  # one paragraph, B edited
    blocks = core.diff(a, b)
    changed = [x for x in blocks if x["t"] not in ("same", "skip")]
    assert len(changed) == 1 and changed[0]["t"] == "mod"
    assert any(o == "+" and "almost" in w for o, w in changed[0]["words"])


def test_merged_copy_is_dated_now_so_it_becomes_the_latest(story):
    from gleaner import merge
    docs, _ = core.scan([str(story)])
    versions, head, strays = core.analyse(core.families(docs)[0])
    head_doc = next(c for c in head["copies"] if c.path.endswith(".docx"))
    out = merge.merged_copy(head_doc, [s for s in strays if s["status"] == "stranded"])
    _, t, src = extract(out)
    assert src == "document" and t > head_doc.time
    r = core.report(core.families(core.scan([str(story)])[0])[0])
    assert r["versions"][r["head"]]["files"][0]["path"] == out and not r["stranded"]


def test_password_protected_office_file_is_named_as_such(tmp_path):
    from gleaner.extract import Unreadable
    p = tmp_path / "locked.docx"
    p.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + b"\0" * 600)
    with pytest.raises(Unreadable, match="password-protected"):
        extract(str(p))


def pptx(path, slides_text, order, modified):
    """slides_text[k] = paragraphs of file slide{k+1}.xml; order = file numbers in showing order."""
    with zipfile.ZipFile(path, "w") as z:
        for k, paras in enumerate(slides_text, 1):
            body = "".join(f"<a:p><a:r><a:t>{p}</a:t></a:r></a:p>" for p in paras)
            z.writestr(f"ppt/slides/slide{k}.xml",
                       '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                       f"<p:cSld><p:spTree><p:sp><p:txBody>{body}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>")
        rels = "".join(f'<Relationship Id="rId{k}" Target="slides/slide{k}.xml" Type="slide"/>'
                       for k in range(1, len(slides_text) + 1))
        z.writestr("ppt/_rels/presentation.xml.rels",
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        ids = "".join(f'<p:sldId id="{255 + k}" r:id="rId{k}"/>' for k in order)
        z.writestr("ppt/presentation.xml",
                   '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   f"<p:sldIdLst>{ids}</p:sldIdLst></p:presentation>")
        z.writestr("docProps/core.xml",
                   '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   f'xmlns:dcterms="http://purl.org/dc/terms/"><dcterms:modified>{modified}</dcterms:modified></cp:coreProperties>')


def test_pptx_reads_slides_in_showing_order_and_names_the_slide_of_a_stray(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "cache_path", lambda: str(tmp_path / "cache.json"))
    # file slide2 is shown first
    pptx(tmp_path / "talk.pptx", [[C, D], [A, B]], [2, 1], "2025-01-01T10:00:00Z")
    paras, _, _ = extract(str(tmp_path / "talk.pptx"))
    assert paras == [A, B, C, D]
    pptx(tmp_path / "talk_sam.pptx", [[C, P, D], [A, B]], [2, 1], "2025-01-02T10:00:00Z")
    pptx(tmp_path / "talk_v2.pptx", [[C, D, E], [A, B]], [2, 1], "2025-01-03T10:00:00Z")
    docs, _ = core.scan([str(tmp_path)])
    r = core.report(core.families(docs)[0])
    assert [(s["text"], s.get("slide")) for s in r["stranded"]] == [(P, 2)]


def test_merged_copy_can_insert_at_the_very_start_of_a_word_file(story):
    # regression: a stray character in the <w:body> pattern crashed this case
    from gleaner import merge
    head = next(d for d in core.scan([str(story)])[0] if d.path.endswith("report_final.docx"))
    out = merge.merged_copy(head, [{"text": P, "after": None}])
    assert extract(out)[0][0] == P


def odt(path, paras, date):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text")
        body = "".join(f'<text:p text:style-name="P1">{p}</text:p>' for p in paras)
        z.writestr("content.xml",
                   '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                   'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
                   'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
                   'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">'
                   f"<office:automatic-styles/><office:body><office:text>{body}</office:text></office:body>"
                   "</office:document-content>")
        z.writestr("meta.xml",
                   '<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/"><office:meta>'
                   f"<dc:date>{date}</dc:date></office:meta></office:document-meta>")


def test_merged_copy_of_a_libreoffice_file(tmp_path, monkeypatch):
    from gleaner import merge
    monkeypatch.setattr(core, "cache_path", lambda: str(tmp_path / "cache.json"))
    odt(tmp_path / "notes.odt", [A, B, C], "2025-01-01T10:00:00")
    odt(tmp_path / "notes_sam.odt", [A, B, P, C], "2025-01-02T10:00:00")
    odt(tmp_path / "notes_v2.odt", [A, B, C, D], "2025-01-03T10:00:00")
    docs, _ = core.scan([str(tmp_path)])
    fam = core.families(docs)[0]
    r = core.report(fam)
    assert r["mergeable"] and [s["text"] for s in r["stranded"]] == [P]
    _, head, _ = core.analyse(fam)
    out = merge.merged_copy(head["doc"], r["stranded"])
    paras, t, src = extract(out)
    assert paras == [A, B, P, C, D] and src == "document" and t > head["doc"].time
    with zipfile.ZipFile(out) as z:
        assert z.namelist()[0] == "mimetype" and z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert "GleanerHighlight" in z.read("content.xml").decode()
