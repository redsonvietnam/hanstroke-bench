import json
import random
import sys
from pathlib import Path

sys.path.insert(0, r"D:\hanstroke-demo")
import benchmark_v3 as b

CACHE = Path(r"D:\hanstroke-demo\cache_hanstroke")

stroke = b.load_stroke_order_data(
    CACHE / "codepoint-character-sequence.txt",
    CACHE / "ucs-strokes.txt",
    CACHE / "cnchar-stroke-table.json",
    [CACHE / "cnchar-stroke-order-jian.json", CACHE / "cnchar-stroke-order-trad.json"],
)

table = json.loads((CACHE / "cnchar-stroke-table.json").read_text(encoding="utf-8"))


def cnchar_tokens(path):
    m = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for ch, letters in m.items():
        if len(ch) != 1 or not isinstance(letters, str):
            continue
        toks = []
        ok = True
        for L in letters:
            nm = table.get(L, {}).get("name")
            if not nm:
                ok = False
                break
            nm = str(nm).split("|")[0].strip()
            nm = __import__("re").sub(r"\d+$", "", nm)
            if not nm:
                ok = False
                break
            toks.append(nm)
        if ok and toks:
            out[ch] = toks
    return out


# Same precedence as the loader: jian first, trad only where jian has no entry.
cn_map = cnchar_tokens(CACHE / "cnchar-stroke-order-jian.json")
for ch, v in cnchar_tokens(CACHE / "cnchar-stroke-order-trad.json").items():
    cn_map.setdefault(ch, v)

seqmap = {}
groupchars = set()
with open(CACHE / "codepoint-character-sequence.txt", encoding="utf-8") as f:
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3 and p[0].startswith("U+"):
            try:
                ch = chr(int(p[0][2:], 16))
            except ValueError:
                continue
            seqmap[ch] = p[2]
            if "(" in p[2]:
                groupchars.add(ch)

# Unihan kTotalStrokes (direct parse, independent of loader)
unihan_total = {}
import zipfile

with zipfile.ZipFile(CACHE / "Unihan.zip") as z:
    with z.open("Unihan_IRGSources.txt") as fh:
        for raw in fh:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("#") or "kTotalStrokes" not in line:
                continue
            parts = line.split("\t")
            if len(parts) >= 3 and parts[1] == "kTotalStrokes":
                try:
                    unihan_total[chr(int(parts[0][2:], 16))] = int(parts[2])
                except (ValueError, IndexError):
                    pass

IDS_OPERATORS = set("⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻")


def ids_first_leaf(ids):
    """Leading component of an IDS (first non-operator char, recursive-ish)."""
    for ch in ids:
        if ch not in IDS_OPERATORS and ch not in "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮":
            return ch
    return None


ids_map = {}
with open(CACHE / "ids.txt", encoding="utf-8") as f:
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3 and p[0].startswith("U+"):
            try:
                ch = chr(int(p[0][2:], 16))
            except ValueError:
                continue
            ids_map[ch] = p[2]


def in_b0(ch):
    if len(ch) != 1:
        return False
    o = ord(ch)
    return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF


def cls_of(names):
    if not names:
        return (None, None)
    rev = {v: k for k, v in b.CLASS_TO_DIGIT.items()}
    return (
        rev.get(b._name_to_class_digit(names[0])),
        rev.get(b._name_to_class_digit(names[-1])),
    )


rng = random.Random(20261003)

cn_trad = set(
    json.loads((CACHE / "cnchar-stroke-order-trad.json").read_text(encoding="utf-8"))
)
bA = sorted(c for c in cn_trad if len(c) == 1 and c in stroke and in_b0(c))
bB = sorted(c for c in groupchars if c in stroke and in_b0(c) and c not in cn_trad)
bC = sorted(
    c for c in stroke if in_b0(c) and c not in cn_map and c not in groupchars
)

sel = []
sel += rng.sample(bA, 40)
sel += rng.sample(bB, 30)
sel += rng.sample(bC, 30)
assert len(sel) == 100 and len(set(sel)) == 100

rows = []
for i, ch in enumerate(sel, 1):
    total, toks = stroke[ch]
    first, last = b.stroke_adapter(toks)
    cn = cn_map.get(ch)
    c_first, c_last = cls_of(cn)
    seq = seqmap.get(ch, "-")
    if c_first is None and c_last is None:
        verdict = "SINGLE"
    elif first == c_first and last == c_last:
        verdict = "AGREE"
    else:
        verdict = "CONFLICT"

    ut = unihan_total.get(ch)
    if ut == total == len(toks):
        count_match = "Y"
    else:
        count_match = f"{ut}/{total}/{len(toks)}"

    ids = ids_map.get(ch, "")
    leaf = ids_first_leaf(ids) if ids and ids != ch else None
    ids_first = None
    if leaf and leaf in stroke:
        try:
            ids_first, _ = b.stroke_adapter(stroke[leaf][1])
        except Exception:
            ids_first = None
    ids_match = "." if ids_first is None else ("Y" if ids_first == first else "N")

    rows.append(
        dict(
            i=i,
            ch=ch,
            cp=f"U+{ord(ch):04X}",
            total=total,
            f=first,
            l=last,
            cf=c_first,
            cl=c_last,
            verdict=verdict,
            seq=seq,
            cm=count_match,
            im=ids_match,
            ids=ids,
        )
    )

from collections import Counter

cnt_v = Counter(r["verdict"] for r in rows)
cnt_cm = Counter(r["cm"] for r in rows)
cnt_im = Counter(r["im"] for r in rows)
print("BUCKETS sizes:", len(bA), len(bB), len(bC))
print("VERDICTS:", dict(cnt_v))
print("COUNT_MATCH:", dict(cnt_cm))
print("IDS_FIRST_MATCH:", dict(cnt_im))
print()
print(
    f"{'#':>3} {'char':<3} {'cp':<8} {'tot':>3} {'pipe':<6} {'cnch':<6} "
    f"{'verdict':<8} {'cnt':<8} {'ids':<3} seq"
)
for r in rows:
    cnch = f"{r['cf'] or '-'}{r['cl'] or '-'}"
    print(
        f"{r['i']:>3} {r['ch']:<3} {r['cp']:<8} {r['total']:>3} {r['f'] + r['l']:<6} "
        f"{cnch:<6} {r['verdict']:<8} {r['cm']:<8} {r['im']:<3} {r['seq']}"
    )
