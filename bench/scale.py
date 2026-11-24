"""Speed and accuracy on synthetic documents with a known history (no disk, no real data).

    python bench/scale.py [N_FAMILIES] [N_LONERS]

Each family: an original, a main line of edited versions, and one side copy where 1-3
paragraphs are added and never merged. Loners are unrelated documents built from the same
vocabulary and sharing a common "template" paragraph, to tempt false merges.
Reports: time, memory, family purity/completeness, and left-behind recall/precision.
"""
import random
import sys
import time
import tracemalloc

sys.path.insert(0, __file__.rsplit("bench", 1)[0])
from gleaner import core  # noqa: E402

rng = random.Random(7)
VOCAB = ["".join("abcdefghijklmnopqrstuvwxyz"[(i // 26 ** k) % 26] for k in range(3)) + "x" for i in range(5000)]
WEIGHTS = [1 / (i + 1) for i in range(5000)]  # Zipf-like: a few very common words, as in real text
TEMPLATE = "Institut name department of aeronautics year two group project report submitted to the jury on the date below"


def para(n=None):
    return " ".join(rng.choices(VOCAB, WEIGHTS, k=n or rng.randint(15, 60)))


def edit(p):
    ws = p.split()
    for _ in range(rng.randint(1, 3)):
        ws[rng.randrange(len(ws))] = rng.choice(VOCAB)
    return " ".join(ws)


def family(k):
    base = [TEMPLATE] + [para() for _ in range(rng.randint(6, 30))]
    line = [base]
    for _ in range(rng.randint(1, 4)):
        v = [edit(p) if rng.random() < .2 else p for p in line[-1]]
        if len(v) > 4 and rng.random() < .5:
            v.pop(rng.randrange(1, len(v)))
        v.insert(rng.randrange(1, len(v) + 1), para())
        line.append(v)
    fork = rng.randrange(len(line) - 1)  # the side copy starts from a version before the latest
    side = list(line[fork])
    added = [f"side{k} " + para() for _ in range(rng.randint(1, 3))]
    for a in added:
        side.insert(rng.randrange(1, len(side) + 1), a)
    t0 = 1.7e9 + k * 1e6
    docs = [(f"f{k}/v{i}.docx", t0 + i * 1000 + (500 if i > fork else 0), v) for i, v in enumerate(line)]
    docs.append((f"f{k}/side.docx", t0 + fork * 1000 + 600, side))
    if rng.random() < .3:  # an export of the latest, with paragraphs cut differently
        merged = [line[-1][0] + " " + line[-1][1]] + line[-1][2:]
        docs.append((f"f{k}/latest.pdf", t0 + 10000, merged))
    return docs, added


def main(n_fam=1000, n_lone=5000):
    specs, truth_added = [], {}
    for k in range(n_fam):
        docs, added = family(k)
        specs += docs
        truth_added[k] = added
    for j in range(n_lone):
        specs.append((f"lone/{j}.docx", 1.6e9 + j, [TEMPLATE] + [para() for _ in range(rng.randint(4, 30))]))

    tracemalloc.start()
    t = time.perf_counter()
    docs = [core.Doc(i, p, 0, tm, "document", paras) for i, (p, tm, paras) in enumerate(specs)]
    t_docs = time.perf_counter() - t
    t = time.perf_counter()
    fams = core.families(docs)
    t_fam = time.perf_counter() - t
    t = time.perf_counter()
    reports = {}
    for f in fams:
        ks = {d.path.split("/")[0] for d in f}
        reports[frozenset(ks)] = core.report(f)
    t_rep = time.perf_counter() - t
    mem = tracemalloc.get_traced_memory()[1] / 1e6
    tracemalloc.stop()

    # grouping: each true family should be exactly one found family
    found = {}
    for f in fams:
        for d in f:
            found[d.path] = id(f)
    exact = sum(1 for k in range(n_fam)
                if len({found.get(p) for p, _, _ in specs if p.startswith(f"f{k}/")}) == 1
                and None not in {found.get(p) for p, _, _ in specs if p.startswith(f"f{k}/")}
                and all(d.path.startswith(f"f{k}/") for f in fams if any(d.path.startswith(f"f{k}/") for d in f) for d in f))
    lone_merged = sum(1 for p, _, _ in specs if p.startswith("lone/") and p in found)

    hit = total = flagged = right = 0
    for ks, r in reports.items():
        for s in r["stranded"]:
            flagged += 1
            right += s["text"].startswith("side")
    for k, added in truth_added.items():
        r = reports.get(frozenset({f"f{k}"}))
        total += len(added)
        if r:
            texts = {s["text"] for s in r["stranded"]}
            hit += sum(a in texts for a in added)

    print(f"{len(docs)} documents ({n_fam} families, {n_lone} unrelated)")
    print(f"time: read {t_docs:.2f} s, group {t_fam:.2f} s, analyse {t_rep:.2f} s   peak memory {mem:.0f} MB")
    print(f"families found exactly: {exact}/{n_fam}   unrelated documents wrongly grouped: {lone_merged}/{n_lone}")
    print(f"left-behind passages found: {hit}/{total} (recall {hit / max(total, 1):.1%})   "
          f"flags that are real: {right}/{flagged} (precision {right / max(flagged, 1):.1%})")


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:3]))
