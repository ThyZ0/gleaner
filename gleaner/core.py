"""Find the versions of each document, rebuild how they descend from each other,
and spot paragraphs written in a side copy that never reached the latest version."""
import difflib
import hashlib
import json
import os
import re
import stat
import tempfile
from collections import defaultdict

from .extract import SUPPORTED, Unreadable, extract

# the cache holds extracted text: any change to the extractor must invalidate it
with open(os.path.join(os.path.dirname(__file__), "extract.py"), "rb") as _f:
    CACHE_VERSION = hashlib.sha1(_f.read()).hexdigest()[:12]
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "site-packages", "$recycle.bin",
             "appdata", ".cache", ".tox", "dist", "build", ".idea", ".vscode"}
# legal boilerplate shipped with software: shared by thousands of files, written by nobody here
SKIP_NAMES = re.compile(r"(.*[-_.])?(licen[cs]e|copying|notices?|third[-_ ]?party[-_ ]?notices|authors|patents)(\.(txt|md))?$", re.I)
MIN_WORDS = 4          # shorter paragraphs (titles, page numbers) are layout, not work
DOC_SHINGLE = 5        # words per shingle when comparing whole documents
PARA_SHINGLE = 3       # words per shingle when comparing paragraphs
# Cloud files not on disk: opening them would download them. FILE_ATTRIBUTE_OFFLINE | RECALL_ON_*.
_CLOUD_ONLY = 0x1000 | 0x40000 | 0x400000


def words(text):
    return re.findall(r"\w+", text.lower())


def shingles(ws, k):
    if len(ws) < k:
        return {hash(tuple(ws))} if ws else set()
    return {hash(tuple(ws[i:i + k])) for i in range(len(ws) - k + 1)}


class Doc:
    __slots__ = ("id", "path", "size", "time", "time_source", "paras", "content", "norm", "psh",
                 "sh", "allsh", "digest")

    def __init__(self, id, path, size, time, time_source, paras):
        self.id, self.path, self.size = id, path, size
        self.time, self.time_source, self.paras = time, time_source, paras
        # content = indexes of paragraphs long enough to count as written work
        self.content, self.norm, self.psh = [], [], []
        all_words = []
        for i, p in enumerate(paras):
            ws = words(p)
            self.norm.append(" ".join(ws))
            self.psh.append(shingles(ws, PARA_SHINGLE))
            if len(ws) >= MIN_WORDS:
                self.content.append(i)
                all_words.extend(ws)
        self.sh = shingles(all_words, DOC_SHINGLE) if len(all_words) >= DOC_SHINGLE else set()
        # every 3-word run of the text, across paragraph breaks: a paragraph "is in" a document
        # when most of its runs are, however that document's format cut it into paragraphs
        self.allsh = shingles(all_words, PARA_SHINGLE)
        self.digest = hashlib.sha1("\n".join(self.norm[i] for i in self.content).encode()).hexdigest()


# ---------------------------------------------------------------- scanning

def cache_path():
    return os.path.join(os.path.expanduser("~"), ".gleaner", "cache.json")


def load_cache():
    try:
        with open(cache_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data["files"] if data.get("v") == CACHE_VERSION else {}
    except (OSError, ValueError, KeyError):
        return {}


def save_cache(files):
    path = cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"v": CACHE_VERSION, "files": files}, f, ensure_ascii=False)
    os.replace(tmp, path)


def walk(roots):
    """Yield (path, stat) for supported documents under roots, skipping tool folders and cloud-only files."""
    seen = set()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                if (name.startswith("~$") or os.path.splitext(name)[1].lower() not in SUPPORTED
                        or SKIP_NAMES.match(name)):
                    continue
                path = os.path.normpath(os.path.join(dirpath, name))
                if path in seen:
                    continue
                seen.add(path)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                if getattr(st, "st_file_attributes", 0) & _CLOUD_ONLY or not stat.S_ISREG(st.st_mode):
                    continue
                yield path, st


def _read(path, size, mtime):
    try:
        paras, t, src = extract(path)
        return {"size": size, "mtime": mtime, "paras": paras, "time": t, "src": src}
    except Unreadable as e:
        return {"size": size, "mtime": mtime, "err": str(e)}


