"""Write a NEW copy of the latest version with the left-behind passages put back where they belong.

The original is never touched. In a .docx the inserted passages are highlighted in yellow and take
the style of the paragraph they follow, so they are easy to review, keep or delete in Word.
"""
import os
from datetime import datetime, timezone
import re
import zipfile
from xml.sax.saxutils import escape

from .core import jaccard, shingles, words

MERGEABLE = {".docx", ".odt", ".md", ".txt", ".tex"}


def _anchor_index(head, text):
    """Index of the latest version's paragraph that best matches `text` (the paragraph the
    passage followed in its own copy), or None to put the passage at the start."""
    if not text:
        return None
    sh = shingles(words(text), 3)
    best, score = None, 0.0
    for i in head.content:
        s = jaccard(sh, head.psh[i])
        if s > score:
            best, score = i, s
    return best if score >= 0.3 else None


def plan(head, strays):
    """[(index in head.paras or None, [texts to insert after it])] in document order."""
    groups = {}
    for s in strays:
        groups.setdefault(_anchor_index(head, s["after"]), []).append(s["text"])
    return sorted(groups.items(), key=lambda kv: -1 if kv[0] is None else kv[0])


def target_path(path):
    stem, ext = os.path.splitext(path)
    out, n = f"{stem} (gleaned){ext}", 2
    while os.path.exists(out):
        out, n = f"{stem} (gleaned {n}){ext}", n + 1
    return out


def merged_copy(head, strays):
    """Write the copy next to the latest version and return its path."""
    ext = os.path.splitext(head.path)[1].lower()
    if ext not in MERGEABLE:
        raise ValueError(f"cannot write into {ext} files; open the latest version and paste the passages")
    out = target_path(head.path)
    if ext == ".docx":
        _docx(head.path, out, plan(head, strays))
    elif ext == ".odt":
        _odt(head.path, out, plan(head, strays))
    else:
        _text(head, out, plan(head, strays))
    return out


def _text(head, out, steps):
    paras = list(head.paras)
    for idx, texts in reversed(steps):  # from the end, so earlier indexes stay valid
        at = 0 if idx is None else idx + 1
        paras[at:at] = texts
    with open(out, "x", encoding="utf-8", newline="\n") as f:
        f.write("\n\n".join(paras) + "\n")


_P_TAG = re.compile(r"<w:p(?=[\s>/])[^>]*?(/?)>|</w:p>")
_PPR = re.compile(r"<w:pPr>.*?</w:pPr>|<w:pPr/>", re.S)
_SECT = re.compile(r"<w:sectPr\b.*?</w:sectPr>|<w:sectPr\b[^>]*/>", re.S)


def _paragraph_spans(xml, tags=_P_TAG):
    """(start, end) of every paragraph element in document order, nested ones included, which is
    the order extract.py reads them in."""
    spans, stack = [], []
    for m in tags.finditer(xml):
        if m.group(0).startswith("</"):
            k = stack.pop()
            spans[k] = (spans[k][0], m.end())
        elif m.group(1) == "/":
            spans.append((m.start(), m.end()))
        else:
            stack.append(len(spans))
            spans.append((m.start(), None))
    if stack or any(e is None for _, e in spans):
        raise ValueError("unexpected document structure")
    return spans


def _xml_text(text):
    return escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text))  # PDF text can hold bytes XML forbids


def _new_paragraph(text, ppr):
    run = ('<w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr>'
           f'<w:t xml:space="preserve">{_xml_text(text)}</w:t></w:r>')
    return f"<w:p>{ppr}{run}</w:p>"


def _docx(src, out, steps):
    with zipfile.ZipFile(src) as z:
        xml = z.read("word/document.xml").decode("utf-8")
        spans = _paragraph_spans(xml)
        # extract.py keeps only non-empty paragraphs: map its indexes back to raw <w:p> elements
        texts = []
        for a, b in spans:
            inner = re.sub(r"<w:tab/>", " ", xml[a:b])
            texts.append(" ".join("".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", inner)).split()))
        kept = [k for k, t in enumerate(texts) if t.strip()]
        edits = []
        for idx, new in steps:
            if idx is None:
                body = re.search(r"<w:body\b[^>]*>", xml).end()
                pos, ppr = body, ""
            else:
                k = kept[idx]
                pos = spans[k][1]
                m = _PPR.match(xml, spans[k][0] + xml[spans[k][0]:].index(">") + 1)
                ppr = _SECT.sub("", m.group(0)) if m else ""  # never copy a section break
            edits.append((pos, "".join(_new_paragraph(t, ppr) for t in new)))
        for pos, chunk in sorted(edits, reverse=True):
            xml = xml[:pos] + chunk + xml[pos:]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ").encode()
        with zipfile.ZipFile(out, "x", zipfile.ZIP_DEFLATED) as w:
            for info in z.infolist():
                data = xml.encode("utf-8") if info.filename == "word/document.xml" else z.read(info.filename)
                if info.filename == "docProps/core.xml":
                    # saved now, as Word would do: otherwise it ties with the original for "latest"
                    data = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*(<)", rb"\g<1>" + now + rb"\g<2>", data)
                w.writestr(info, data)


_ODF_P = re.compile(r"<text:[ph](?=[\s>/])[^>]*?(/?)>|</text:[ph]>")
_HL_STYLE = ('<style:style style:name="GleanerHighlight" style:family="text">'
             '<style:text-properties fo:background-color="#ffff00"/></style:style>')


def _odt(src, out, steps):
    """Same as _docx for LibreOffice: new <text:p> after the anchor, its paragraph style, a yellow span."""
    with zipfile.ZipFile(src) as z:
        xml = z.read("content.xml").decode("utf-8")
        spans = _paragraph_spans(xml, _ODF_P)
        texts = [" ".join(re.sub(r"<[^>]+>", "", xml[a:b]).split()) for a, b in spans]
        kept = [k for k, t in enumerate(texts) if t]
        edits = []
        for idx, new in steps:
            if idx is None:
                pos, style = re.search(r"<office:text[^>]*>", xml).end(), ""
            else:
                a, b = spans[kept[idx]]
                pos = b
                m = re.match(r'<text:[ph][^>]*?(text:style-name="[^"]*")', xml[a:b])
                style = " " + m.group(1) if m else ""
            chunk = "".join(f'<text:p{style}><text:span text:style-name="GleanerHighlight">{_xml_text(t)}'
                            "</text:span></text:p>" for t in new)
            edits.append((pos, chunk))
        for pos, chunk in sorted(edits, reverse=True):
            xml = xml[:pos] + chunk + xml[pos:]
        if "<office:automatic-styles/>" in xml:
            xml = xml.replace("<office:automatic-styles/>", f"<office:automatic-styles>{_HL_STYLE}</office:automatic-styles>", 1)
        elif "</office:automatic-styles>" in xml:
            xml = xml.replace("</office:automatic-styles>", _HL_STYLE + "</office:automatic-styles>", 1)
        else:
            xml = xml.replace("<office:body", f"<office:automatic-styles>{_HL_STYLE}</office:automatic-styles><office:body", 1)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S").encode()
        with zipfile.ZipFile(out, "x", zipfile.ZIP_DEFLATED) as w:
            for info in z.infolist():  # mimetype stays first and uncompressed, as ODF requires
                data = xml.encode("utf-8") if info.filename == "content.xml" else z.read(info.filename)
                if info.filename == "meta.xml":
                    data = re.sub(rb"(<dc:date>)[^<]*(<)", rb"\g<1>" + now + rb"\g<2>", data)
                w.writestr(info, data)
