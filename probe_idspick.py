import sys
import json
import re
from pathlib import Path

sys.path.insert(0, r"D:\hanstroke-demo")
import benchmark_v3 as b

CACHE = Path(r"D:\hanstroke-demo\cache_hanstroke")


def cnchar_tokens(path):
    m = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    table = json.loads((CACHE / "cnchar-stroke-table.json").read_text(encoding="utf-8"))
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
            nm = re.sub(r"\d+$", "", nm)
            if not nm:
                ok = False
                break
            toks.append(nm)
        if ok and toks:
            out[ch] = toks
    return out


cn_map = cnchar_tokens(CACHE / "cnchar-stroke-order-jian.json")
for ch, v in cnchar_tokens(CACHE / "cnchar-stroke-order-trad.json").items():
    cn_map.setdefault(ch, v)

ids_raw = {}
with open(CACHE / "ids.txt", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) < 3:
            continue
        ch = p[1].strip()
        if len(ch) != 1 or ch in ids_raw:
            continue
        for cand in p[2:]:
            c = re.sub(r"\[[^\]]+\]", "", cand).strip()
            if c:
                ids_raw[ch] = c
                break

seqmap = {}
with open(CACHE / "codepoint-character-sequence.txt", encoding="utf-8") as f:
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3 and p[0].startswith("U+"):
            try:
                seqmap[chr(int(p[0][2:], 16))] = p[2]
            except ValueError:
                pass

stroke = b.load_stroke_order_data(
    CACHE / "codepoint-character-sequence.txt",
    CACHE / "ucs-strokes.txt",
    CACHE / "cnchar-stroke-table.json",
    [
        CACHE / "cnchar-stroke-order-jian.json",
        CACHE / "cnchar-stroke-order-trad.json",
    ],
)

n = 0
for ch, seq in sorted(seqmap.items()):
    if n >= 18:
        break
    if ch not in cn_map or ch not in stroke:
        continue
    try:
        segs = b.parse_stroke_segments(seq)
    except Exception:
        continue
    if not segs[0][1]:
        continue
    raw = ids_raw.get(ch)
    if not raw:
        continue
    tree = b.parse_ids(raw)
    if tree is None or isinstance(tree, str) or tree.op != "⿰":
        continue
    lf = tree.children[0]
    if isinstance(lf, str) and lf.startswith("&"):
        d = b.decode_entity_ref(lf)
        lf = d if d else lf
    if not isinstance(lf, str) or len(lf) != 1 or lf == ch:
        continue
    e = stroke.get(lf)
    if not e:
        continue
    try:
        lfirst, llast = b.stroke_adapter(e[1])
    except Exception:
        continue
    tf_c = b._name_to_class_digit(cn_map[ch][0])
    if b.CLASS_TO_DIGIT.get(lfirst) == tf_c:
        continue
    n += 1
    cf = b.CLASS_TO_DIGIT.get(tf_c, "?")
    lfd = b.CLASS_TO_DIGIT.get(lfirst, "?")
    # show cnchar letters for the char and the leaf
    cn_letters = "?"
    for name, path in (
        ("jian", CACHE / "cnchar-stroke-order-jian.json"),
        ("trad", CACHE / "cnchar-stroke-order-trad.json"),
    ):
        m = json.loads(path.read_text(encoding="utf-8"))
        if ch in m:
            cn_letters = f"{name}:{m[ch]}"
            break
    print(
        f"{ch} U+{ord(ch):04X} seq={seq[:16]:16s} leaf={lf} "
        f"leaf_first={lfirst}({lfd}) cnchar_first={cf} cnchar={cn_letters}"
    )