def scan(roots, progress=None, use_cache=True):
    """Read every document under roots. Returns (docs, problems). Unchanged files come from the cache;
    the others are read in parallel (PDF parsing is slow and uses one core per file)."""
    cache = load_cache() if use_cache else {}
    files = list(walk(roots))
    entries, todo = {}, []
    for path, st in files:
        hit = cache.get(path)
        if hit and hit["size"] == st.st_size and hit["mtime"] == st.st_mtime:
            entries[path] = hit
        else:
            todo.append((path, st.st_size, st.st_mtime))
    done = len(entries)
    if progress:
        progress(done, len(files), "")
    if len(todo) <= 8:
        for t in todo:
            entries[t[0]] = _read(*t)
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=max(1, min(8, (os.cpu_count() or 2) - 1))) as pool:
            futures = {pool.submit(_read, *t): t for t in todo}
            for fut in as_completed(futures):
                t = futures[fut]
                try:
                    entries[t[0]] = fut.result()
                except Exception as e:  # a crashed worker must not lose the whole scan
                    entries[t[0]] = {"size": t[1], "mtime": t[2], "err": f"reader crashed ({type(e).__name__})"}
                done += 1
                if progress and done % 5 == 0:
                    progress(done, len(files), t[0])
    new_cache, docs, problems = {}, [], []
    for path, st in files:
        entry = new_cache[path] = entries[path]
        if "err" in entry:
            problems.append({"path": path, "reason": entry["err"]})
        elif entry["paras"]:
            docs.append(Doc(len(docs), path, st.st_size, entry["time"], entry["src"], entry["paras"]))
    if progress:
        progress(len(files), len(files), "")
    if use_cache:
        # keep entries for folders not scanned this time, so scanning one folder doesn't wipe the rest
        roots_n = [os.path.normcase(os.path.normpath(r)) for r in roots]
        for p, e in cache.items():
            if p not in new_cache and not any(os.path.normcase(p).startswith(r + os.sep) for r in roots_n):
                new_cache[p] = e
        save_cache(new_cache)
    return docs, problems


# ---------------------------------------------------------------- families

def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def related(a, b):
    """Two documents are versions of each other if they share most of their text.
    Containment lets a 2-page draft join its 10-page final; the Jaccard floor keeps
    papers that merely share a template (exam instructions, a cover page) apart."""
    if not a.sh or not b.sh:
        return False
    inter = len(a.sh & b.sh)
    if inter < 20:
        return False
    jac = inter / (len(a.sh) + len(b.sh) - inter)
    contain = inter / min(len(a.sh), len(b.sh))
    return jac >= 0.35 or (contain >= 0.8 and jac >= 0.12)


