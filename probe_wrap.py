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
        for letter in letters:
            info = table.get(letter)
            if not info or not info.get("name"):
                ok = False
                break
            nm = str(info["name"]).split("|")[0].strip()
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

seq_map = {}
with open(CACHE / "codepoint-character-sequence.txt", encoding="utf-8") as f:
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3 and p[0].startswith("U+"):
            try:
                seq_map[chr(int(p[0][2:], 16))] = p[2].strip()
            except ValueError:
                pass

# loader WITH ids (Pass4b active)
stroke = b.load_stroke_order_data(
    CACHE / "codepoint-character-sequence.txt",
    CACHE / "ucs-strokes.txt",
    CACHE / "cnchar-stroke-table.json",
    [CACHE / "cnchar-stroke-order-jian.json", CACHE / "cnchar-stroke-order-trad.json"],
    CACHE / "ids.txt",
)


def walk(node, first):
    if isinstance(node, str):
        return node, False
    if node.op in b.IDS_EXCLUDED_OPS:
        return None, True
    if not node.children:
        return None, False
    return walk(node.children[0 if first else -1], first)


def verified_digits(leaf, self_ch):
    if leaf is None:
        return None, "no_leaf"
    if leaf.startswith("&"):
        d = b.decode_entity_ref(leaf)
        leaf = d if d else None
    if (
        leaf is None
        or len(leaf) != 1
        or leaf == self_ch
        or leaf in b.PLACEHOLDER_CHARS
        or not b.is_cjk_leaf(leaf)
    ):
        return None, "no_leaf"
    entry = stroke.get(leaf)
    if entry is None:
        return None, "no_leaf"
    if leaf not in cn_map:
        return None, "unverified"
    try:
        f_d, l_d = b.stroke_adapter(entry[1])
    except Exception:
        return None, "no_leaf"
    tf = b.CLASS_TO_DIGIT.get(f_d)
    tl = b.CLASS_TO_DIGIT.get(l_d)
    cf = b._name_to_class_digit(cn_map[leaf][0])
    cl = b._name_to_class_digit(cn_map[leaf][-1])
    if not tf or not tl or cf is None or cl is None:
        return None, "unverified"
    if tf != cf or tl != cl:
        return None, "unverified"
    return (tf, tl), "ok"


# validation: cnchar-covered group chars, rule-as-applied (R3 gates),
# split by root op in {⿺,⿹} vs others
from collections import defaultdict

stats = defaultdict(lambda: [0, 0])  # bucket -> [agree, checked]
skip = defaultdict(int)
for ch, seq in seq_map.items():
    if ch not in cn_map or ch not in stroke:
        skip["not_in_cn_or_stroke"] += 1
        continue
    try:
        segs = b.parse_stroke_segments(seq)
    except Exception:
        skip["seg_parse"] += 1
        continue
    if not segs[0][1] and not segs[-1][1]:
        skip["no_group"] += 1
        continue
    need_f = bool(segs[0][1])
    need_l = bool(segs[-1][1])
    raw = ids_raw.get(ch)
    if not raw:
        skip["no_ids"] += 1
        continue
    tree = b.parse_ids(raw)
    if tree is None:
        skip["ids_parse_none"] += 1
        continue
    if isinstance(tree, str):
        skip["ids_str"] += 1
        continue
    op = tree.op
    leaf_f, ex_f = walk(tree, True)
    leaf_l, ex_l = walk(tree, False)
    if (need_f and ex_f) or (need_l and ex_l):
        skip["excluded_op"] += 1
        continue
    tf_c = b._name_to_class_digit(cn_map[ch][0])
    tl_c = b._name_to_class_digit(cn_map[ch][-1])
    if need_f and tf_c is None:
        skip["cnchar_first_unmappable"] += 1
        continue
    if need_l and tl_c is None:
        skip["cnchar_last_unmappable"] += 1
        continue
    dig_f = (None, "ok")
    dig_l = (None, "ok")
    if need_f:
        dig_f = verified_digits(leaf_f, ch)
        if dig_f[1] != "ok":
            skip["leafF_" + dig_f[1]] += 1
            continue
    if need_l:
        dig_l = verified_digits(leaf_l, ch)
        if dig_l[1] != "ok":
            skip["leafL_" + dig_l[1]] += 1
            continue
    bucket = "WRAP_⿺⿹" if op in ("⿺", "⿹") else "OTHER"
    stats[bucket][1] += 1
    ok = True
    if need_f and dig_f[0][0] != tf_c:
        ok = False
    if need_l and dig_l[0][1] != tl_c:
        ok = False
    if ok:
        stats[bucket][0] += 1

print("=== skip reasons ===")
for k, v in sorted(skip.items(), key=lambda x: -x[1]):
    print(f"{k}: {v}")
print("=== rule-as-applied validation by root op (cnchar ground truth) ===")

print("=== rule-as-applied validation by root op (cnchar ground truth) ===")
total_a = total_c = 0
for bucket in sorted(stats):
    a, c = stats[bucket]
    total_a += a
    total_c += c
    rate = a * 100.0 / c if c else 0.0
    print(f"{bucket:10s}: {a:4d}/{c:4d} = {rate:6.2f}%  err={100-rate:.2f}%")
if total_c:
    print(f"{'TOTAL':10s}: {total_a}/{total_c} = {total_a*100.0/total_c:.2f}%")
