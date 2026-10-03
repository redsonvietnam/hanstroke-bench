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

# leaf verification: leaf in cnchar AND stroke first/last == cnchar first/last
leaf_ok = {}
for lf, e in stroke.items():
    if len(lf) != 1 or lf not in cn_map:
        continue
    try:
        f_d, l_d = b.stroke_adapter(e[1])
    except Exception:
        continue
    cf = b._name_to_class_digit(cn_map[lf][0])
    cl = b._name_to_class_digit(cn_map[lf][-1])
    leaf_ok[lf] = (cf is not None and cl is not None
                   and b.CLASS_TO_DIGIT.get(f_d) == cf
                   and b.CLASS_TO_DIGIT.get(l_d) == cl)


def lead(node):
    if isinstance(node, str):
        return node, False
    if node.op in b.IDS_EXCLUDED_OPS:
        return None, True
    if not node.children:
        return None, False
    return lead(node.children[0])


def trail(node):
    if isinstance(node, str):
        return node, False
    if node.op in b.IDS_EXCLUDED_OPS:
        return None, True
    if not node.children:
        return None, False
    return trail(node.children[-1])


def norm_leaf(lf):
    if lf and lf.startswith("&"):
        d = b.decode_entity_ref(lf)
        return d if d else None
    return lf


def digits_of(lf, which):
    if lf is None or len(lf) != 1:
        return None
    e = stroke.get(lf)
    if not e:
        return None
    try:
        f_d, l_d = b.stroke_adapter(e[1])
    except Exception:
        return None
    if which == "F":
        return b.CLASS_TO_DIGIT.get(f_d)
    return b.CLASS_TO_DIGIT.get(l_d)


RESTRICT_OPS = set()  # per restriction


def run(name, require_leaf_ok, exclude_ops, also_ops=None):
    exclude_ops = exclude_ops or set()
    chk = 0
    agr = 0
    for ch, seq in seqmap.items():
        if ch not in cn_map or ch not in stroke:
            continue
        try:
            segs = b.parse_stroke_segments(seq)
        except Exception:
            continue
        if not segs[0][1] and not segs[-1][1]:
            continue
        need_f = bool(segs[0][1])
        need_l = bool(segs[-1][1])
        raw = ids_raw.get(ch)
        if not raw:
            continue
        tree = b.parse_ids(raw)
        if tree is None or isinstance(tree, str):
            continue
        if also_ops is not None and tree.op not in also_ops:
            continue
        if tree.op in exclude_ops:
            continue
        tf_c = b._name_to_class_digit(cn_map[ch][0])
        tl_c = b._name_to_class_digit(cn_map[ch][-1])
        if need_f and tf_c is None:
            need_f = False
        if need_l and tl_c is None:
            need_l = False
        if not need_f and not need_l:
            continue
        leaf_f = norm_leaf(lead(tree)[0])
        leaf_l = norm_leaf(trail(tree)[0])
        if require_leaf_ok:
            if need_f and not leaf_ok.get(leaf_f, False):
                need_f = False
            if need_l and not leaf_ok.get(leaf_l, False):
                need_l = False
            if not need_f and not need_l:
                continue
        ok = True
        if need_f:
            dgt = digits_of(leaf_f, "F")
            if dgt is None:
                continue
            ok = ok and dgt == tf_c
        if need_l:
            dgt = digits_of(leaf_l, "L")
            if dgt is None:
                continue
            ok = ok and dgt == tl_c
        chk += 1
        if ok:
            agr += 1
    rate = agr * 100.0 / chk if chk else 0.0
    print(f"{name:58s} {agr:5d}/{chk:5d} = {rate:6.2f}%  err={100-rate:.2f}%")


print("== combined F+L agreement under restrictions (cnchar = ground truth) ==")
run("base: leading-for-F, trailing-for-L, all ops", False, set())
run("R1: exclude wrap ops ⿺⿹", False, set("⿺⿹"))
run("R2: exclude ⿺⿹ + ⿸⿶⿷⿵⿴⿻(keep ⿰⿱⿲⿳)", False, None,
    also_ops=set("⿰⿱⿲⿳"))
run("R3: leaf must be cnchar-covered AND agree (verified leaf)", True, set())
run("R4: R3 + exclude ⿺⿹", True, set("⿺⿹"))
run("R5: R3 + only ⿰⿱⿲⿳", True, set(), also_ops=set("⿰⿱⿲⿳"))