def families(docs):
    """Group documents into families of versions. Returns list of lists of Doc (size >= 2)."""
    parent = list(range(len(docs)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # identical text: always the same family, even for very short files
    by_digest = defaultdict(list)
    for d in docs:
        if d.content:
            by_digest[d.digest].append(d.id)
    for ids in by_digest.values():
        for i in ids[1:]:
            parent[find(i)] = find(ids[0])

    # Candidates come from a fixed 1-in-8 sample of shingles (the same sample in every file),
    # then each candidate pair is checked on the full text.
    index = defaultdict(list)
    for d in docs:
        for s in d.sh:
            if s & 7 == 0:
                index[s].append(d.id)
    shared = defaultdict(int)
    for ids in index.values():
        if len(ids) > 60:  # shingle in too many files: boilerplate, says nothing about lineage
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                shared[(ids[i], ids[j])] += 1
    for (i, j), n in shared.items():
        if n >= 2 and find(i) != find(j) and related(docs[i], docs[j]):
            parent[find(i)] = find(j)

    groups = defaultdict(list)
    for d in docs:
        groups[find(d.id)].append(d)
    return [sorted(g, key=lambda d: d.time) for g in groups.values() if len(g) > 1]


# ---------------------------------------------------------------- lineage and strays

EDITABLE = {".docx", ".pptx", ".odt", ".odp", ".txt", ".md", ".tex"}
KEPT = 0.6  # share of a paragraph's 3-word runs a document must hold to "still have" it


def ext(doc):
    return os.path.splitext(doc.path)[1].lower()


def contained(sh, big):
    """Share of `sh` found in `big`."""
    return len(sh & big) / len(sh) if sh else 0.0


def same_content(a, b):
    """Identical text, or the same text in another format (a .docx and its PDF export)."""
    return a.digest == b.digest or (contained(a.allsh, b.allsh) >= 0.9 and contained(b.allsh, a.allsh) >= 0.9)


def analyse(family, head_id=None):
    """Lineage + strays for one family (list of Doc sorted by time).

    Copies and exports with the same text are one version. Each version's parent is the
    most similar older version. A paragraph missing from the head is:
      - 'removed'  if it existed on the head's own line of ancestors (someone deleted it there),
      - 'stranded' if it only ever lived in side copies (written, then never carried over).
    """
    versions = []
    for d in family:
        v = next((v for v in versions if same_content(v["copies"][0], d)), None)
        if v:
            v["copies"].append(d)
        else:
            versions.append({"copies": [d]})
    for v in versions:
        editable = [c for c in v["copies"] if ext(c) in EDITABLE]
        # show the file you'd edit: an editable one, preferably the one whose date is saved inside
        # it (Office/ODF) rather than a plain-text export made later
        v["doc"] = max(editable or v["copies"], key=lambda d: (d.time_source == "document", d.time))
        v["time"] = max(c.time for c in v["copies"])
    versions.sort(key=lambda v: v["time"])
    for n, v in enumerate(versions):
        v["n"] = n
        best, best_sim = None, -1.0
        for u in versions[:n]:
            sim = jaccard(u["doc"].allsh, v["doc"].allsh)
            if sim >= best_sim:
                best, best_sim = u, sim
        v["parent"] = best["n"] if best else None
        v["sim"] = round(best_sim, 3) if best else None

    head = versions[-1]
    if head_id is not None:
        head = next((v for v in versions if any(c.id == head_id for c in v["copies"])), head)
    line = set()
    x = head["n"]
    while x is not None:
        line.add(x)
        x = versions[x]["parent"]

    head_sh = head["doc"].allsh
    strays = []
    for v in versions:
        if v is head:
            continue
        d = v["doc"]
        last_anchor = None
        for i in d.content:
            sh = d.psh[i]
            if contained(sh, head_sh) >= KEPT:
                last_anchor = d.paras[i]  # only paragraphs the head still has can anchor a stray
                continue
            known = next((s for s in strays if contained(sh, s["_sh"]) >= KEPT or contained(s["_sh"], sh) >= KEPT), None)
            if known:
                known["seen_in"].append(v["n"])
                if v["n"] in line:
                    known["status"] = "removed"
                continue
            strays.append({"text": d.paras[i], "seen_in": [v["n"]], "after": last_anchor,
                           "status": "removed" if v["n"] in line else "stranded", "_sh": sh})
    for s in strays:
        del s["_sh"]
        s["source"] = max(s["seen_in"])  # the most recent copy holding it
    return versions, head, strays


def report(family, head_id=None):
    """Everything the CLI and the UI show about a family, as plain JSON-ready data."""
    versions, head, strays = analyse(family, head_id)
    received = all(ext(d) == ".pdf" for d in family)
    out_versions = []
    for v in versions:
        d = v["doc"]
        out_versions.append({
            "n": v["n"], "parent": v["parent"], "sim": v["sim"], "time": v["time"],
            "doc_time": d.time, "time_source": d.time_source, "is_head": v is head,
            "words": sum(len(d.norm[i].split()) for i in d.content),
            # the file to open first, then its other copies, newest first
            "files": [{"id": c.id, "path": c.path, "time": c.time, "size": c.size, "ext": ext(c)}
                      for c in sorted(v["copies"], key=lambda c: (c is not d, -c.time))],
        })
    stranded = [s for s in strays if s["status"] == "stranded"]
    name = os.path.basename(head["doc"].path)
    return {
        "name": name, "head": head["n"], "received": received,
        "versions": out_versions, "files": len(family),
        "stranded": stranded, "removed": [s for s in strays if s["status"] == "removed"],
        # left-behind work first, then the most recently edited documents
        "score": (0 if received else 2e10) + (1e10 if stranded else 0) + versions[-1]["time"],
    }


# ---------------------------------------------------------------- diff

def diff(a, b, context=2):
    """Paragraph-level diff of Doc a -> Doc b, with word-level detail on edited paragraphs."""
    sm = difflib.SequenceMatcher(None, a.norm, b.norm, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            n = i2 - i1
            if n > 2 * context + 1:
                out += [{"t": "same", "text": a.paras[i]} for i in range(i1, i1 + context)]
                out.append({"t": "skip", "n": n - 2 * context})
                out += [{"t": "same", "text": a.paras[i]} for i in range(i2 - context, i2)]
            else:
                out += [{"t": "same", "text": a.paras[i]} for i in range(i1, i2)]
            continue
        olds, news = list(range(i1, i2)), list(range(j1, j2))
        # pair up edited paragraphs, leave the rest as plain removals/additions
        while olds or news:
            if olds and news and jaccard(a.psh[olds[0]], b.psh[news[0]]) >= 0.3:
                out.append({"t": "mod", "words": word_diff(a.paras[olds.pop(0)], b.paras[news.pop(0)])})
            elif olds and (not news or _best(a.psh[olds[0]], b, news) < 0.3):
                out.append({"t": "del", "text": a.paras[olds.pop(0)]})
            else:
                out.append({"t": "add", "text": b.paras[news.pop(0)]})
    return out


def _best(sh, doc, idxs):
    return max((jaccard(sh, doc.psh[j]) for j in idxs), default=0.0)


def word_diff(old, new):
    a, b = re.findall(r"\S+|\s+", old), re.findall(r"\S+|\s+", new)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(["=", "".join(a[i1:i2])])
        else:
            if i2 > i1:
                out.append(["-", "".join(a[i1:i2])])
            if j2 > j1:
                out.append(["+", "".join(b[j1:j2])])
    return out
