"""Turn a document into an ordered list of paragraphs, plus its best-known edit time.

Office formats are zip files of XML: read with the standard library, no Office needed.
PDF needs the optional `pypdf` package; without it PDFs are skipped, not guessed.
"""
import logging
import os
import re
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
ODF_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
DCTERMS = "{http://purl.org/dc/terms/}"
DC = "{http://purl.org/dc/elements/1.1/}"
ODF_META = "{urn:oasis:names:tc:opendocument:xmlns:meta:1.0}"

SUPPORTED = {".docx", ".pptx", ".odt", ".odp", ".txt", ".md", ".tex", ".pdf"}
MAX_BYTES = 60 * 1024 * 1024  # shortcut: larger files are skipped; raise if real reports are bigger


logging.getLogger("pypdf").setLevel(logging.ERROR)  # font warnings on every school PDF: noise


class Unreadable(Exception):
    pass


def _iso(s):
    """Parse an ISO date from document metadata; None when absent or absurd."""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    t = d.timestamp()
    # Templates often carry 1601/1980 dates or future ones: ignore them.
    return t if 946684800 < t < datetime.now(timezone.utc).timestamp() + 86400 else None


def _docx(z):
    root = ET.fromstring(z.read("word/document.xml"))
    out = []
    for p in root.iter(W + "p"):
        parts = []
        for el in p.iter():
            # equations (math:t) are left out: PDF exports scatter them into fragments that would
            # make a .docx and its own PDF look like different versions
            if el.tag == W + "t" and el.text:
                parts.append(el.text)
            elif el.tag == W + "tab":
                parts.append(" ")
            elif el.tag in (W + "br", W + "cr"):
                parts.append("\n")
        out.append("".join(parts))
    return out


def _pptx(z):
    slides = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
    slides.sort(key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    out = []
    for n in slides:
        root = ET.fromstring(z.read(n))
        for p in root.iter(A + "p"):
            out.append("".join(t.text or "" for t in p.iter(A + "t")))
    return out


def _odf(z):
    root = ET.fromstring(z.read("content.xml"))
    return ["".join(el.itertext()) for el in root.iter() if el.tag in (ODF_TEXT + "p", ODF_TEXT + "h")]


def _ooxml_time(z):
    try:
        root = ET.fromstring(z.read("docProps/core.xml"))
    except KeyError:
        return None
    el = root.find(DCTERMS + "modified")
    return _iso(el.text if el is not None else None)


def _odf_time(z):
    try:
        root = ET.fromstring(z.read("meta.xml"))
    except KeyError:
        return None
    el = next(root.iter(DC + "date"), None)
    return _iso(el.text if el is not None else None)


def _plain(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    text = text.replace("\r\n", "\n")
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) >= 5 and sum(bool(_STAMPED.search(l[:40])) for l in lines) > len(lines) / 2:
        return []  # a log written by a program, not a document someone edits
    return re.split(r"\n\s*\n", text)


# a date or a clock time near the start of a line: 2026-08-22, 8/29/2026, [Info | 8:55:41 AM]
_STAMPED = re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}:\d{2}:\d{2}")


_SENTENCE_END = re.compile(r"[.!?:;»\"')\]]$")


def _pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise Unreadable("PDF support needs `pip install pypdf`")
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise Unreadable("encrypted PDF")
        lines = []
        for page in reader.pages:
            lines.extend((page.extract_text() or "").splitlines())
            lines.append("")
    except Unreadable:
        raise
    except Exception as e:  # pypdf raises many types on damaged files
        raise Unreadable(f"PDF could not be read: {type(e).__name__}")
    # PDFs have no paragraphs: rebuild them from lines that end a sentence.
    out, cur = [], []
    for line in lines:
        line = line.strip()
        if not line:
            if cur:
                out.append(" ".join(cur))
                cur = []
            continue
        cur.append(line)
        if _SENTENCE_END.search(line) and len(" ".join(cur)) > 80:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def extract(path):
    """Return (paragraphs, edited_time, time_source). Raises Unreadable."""
    ext = os.path.splitext(path)[1].lower()
    st = os.stat(path)
    if st.st_size > MAX_BYTES:
        raise Unreadable("file too large")
    meta_time = None
    try:
        if ext in (".docx", ".pptx", ".odt", ".odp"):
            with zipfile.ZipFile(path) as z:
                if ext == ".docx":
                    paras, meta_time = _docx(z), _ooxml_time(z)
                elif ext == ".pptx":
                    paras, meta_time = _pptx(z), _ooxml_time(z)
                else:
                    paras, meta_time = _odf(z), _odf_time(z)
        elif ext == ".pdf":
            paras = _pdf(path)
        else:
            paras = _plain(path)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise Unreadable(f"damaged or not a real {ext} file ({type(e).__name__})")
    except OSError as e:
        raise Unreadable(f"cannot open ({e.strerror or e})")
    paras = [re.sub(r"[ \t ]+", " ", p).strip() for p in paras]
    paras = [p for p in paras if p]
    if meta_time:
        return paras, meta_time, "document"
    return paras, st.st_mtime, "file"
