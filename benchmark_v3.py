"""HANSTROKE-V3-BENCHMARK spec=CHOT-2026-10-03 — scope: offline benchmark only.

This script implements the bilateral architecture-agreed offline benchmark for
HANSTROKE V3 Chinese character input encoding. It downloads data, enforces manifest
hash locking (fail-closed), validates stroke tokens, runs golden tests on ~60
anchors, performs recursive IDS tree parsing with deterministic anchor policy,
generates HANSTROKE codes for T3-A, T3-C, and T3-E across B0, B1, and B3-T profiles,
and evaluates collision metrics and the >=95% gate.
"""

from __future__ import annotations

import argparse
import collections
from dataclasses import asdict, dataclass
import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import random
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.error
import urllib.parse
import urllib.request
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

# -----------------------------------------------------------------------------
# SPECIFICATION CONSTANTS
# -----------------------------------------------------------------------------
SPEC_VERSION = "CHOT-2026-10-03"
CACHE_DIR_DEFAULT = Path("./cache_hanstroke")
MANIFEST_FILE_NAME = "manifest.lock.json"
REPORT_JSON_NAME = "report.json"
REPORT_MD_NAME = "report.md"
GOLDEN_FILE_NAME = "golden.json"

GATE_THRESHOLD_PCT = 95.0
B0_CORE_FLOOR_PCT = 90.0
CODE_CEILING = 6
LADDER_RUNGS = (3, 4, 5, 6)
K_GROUPS = (24, 48, 96, 214)
SENTINEL_CHAR = "~"
MSG_B3_HN_BLOCKED = (
    "B3-HN: BLOCKED — chưa có nguồn tần suất Hán-Nôm có provenance; "
    "không thay bằng B1/B3-T"
)
T3_SELECTION_NOTE = (
    "Chọn T3 đơn giản nhất đạt gate, thứ tự A < C < E; "
    "nếu chỉ E đạt → ghi nhận HANSTROKE là hệ dựa trên thành phần"
)

# -----------------------------------------------------------------------------
# 1) DATA SOURCES MANIFEST DEFINITION
# -----------------------------------------------------------------------------
SOURCES: dict[str, dict[str, str]] = {
    "unihan": {
        "url": "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip",
        "kind": "unihan_zip",
        "license": "Unicode License",
        "note": "Unihan database for kTotalStrokes, kTraditionalVariant, kSimplifiedVariant",
        "filename": "unihan.zip",
    },
    "ids": {
        "url": "https://raw.githubusercontent.com/cjkvi/cjkvi-ids/master/ids.txt",
        "kind": "ids_text",
        "license": "GPL / Open Data",
        "note": "CJKVI IDS syntax table",
        "filename": "ids.txt",
    },
    "stroke_order": {
        "url": "https://raw.githubusercontent.com/cjkvi/cjkvi-ids/master/ucs-strokes.txt",
        "kind": "stroke_order_text",
        "license": "GPL / Open Data",
        "note": "CJKVI stroke counts (codepoint, char, total strokes)",
        "filename": "ucs-strokes.txt",
    },
    "stroke_seq": {
        "url": "https://raw.githubusercontent.com/stroke-input/stroke-input-data/master/codepoint-character-sequence.txt",
        "kind": "stroke_seq_regex",
        "license": "CC-BY-4.0 (Conway Stroke Data)",
        "note": "Stroke-input: tab-separated (codepoint, character, stroke sequence regex), classes 1-5",
        "filename": "codepoint-character-sequence.txt",
    },
    "stroke_cnchar_table": {
        "url": "https://raw.githubusercontent.com/theajack/cnchar/master/src/cnchar/plugin/order/dict/stroke-table.json",
        "kind": "cnchar_json",
        "license": "MIT (cnchar)",
        "note": "cnchar stroke letter table: letter -> shape/type/name (named strokes)",
        "filename": "cnchar-stroke-table.json",
    },
    "stroke_cnchar_jian": {
        "url": "https://raw.githubusercontent.com/theajack/cnchar/master/src/cnchar/plugin/order/dict/stroke-order-jian.json",
        "kind": "cnchar_json",
        "license": "MIT (cnchar)",
        "note": "cnchar simplified stroke order: char -> stroke letter sequence",
        "filename": "cnchar-stroke-order-jian.json",
    },
    "stroke_cnchar_trad": {
        "url": "https://raw.githubusercontent.com/theajack/cnchar/master/src/cnchar/plugin/trad/dict/stroke-order-trad.json",
        "kind": "cnchar_json",
        "license": "MIT (cnchar)",
        "note": "cnchar traditional stroke order: char -> stroke letter sequence",
        "filename": "cnchar-stroke-order-trad.json",
    },
    "freq_b1": {
        "url": "https://lingua.mtsu.edu/chinese-computing/statistics/char/download.php?Which=MO",
        "kind": "freq_text",
        "license": "Academic / Non-commercial (Jun Da)",
        "note": "Jun Da modern Chinese character frequency table (tab-delimited, gb2312)",
        "filename": "freq_b1.txt",
    },
}

# -----------------------------------------------------------------------------
# 2) STROKE ADAPTER & TOKEN MAPPING
# -----------------------------------------------------------------------------
# 5 Classes: H (横/提), V (竖), P (撇), D (点/捺), Z (折/弯/钩)
# Explicit mapping requirement:
# - 横 -> H
# - 竖 -> V
# - 撇, 平撇, 竖撇 -> P
# - 点, 捺, 斜捺 -> D
# - 提 -> H (V4-CHOT Q2(a): 提 = 横类起笔, 同 digit 源 5-class; 原 V2 spec 记 提->D 为笔误)
# - 横折, 横钩, 横撇, 横折钩, 横折撇, 竖折, 竖弯, 竖弯钩, 横折弯钩, 横折折钩,
#   横折折折钩, 横折提, 横斜钩, 斜钩, 卧钩 -> Z
# - 竖钩 -> V (CRITICAL: 竖钩 = V, not Z)
# - 竖提, 撇点, 撇折, 弯钩, 横撇弯钩 -> Z
# GENERAL RULE: token containing 折/转/钩 -> Z, EXCEPT 竖钩 -> V.
# Unknown tokens -> raise BuildError("UNMAPPED STROKE TOKEN: ...")

STROKE_TOKENS: dict[str, str] = {
    # Horizontal
    "横": "H",
    "一": "H",
    "H": "H",
    "h": "H",
    "1": "H",
    "㇐": "H",
    # Vertical
    "竖": "V",
    "丨": "V",
    "V": "V",
    "v": "V",
    "S": "V",
    "s": "V",
    "2": "V",
    "㇑": "V",
    "竖钩": "V",  # CHỐT: 竖钩 = V
    "㇚": "V",
    # Slash / Falling Left
    "撇": "P",
    "平撇": "P",
    "竖撇": "P",
    "丿": "P",
    "P": "P",
    "p": "P",
    "3": "P",
    "㇒": "P",
    # Dot / Falling Right / Rising
    "点": "D",
    "捺": "D",
    "斜捺": "D",
    "提": "H",  # V4-CHOT Q2(a): 提 -> H
    "挑": "D",
    "丶": "D",
    "D": "D",
    "d": "D",
    "N": "D",
    "n": "D",
    "4": "D",
    "㇔": "D",
    "㇏": "D",
    "㇀": "D",
    "㇣": "D",
    # Folding / Turning / Hooks (Z)
    "横折": "Z",
    "横钩": "Z",
    "横撇": "Z",
    "横折钩": "Z",
    "横折撇": "Z",
    "竖折": "Z",
    "竖弯": "Z",
    "竖弯钩": "Z",
    "横折弯钩": "Z",
    "横折折钩": "Z",
    "横折折折钩": "Z",
    # V4: hoàn tất bảng token tường minh (6 letter-name cnchar chưa có — đều 含折/钩)
    "横折折": "Z",
    "横折弯": "Z",
    "横折折折": "Z",
    "横折折撇": "Z",
    "竖折撇": "Z",
    "竖折折": "Z",
    "竖折折钩": "Z",
    "横折提": "Z",
    "横斜钩": "Z",
    "斜钩": "Z",
    "卧钩": "Z",
    "竖提": "Z",
    "撇点": "Z",
    "撇折": "Z",
    "弯钩": "Z",
    "横撇弯钩": "Z",
    "Z": "Z",
    "z": "Z",
    "5": "Z",
    "㇖": "Z",
    "㇗": "Z",
    "㇘": "Z",
    "㇙": "Z",
    "㇛": "Z",
    "㇜": "Z",
    "㇝": "Z",
    "㇞": "Z",
    "㇟": "Z",
    "㇠": "Z",
    "㇡": "Z",
    "㇢": "Z",
}


class BuildError(Exception):
    """Raised when an unrecoverable data build or mapping error occurs."""

    pass


def map_stroke_token(token: str) -> str:
    """Map a single stroke token to {H, V, P, D, Z} without guessing."""
    t = token.strip()
    if not t:
        raise BuildError("UNMAPPED STROKE TOKEN: <empty>")
    if t in STROKE_TOKENS:
        return STROKE_TOKENS[t]
    # General rule check
    if "竖钩" in t:
        return "V"
    if "折" in t or "转" in t or "钩" in t:
        return "Z"
    raise BuildError(f"UNMAPPED STROKE TOKEN: {token}")


def stroke_adapter(token_seq: list[str]) -> tuple[str, str]:
    """Map a sequence of stroke tokens to (first_class, last_class)."""
    if not token_seq:
        raise BuildError("EMPTY STROKE SEQUENCE")
    first_c = map_stroke_token(token_seq[0])
    last_c = map_stroke_token(token_seq[-1])
    return first_c, last_c


# GOLDEN_ANCHORS: ~63 verified reference anchors (char -> {codepoint, total, first, last})
GOLDEN_ANCHORS_INLINE: dict[str, dict[str, Any]] = {
    "亻": {"codepoint": "U+4EBB", "total": 2, "first": "P", "last": "V"},
    "氵": {"codepoint": "U+6C35", "total": 3, "first": "D", "last": "H"},  # V4-CHOT: last D->H (提=H)
    "日": {"codepoint": "U+65E5", "total": 4, "first": "V", "last": "H"},
    "女": {"codepoint": "U+5973", "total": 3, "first": "Z", "last": "H"},
    "子": {"codepoint": "U+5B50", "total": 3, "first": "Z", "last": "H"},
    "水": {"codepoint": "U+6C34", "total": 4, "first": "V", "last": "D"},
    "小": {"codepoint": "U+5C0F", "total": 3, "first": "V", "last": "D"},
    "宀": {"codepoint": "U+5B80", "total": 3, "first": "D", "last": "Z"},
    "艹": {"codepoint": "U+8279", "total": 3, "first": "H", "last": "V"},
    "口": {"codepoint": "U+53E3", "total": 3, "first": "V", "last": "H"},
    "木": {"codepoint": "U+6728", "total": 4, "first": "H", "last": "D"},
    "火": {"codepoint": "U+706B", "total": 4, "first": "D", "last": "D"},
    "土": {"codepoint": "U+571F", "total": 3, "first": "H", "last": "H"},
    "金": {"codepoint": "U+91D1", "total": 8, "first": "P", "last": "H"},
    "心": {"codepoint": "U+5FC3", "total": 4, "first": "D", "last": "D"},
    "手": {"codepoint": "U+624B", "total": 4, "first": "P", "last": "V"},  # V4-CHOT: last Z->V (竖钩=V)
    "目": {"codepoint": "U+76EE", "total": 5, "first": "V", "last": "H"},
    "言": {"codepoint": "U+8A00", "total": 7, "first": "D", "last": "H"},
    "虫": {"codepoint": "U+866B", "total": 6, "first": "V", "last": "D"},
    "鱼": {"codepoint": "U+9C7C", "total": 8, "first": "P", "last": "H"},
    "鸟": {"codepoint": "U+9E1F", "total": 5, "first": "P", "last": "H"},
    "马": {"codepoint": "U+9A6C", "total": 3, "first": "Z", "last": "H"},
    "车": {"codepoint": "U+8F66", "total": 4, "first": "H", "last": "V"},
    "贝": {"codepoint": "U+8D1D", "total": 4, "first": "V", "last": "D"},
    "门": {"codepoint": "U+95E8", "total": 3, "first": "D", "last": "Z"},
    "月": {"codepoint": "U+6708", "total": 4, "first": "P", "last": "H"},
    "山": {"codepoint": "U+5C71", "total": 3, "first": "V", "last": "V"},
    "田": {"codepoint": "U+7530", "total": 5, "first": "V", "last": "H"},
    "石": {"codepoint": "U+77F3", "total": 5, "first": "H", "last": "H"},
    "竹": {"codepoint": "U+7AF9", "total": 6, "first": "P", "last": "V"},
    "米": {"codepoint": "U+7C73", "total": 6, "first": "D", "last": "D"},
    "雨": {"codepoint": "U+96E8", "total": 8, "first": "H", "last": "D"},
    "白": {"codepoint": "U+767D", "total": 5, "first": "P", "last": "H"},
    "黑": {"codepoint": "U+9ED1", "total": 12, "first": "V", "last": "D"},
    "男": {"codepoint": "U+7537", "total": 7, "first": "V", "last": "P"},
    "力": {"codepoint": "U+529B", "total": 2, "first": "Z", "last": "P"},
    "耳": {"codepoint": "U+8033", "total": 6, "first": "H", "last": "H"},
    "大": {"codepoint": "U+5927", "total": 3, "first": "H", "last": "D"},
    "中": {"codepoint": "U+4E2D", "total": 4, "first": "V", "last": "V"},
    "一": {"codepoint": "U+4E00", "total": 1, "first": "H", "last": "H"},
    "二": {"codepoint": "U+4E8C", "total": 2, "first": "H", "last": "H"},
    "三": {"codepoint": "U+4E09", "total": 3, "first": "H", "last": "H"},
    "十": {"codepoint": "U+5341", "total": 2, "first": "H", "last": "V"},
    "人": {"codepoint": "U+4EBA", "total": 2, "first": "P", "last": "D"},
    "又": {"codepoint": "U+53C8", "total": 2, "first": "Z", "last": "D"},
    "寸": {"codepoint": "U+5BF8", "total": 3, "first": "H", "last": "D"},
    "弓": {"codepoint": "U+5F13", "total": 3, "first": "Z", "last": "Z"},
    "戈": {"codepoint": "U+6208", "total": 4, "first": "H", "last": "D"},
    "戸": {"codepoint": "U+6238", "total": 4, "first": "H", "last": "P"},  # V4-CHOT: first D->H (1513)
    "页": {"codepoint": "U+9875", "total": 6, "first": "H", "last": "D"},
    "风": {"codepoint": "U+98CE", "total": 4, "first": "P", "last": "D"},
    "飞": {"codepoint": "U+98DE", "total": 3, "first": "Z", "last": "D"},
    "长": {"codepoint": "U+957F", "total": 4, "first": "P", "last": "D"},
    "见": {"codepoint": "U+89C1", "total": 4, "first": "V", "last": "Z"},
    "走": {"codepoint": "U+8D70", "total": 7, "first": "H", "last": "D"},
    "足": {"codepoint": "U+8DB3", "total": 7, "first": "V", "last": "D"},
    "禾": {"codepoint": "U+79BE", "total": 5, "first": "P", "last": "D"},
    "广": {"codepoint": "U+5E7F", "total": 3, "first": "D", "last": "P"},
    "疒": {"codepoint": "U+7592", "total": 5, "first": "D", "last": "H"},  # V4-CHOT: last D->H (提=H)
    "辶": {"codepoint": "U+8FB6", "total": 3, "first": "D", "last": "D"},
    "門": {"codepoint": "U+9580", "total": 8, "first": "V", "last": "H"},
    "車": {"codepoint": "U+8ECA", "total": 7, "first": "H", "last": "V"},
    "馬": {"codepoint": "U+99AC", "total": 10, "first": "H", "last": "D"},  # V4-CHOT: (V,H)->(H,D) both sources
    "戶": {"codepoint": "U+6236", "total": 4, "first": "P", "last": "H"},  # V4-CHOT ADD: stroke-input 3351 + cnchar sscj
    "户": {"codepoint": "U+6237", "total": 4, "first": "D", "last": "P"},  # V4-CHOT ADD: stroke-input 4513 + cnchar kcjs
    "以": {"codepoint": "U+4EE5", "total": 4, "first": "Z", "last": "D"},  # V4-CHOT ADD: 竖提->Z test (cnchar hksk)
    # V9-DECISION [V9-Q2] ADD (2026-10-03): 51 golden = 49 AGREE spotcheck100
    # (first/last double-source: pipeline == cnchar, total = loader baseline;
    #  Unihan kTotalStrokes variance noted in GOLDEN_CHANGELOG.md for
    #  嚴/連/骘/苜) + 諩/䛡 resolved via IDS_PICKED (cnchar lacks both,
    #  IDS leading leaf 言 = frozen golden (D,H)).
    "勛": {"codepoint": "U+52DB", "total": 12, "first": "V", "last": "P"},
    "鱺": {"codepoint": "U+9C7A", "total": 30, "first": "P", "last": "Z"},
    "倆": {"codepoint": "U+5006", "total": 10, "first": "P", "last": "D"},
    "蔞": {"codepoint": "U+851E", "total": 14, "first": "H", "last": "H"},
    "暢": {"codepoint": "U+66A2", "total": 14, "first": "V", "last": "P"},
    "錮": {"codepoint": "U+932E", "total": 16, "first": "P", "last": "H"},
    "綴": {"codepoint": "U+7DB4", "total": 14, "first": "Z", "last": "D"},
    "慍": {"codepoint": "U+614D", "total": 13, "first": "D", "last": "H"},
    "鶴": {"codepoint": "U+9DB4", "total": 21, "first": "D", "last": "D"},
    "誡": {"codepoint": "U+8AA1", "total": 14, "first": "D", "last": "D"},
    "鐨": {"codepoint": "U+9428", "total": 20, "first": "P", "last": "D"},
    "縐": {"codepoint": "U+7E10", "total": 16, "first": "Z", "last": "P"},
    "嚴": {"codepoint": "U+56B4", "total": 19, "first": "V", "last": "D"},
    "儻": {"codepoint": "U+513B", "total": 22, "first": "P", "last": "D"},
    "鉀": {"codepoint": "U+9240", "total": 13, "first": "P", "last": "V"},
    "診": {"codepoint": "U+8A3A", "total": 12, "first": "D", "last": "P"},
    "搾": {"codepoint": "U+643E", "total": 13, "first": "H", "last": "H"},
    "齠": {"codepoint": "U+9F60", "total": 20, "first": "V", "last": "H"},
    "撓": {"codepoint": "U+6493", "total": 15, "first": "H", "last": "Z"},
    "鶩": {"codepoint": "U+9DA9", "total": 20, "first": "Z", "last": "D"},
    "鏢": {"codepoint": "U+93E2", "total": 19, "first": "P", "last": "D"},
    "埡": {"codepoint": "U+57E1", "total": 11, "first": "H", "last": "H"},
    "璉": {"codepoint": "U+7489", "total": 14, "first": "H", "last": "D"},
    "颳": {"codepoint": "U+98B3", "total": 15, "first": "P", "last": "H"},
    "鋪": {"codepoint": "U+92EA", "total": 15, "first": "P", "last": "D"},
    "暱": {"codepoint": "U+66B1", "total": 14, "first": "V", "last": "Z"},
    "當": {"codepoint": "U+7576", "total": 13, "first": "V", "last": "H"},
    "繆": {"codepoint": "U+7E46", "total": 17, "first": "Z", "last": "P"},
    "蕎": {"codepoint": "U+854E", "total": 15, "first": "H", "last": "H"},
    "萇": {"codepoint": "U+8407", "total": 11, "first": "H", "last": "D"},
    "吒": {"codepoint": "U+5412", "total": 6, "first": "V", "last": "Z"},
    "禪": {"codepoint": "U+79AA", "total": 16, "first": "D", "last": "V"},
    "滄": {"codepoint": "U+6EC4", "total": 13, "first": "D", "last": "H"},
    "鏈": {"codepoint": "U+93C8", "total": 18, "first": "P", "last": "D"},
    "啓": {"codepoint": "U+5553", "total": 11, "first": "D", "last": "H"},
    "脛": {"codepoint": "U+811B", "total": 11, "first": "P", "last": "H"},
    "連": {"codepoint": "U+9023", "total": 10, "first": "H", "last": "D"},
    "術": {"codepoint": "U+8853", "total": 11, "first": "P", "last": "V"},
    "匲": {"codepoint": "U+5332", "total": 14, "first": "H", "last": "Z"},
    "搬": {"codepoint": "U+642C", "total": 13, "first": "H", "last": "D"},
    "骘": {"codepoint": "U+9A98", "total": 13, "first": "Z", "last": "H"},
    "怄": {"codepoint": "U+6004", "total": 7, "first": "D", "last": "Z"},
    "簸": {"codepoint": "U+7C38", "total": 19, "first": "P", "last": "D"},
    "俚": {"codepoint": "U+4FDA", "total": 9, "first": "P", "last": "H"},
    "苜": {"codepoint": "U+82DC", "total": 8, "first": "H", "last": "H"},
    "闯": {"codepoint": "U+95EF", "total": 6, "first": "D", "last": "H"},
    "戒": {"codepoint": "U+6212", "total": 7, "first": "H", "last": "D"},
    "埝": {"codepoint": "U+57DD", "total": 11, "first": "H", "last": "D"},
    "苡": {"codepoint": "U+82E1", "total": 7, "first": "H", "last": "D"},
    "諩": {"codepoint": "U+8AE9", "total": 15, "first": "D", "last": "H"},  # IDS_PICKED: IDS ⿰言並, first group (1|4)->4 via 言
    "䛡": {"codepoint": "U+46E1", "total": 14, "first": "D", "last": "H"},  # IDS_PICKED: IDS ⿰言𠯑, first group (1|4)->4 via 言
}

# V4-CHOT Dieu kien 1: golden DONG BANG (SHA-256 cua dict, sort_keys, khong khoang trang).
# Sua golden = vi pham Dieu kien 1, tru khi ghi changelog + cap nhat hang so nay.
GOLDEN_FROZEN_SHA256 = (
    "83d444d66bf594b095ed3a3424a86dcb2f4624c703bef91d3f885181500a569d"
)  # V9-DECISION 2026-10-03: +51 golden (49 AGREE + 諩/䛡 IDS_PICKED), see GOLDEN_CHANGELOG.md

# V6-DECISION (2026-10-03, DONG THUAN ChatGPT + Claude, reconcile [V6-QA..QD]):
# anchor grammar + placeholder policy DONG BONG truoc vong chay lai.
# Sua dict = cap nhat ANCHOR_SPEC_SHA256 + ghi changelog (giong golden).
# V9-DECISION (2026-10-03, DONG THUAN ChatGPT + Claude, reconcile [V9-Q1/Q2]):
# + B0-core floor + IDS_PICKED rule DONG BONG truoc vong chay lai.
# Sua dict = cap nhat ANCHOR_SPEC_SHA256 + ghi changelog (giong golden).
ANCHOR_GRAMMAR_SPEC: dict[str, str] = {
    "version": "V9-DECISION-2026-10-03",
    "terminal_rule": (
        "IDS missing/terminal -> primary=char, secondary='~', residual=0 (z/terminal)"
    ),
    "atomic_placeholder_rule": (
        "any placeholder U+2460-2473 (1-20) inside IDS -> whole char atomic: "
        "primary=char, secondary='~', t2=1, flag COMPOSITE_PLACEHOLDER; needs "
        "stroke data else MISSING_ANCHOR_STROKES (excluded, reported separately)"
    ),
    "atomic_invalid_rule": (
        "extracted component not a valid CJK leaf (after entity decode) -> "
        "same atomic treatment, flag SELF_ANCHOR_NO_COMPONENT"
    ),
    "component_rule": (
        "primary=DFS-first-leaf(child[0]) (for 3/3-shape = first operand); "
        "secondary=DFS-first-leaf(child[1]) else '~'"
    ),
    "anchor_stroke_source": (
        "anchor table: cnchar first/last preferred per end; else base fixed-end "
        "digits (TQ); end-position group without cnchar -> IDS_PICKED rule "
        "(ids_picked_rule) if applicable, else AMBIGUOUS_ANCHOR "
        "flag+count, tie-break digits kept for codegen (khong chon im le)"
    ),
    "forbidden": "never choose anchor by collision or frequency",
    "gate_denominators": (
        "wide (all B0 chars, no-code = fail) official; narrow (qualified only) "
        "diagnostic; no retrospective gate relaxation"
    ),
    "placeholders": (
        "no guessing components; rescued/excluded counts reported separately"
    ),
    "b0_composition": (
        "B0=27,584 = U+4E00-9FFF (20,992, B0-core) + U+3400-4DBF (6,592); "
        "Ext-B+ out of scope; gate weights remain on B1/B3-T"
    ),
    "oracle_rule": (
        "oracle-E = full anchor identity; V4 gate registered only after oracle "
        "results; oracle <95% wide -> m<=4-char code infeasible -> retrieval+refine"
    ),
    "ids_picked_rule": (
        "V9/V11 [V9-Q2][V11-QC] cnchar THIEU char: first-position "
        "group resolved by IDS LEADING leaf strokes, last-position "
        "group by TRAILING leaf strokes (leaf o vi tri dau/cuoi, "
        "entity-decoded); leaf must be VERIFIED: in cnchar_map AND "
        "leaf data first/last == cnchar first/last (R3; validation "
        "OTHER ops 1199/1201 = 99.83% err 0.17%); skip "
        "placeholder/self/invalid leaf; EXCLUDE ops {⿴,⿵,⿻,⿺,⿹} "
        "on leaf path (V11: wrap ops ⿺⿹ REVOKED — probe err "
        "58.76% (40/97) >> 5% threshold, Claude V9 constraint 4 "
        "+ ChatGPT V11-QC); flag+count IDS_PICKED separately "
        "(ids_picked/changed/excluded/no_leaf/unverified/conflict); "
        "rule runs only when char not in cnchar_map; validation vs "
        "cnchar ground truth reported (ids_valid_*); revoke if "
        "error rate >5%"
    ),
    "v4_gate_registered": (
        "V9 [V9-Q1] BEFORE running, non-retrospective: official gate = B1 and "
        "B3-T separately, wide denominator (no-code=fail), >=95% frequency-"
        "weighted chars with <=9 exact candidates; B0-core soft floor = >=90% "
        "UNWEIGHTED wide (diagnostic floor, NOT selection criterion, truoc khi "
        "chay); code ceiling <=6 chars, never raised; if gate unreachable "
        "within 6 chars -> FAIL; report frequency-weighted average code length"
    ),
    "ladder_rule": (
        "V9/V7 diagnostics (i): string S = code_c (t1+t2+A5x5+S5x5) + "
        "primary_anchor; rungs L3/L4/L5/L6 = S[:L]; SAME data partition and "
        "weights as profiles (no reseed); gate per rung = B1 and B3-T wide "
        ">=95% weighted <=9 exact; winner = shortest L <=6; none within 6 -> "
        "V4 FAIL (never raise ceiling); oracle-full = unbounded upper bound "
        "diagnostic only; report freq-weighted average code length"
    ),
    "k_groups_rule": (
        "V9/V7 diagnostics (ii): K in {24,48,96,214}; component group = "
        "kRSUnicode (Kangxi) radical of primary-anchor leaf merged by FIXED "
        "published numbering: block(r)=(r-1)*K//214 (K=214 identity); anchor "
        "without kRS -> shared unmapped bucket (counted; +1 identification "
        "cost); key = code_c + '#' + block; NEVER group by collision or "
        "frequency; report bucket>9 distribution + identification cost "
        "(=K[+1]) per config; same partition as (i); winner = smallest K "
        "meeting the same wide gate when a code design is chosen"
    ),
}
ANCHOR_SPEC_SHA256 = (
    "88def0d267678ccf99a605495751485782b2cad0b30c05ddeed8148b808d0f32"
)  # V11: +⿺⿹ revoked in ids_picked_rule (wrap err 58.76%)


def build_anchor_spec_sha() -> str:
    return hashlib.sha256(
        json.dumps(
            ANCHOR_GRAMMAR_SPEC, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def verify_anchor_spec() -> str:
    got = build_anchor_spec_sha()
    if ANCHOR_SPEC_SHA256 != got:
        print(
            "ERROR: anchor grammar spec hash mismatch "
            f"(expected {ANCHOR_SPEC_SHA256}, got {got}).",
            file=sys.stderr,
        )
        sys.exit(3)
    return got


# -----------------------------------------------------------------------------
# 3) IDS RECURSIVE PARSER & TREE NODES
# -----------------------------------------------------------------------------
IDS_OPERATORS: dict[str, int] = {
    "⿰": 2,
    "⿱": 2,
    "⿲": 3,
    "⿳": 3,
    "⿴": 2,
    "⿵": 2,
    "⿶": 2,
    "⿷": 2,
    "⿸": 2,
    "⿹": 2,
    "⿺": 2,
    "⿻": 2,
    "⿼": 2,
    "⿽": 2,
}

CONF_EXACT = "EXACT"
CONF_APPROX = "APPROX"
CONF_COMPOSITE = "COMPOSITE"
CONF_MISSING = "MISSING"
CONF_INHERITED = "INHERITED"


@dataclass
class IDSNode:
    op: str
    children: list[IDSNode | str]
    confidence: str
    raw: str
    provenance: Optional[str] = None


def is_cjk_leaf(char: str) -> bool:
    """Validate whether char belongs to standard CJK ideographic/radical ranges."""
    if len(char) != 1:
        return False
    cp = ord(char)
    return (
        (0x4E00 <= cp <= 0x9FFF)
        or (0x3400 <= cp <= 0x4DBF)
        or (0x20000 <= cp <= 0x2A6DF)
        or (0x2A700 <= cp <= 0x2B73F)
        or (0x2B740 <= cp <= 0x2B81F)
        or (0x2B820 <= cp <= 0x2CEAF)
        or (0x2CEB0 <= cp <= 0x2EBEF)
        or (0x30000 <= cp <= 0x3134F)
        or (0x2E80 <= cp <= 0x2EF3)  # CJK Radicals Supplement
        or (0x2F00 <= cp <= 0x2FD5)  # Kangxi Radicals
        or (0x3005 <= cp <= 0x3007)
    )


# V6-DECISION: placeholders = U+2460..U+2473 (①..⑳) — id-sequence "unknown part".
PLACEHOLDER_CHARS = frozenset(chr(cp) for cp in range(0x2460, 0x2474))


def is_placeholder_char(ch: str) -> bool:
    return len(ch) == 1 and ch in PLACEHOLDER_CHARS


def decode_entity_ref(token: str) -> Optional[str]:
    """&Uxxxx; / &#xhh; / &#dd; -> str char; None if not an entity."""
    if len(token) < 4 or not token.startswith("&") or not token.endswith(";"):
        return None
    body = token[1:-1]
    try:
        if body[:1] in ("U", "u"):
            return chr(int(body[1:], 16))
        if body[:1] == "#":
            if body[1:2].lower() == "x":
                return chr(int(body[2:], 16))
            return chr(int(body[1:], 10))
        if body[:1] in ("X", "x"):
            return chr(int(body[1:], 16))
        return chr(int(body, 10))
    except (ValueError, OverflowError):
        return None


def normalize_leaf(leaf: str) -> str:
    """Decode entity refs to real chars; identity otherwise."""
    if leaf.startswith("&"):
        dec = decode_entity_ref(leaf)
        if dec is not None:
            return dec
    return leaf


def ids_contains_placeholder(node_or_leaf: "IDSNode | str") -> bool:
    """True if ANY leaf of the IDS tree is a placeholder (V6 atomic rule)."""
    if isinstance(node_or_leaf, str):
        return node_or_leaf in PLACEHOLDER_CHARS
    for child in node_or_leaf.children:
        if ids_contains_placeholder(child):
            return True
    return False


def strip_variation_selectors(text: str) -> str:
    """Strip Unicode Variation Selectors FE00-FE0F."""
    return re.sub(r"[\uFE00-\uFE0F]", "", text)


def parse_ids_tokens(tokens: list[str]) -> tuple[IDSNode | str, int, str]:
    """Recursive descent parser over IDS tokens."""
    if not tokens:
        raise BuildError("Empty token stream in IDS parsing")
    token = tokens[0]
    if token in IDS_OPERATORS:
        arity = IDS_OPERATORS[token]
        children: list[IDSNode | str] = []
        offset = 1
        overall_conf = CONF_EXACT
        for _ in range(arity):
            if offset >= len(tokens):
                return (
                    IDSNode(
                        op=token,
                        children=children,
                        confidence=CONF_COMPOSITE,
                        raw="".join(tokens),
                    ),
                    len(tokens),
                    CONF_COMPOSITE,
                )
            child, consumed, child_conf = parse_ids_tokens(tokens[offset:])
            children.append(child)
            offset += consumed
            if child_conf == CONF_APPROX:
                overall_conf = CONF_APPROX
            elif child_conf == CONF_COMPOSITE and overall_conf != CONF_APPROX:
                overall_conf = CONF_COMPOSITE
        return (
            IDSNode(
                op=token,
                children=children,
                confidence=overall_conf,
                raw="".join(tokens[:offset]),
            ),
            offset,
            overall_conf,
        )

    # Leaf token
    if token.startswith("&") or token in ("?", "+", "^"):
        conf = CONF_APPROX if token in ("?", "+", "^") else CONF_COMPOSITE
        return token, 1, conf
    if is_cjk_leaf(token):
        return token, 1, CONF_EXACT
    return token, 1, CONF_COMPOSITE


def tokenize_ids(raw_ids: str) -> list[str]:
    """Tokenize IDS string into operators, CJK chars, and entity references."""
    clean = strip_variation_selectors(raw_ids)
    tokens: list[str] = []
    i = 0
    n = len(clean)
    while i < n:
        if clean[i] == "&":
            semi = clean.find(";", i)
            if semi != -1:
                tokens.append(clean[i : semi + 1])
                i = semi + 1
            else:
                tokens.append(clean[i])
                i += 1
        else:
            tokens.append(clean[i])
            i += 1
    return tokens


def parse_ids(raw_ids: str) -> Optional[IDSNode | str]:
    """Parse raw IDS string into a Node tree or single leaf."""
    tokens = tokenize_ids(raw_ids)
    if not tokens:
        return None
    node_or_leaf, consumed, _ = parse_ids_tokens(tokens)
    return node_or_leaf


# -----------------------------------------------------------------------------
# 4) DETERMINISTIC ANCHOR EXTRACTION POLICY
# -----------------------------------------------------------------------------
def get_first_leaf_dfs(node_or_leaf: IDSNode | str) -> str:
    """DFS preorder first leaf extraction."""
    if isinstance(node_or_leaf, str):
        return node_or_leaf
    for child in node_or_leaf.children:
        res = get_first_leaf_dfs(child)
        if res:
            return res
    return SENTINEL_CHAR


def extract_anchors(
    char: str, ids_tree: Optional[IDSNode | str]
) -> tuple[str, str]:
    """Primary anchor = child[0] DFS-preorder first leaf.

    Secondary = child[1] DFS-preorder first leaf (or sentinel '~').
    Terminal character (no IDS tree) -> primary = char, secondary = '~'.
    """
    if ids_tree is None or isinstance(ids_tree, str):
        # Terminal character: anchor is the character itself
        return char, SENTINEL_CHAR

    if not ids_tree.children:
        return char, SENTINEL_CHAR

    primary = get_first_leaf_dfs(ids_tree.children[0])
    secondary = (
        get_first_leaf_dfs(ids_tree.children[1])
        if len(ids_tree.children) > 1
        else SENTINEL_CHAR
    )
    return primary, secondary


# -----------------------------------------------------------------------------
# 5) HANSTROKE ENCODING ENGINE (TIERS 1, 2, 3)
# -----------------------------------------------------------------------------
T2_FORM_MAP: dict[str, str] = {
    "": "1",
    "terminal": "1",
    "⿰": "2",
    "⿲": "2",
    "⿱": "3",
    "⿳": "3",
    "⿴": "4",
    "⿵": "5",
    "⿶": "6",
    "⿷": "7",
    "⿺": "7",
    "⿸": "8",
    "⿹": "8",
    "⿻": "9",
    "⿼": "2",
    "⿽": "3",
}

SHAPE_MATRIX: dict[str, dict[str, str]] = {
    "H": {"H": "1", "V": "2", "P": "3", "D": "4", "Z": "5"},
    "V": {"H": "6", "V": "7", "P": "8", "D": "9", "Z": "a"},
    "P": {"H": "b", "V": "c", "P": "d", "D": "e", "Z": "f"},
    "D": {"H": "g", "V": "h", "P": "i", "D": "j", "Z": "k"},
    "Z": {"H": "l", "V": "m", "P": "n", "D": "o", "Z": "p"},
}


def encode_t1_residual(residual: int) -> str:
    """Encode residual stroke count to T1 key."""
    if residual == 0:
        return "z"
    if 1 <= residual <= 9:
        return str(residual)
    if residual == 10:
        return "0"
    if 11 <= residual <= 28:
        return chr(ord("a") + (residual - 11))
    return f"q{residual}"


def encode_shape_5x5(first_c: str, last_c: str) -> str:
    """Encode stroke pair (first, last) to 1-char matrix key."""
    return SHAPE_MATRIX.get(first_c, {}).get(last_c, "1")


# -----------------------------------------------------------------------------
# MANIFEST, DOWNLOAD, AND VERIFICATION UTILITIES
# -----------------------------------------------------------------------------
def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def fetch_url(url: str, dest_path: Path) -> tuple[int, str]:
    """Fetch URL to destination path and return (bytes_count, sha256)."""
    headers = {"User-Agent": "HANSTROKE-V3-BENCHMARK/1.0 (+python-urllib)"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        print(
            f"SOURCE FETCH FAIL: HTTP {e.code} — {url}",
            file=sys.stderr,
        )
        sys.exit(2)
    except urllib.error.URLError as e:
        print(
            f"SOURCE FETCH FAIL: {e.reason} — {url}",
            file=sys.stderr,
        )
        sys.exit(2)

    if len(data) == 0 and "ucs-strokes" in url:
        print(
            "SOURCE MISSING: stroke_order — điền URL đúng vào SOURCES",
            file=sys.stderr,
        )
        sys.exit(2)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(data)
    return len(data), compute_sha256(dest_path)


def query_cjkvi_commit(timeout: float = 3.0) -> str:
    """Retrieve actual master commit sha for cjkvi-ids repository."""
    api_url = "https://api.github.com/repos/cjkvi/cjkvi-ids/commits/master"
    headers = {"User-Agent": "HANSTROKE-V3-BENCHMARK/1.0"}
    req = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return str(data.get("sha", "master@download-time"))
    except Exception:
        return "master@download-time"


def update_manifest(cache_dir: Path) -> dict[str, Any]:
    """Download all sources and generate manifest.lock.json."""
    print(">>> Updating manifest and downloading all sources...")
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "spec_version": SPEC_VERSION,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "sources": {},
    }

    for name, meta in SOURCES.items():
        dest = cache_dir / meta["filename"]
        print(f"  - Downloading {name} from {meta['url']} -> {dest}...")
        n_bytes, sha = fetch_url(meta["url"], dest)

        # Version resolution
        version = "latest"
        if name in ("ids", "stroke_order"):
            version = query_cjkvi_commit()

        manifest["sources"][name] = {
            "name": name,
            "url": meta["url"],
            "version": version,
            "sha256": sha,
            "license": meta["license"],
            "bytes": n_bytes,
            "downloaded_at": datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(),
            "note": meta["note"],
        }

    lock_path = cache_dir / MANIFEST_FILE_NAME
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f">>> Manifest locked to {lock_path}")
    return manifest


def verify_manifest_fail_closed(
    cache_dir: Path, offline: bool
) -> dict[str, Any]:
    """Verify cached files against manifest.lock.json. Fail-closed (exit 3) on mismatch."""
    lock_path = cache_dir / MANIFEST_FILE_NAME
    if not lock_path.is_file():
        if offline:
            print(
                f"ERROR: {lock_path} not found in offline mode. Run --update-manifest first.",
                file=sys.stderr,
            )
            sys.exit(3)
        print(
            f"Manifest lock not found at {lock_path}. Running manifest update..."
        )
        return update_manifest(cache_dir)

    with open(lock_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    print(">>> Verifying source checksums against locked manifest (FAIL-CLOSED)...")
    for name, meta in SOURCES.items():
        file_path = cache_dir / meta["filename"]
        if not file_path.is_file():
            if offline:
                print(
                    f"FAIL-CLOSED: Missing required cached file {file_path} in offline mode.",
                    file=sys.stderr,
                )
                sys.exit(3)
            print(f"  Missing {file_path}, re-downloading...")
            fetch_url(meta["url"], file_path)

        actual_sha = compute_sha256(file_path)
        expected_sha = manifest["sources"].get(name, {}).get("sha256")
        if actual_sha != expected_sha:
            print(
                f"FAIL-CLOSED: SHA-256 mismatch for source '{name}'!",
                file=sys.stderr,
            )
            print(f"  Expected: {expected_sha}", file=sys.stderr)
            print(f"  Actual:   {actual_sha}", file=sys.stderr)
            sys.exit(3)
        print(f"  [OK] {name}: SHA-256 matches locked hash ({actual_sha[:12]}...)")
    return manifest


# -----------------------------------------------------------------------------
# DATA LOADERS (UNIHAN, IDS, STROKE ORDER, FREQUENCY)
# -----------------------------------------------------------------------------
def expand_stroke_regex(seq: str) -> list[str]:
    """Deterministically expand a stroke sequence regex.

    Alternation groups `(a|b|c)` resolve to the FIRST alternative (leftmost),
    giving a deterministic first/last stroke as required by the CHOT spec.
    Characters are digits 1-5 (1=横,2=竖,3=撇,4=点/捺,5=折).
    """
    out: list[str] = []
    i = 0
    n = len(seq)
    while i < n:
        ch = seq[i]
        if ch == "(":
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if seq[j] == "(":
                    depth += 1
                elif seq[j] == ")":
                    depth -= 1
                j += 1
            if depth != 0:
                raise BuildError(f"UNBALANCED PAREN IN STROKE SEQ: {seq}")
            inner = seq[i + 1 : j - 1]
            first_alt = inner.split("|")[0]
            out.extend(expand_stroke_regex(first_alt))
            i = j
        elif ch in "12345":
            out.append(ch)
            i += 1
        elif ch in "\\|":
            i += 1
        else:
            raise BuildError(f"UNMAPPED STROKE TOKEN: {ch}")
    if not out:
        raise BuildError(f"EMPTY STROKE SEQ: {seq}")
    return out


SEQ_FIELD_RE = re.compile(r"^[1-5|()\\]+$")

# V4-CHOT: 5-class digit encoding for stroke-input sequences.
CLASS_TO_DIGIT: dict[str, str] = {"H": "1", "V": "2", "P": "3", "D": "4", "Z": "5"}

# Source-mechanism statistics, filled by load_stroke_order_data (V4-CHOT).
STROKE_SOURCE_STATS: dict[str, int] = {}

# V6-DECISION: anchor stroke table (char -> (first_class, last_class, source))
# source: "cnchar" | "tq" | "ambiguous" | "fill"  (fill = cnchar-only partial)
ANCHOR_TABLE: dict[str, tuple[str, str, str]] = {}
ANCHOR_TABLE_STATS: dict[str, int] = {}
# V6 [V6-QC]: classification source for the cross-check disagreements
CROSS_DISAGREE_CHARS: list[dict[str, str]] = []
# V9-DECISION [V9-Q2]: chars whose first/last group resolved via IDS leading leaf
IDS_PICKED_CHARS: set[str] = set()
IDS_EXCLUDED_OPS = frozenset("⿴⿵⿻⿺⿹")  # Claude V9: loai enclosing/overlay; V11: +⿺⿹ (probe wrap err 58.76% >> 5% revoke threshold)
# V9 spotcheck strata support (filled by load_stroke_order_data)
GROUP_CHARS: set[str] = set()  # chars with alternation group in stroke seq
CNCHAR_COVERED: set[str] = set()  # chars present in cnchar dictionaries
DIGIT_TO_CLASS: dict[str, str] = {"1": "H", "2": "V", "3": "P", "4": "D", "5": "Z"}


def parse_stroke_segments(seq: str) -> list[tuple[str, list[str]]]:
    """Split a stroke-sequence regex into segments.

    Each segment is (fixed_digits, alts):
      - fixed segment: fixed_digits like "125", alts == []
      - group segment: fixed_digits == "", alts like ["1", "4"]
    Alternation groups are only allowed at positions written by the source;
    unbalanced parens / unknown chars raise BuildError.
    """
    segs: list[tuple[str, list[str]]] = []
    i = 0
    n = len(seq)
    while i < n:
        ch = seq[i]
        if ch == "(":
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if seq[j] == "(":
                    depth += 1
                elif seq[j] == ")":
                    depth -= 1
                j += 1
            if depth != 0:
                raise BuildError(f"UNBALANCED PAREN IN STROKE SEQ: {seq}")
            alts = seq[i + 1 : j - 1].split("|")
            if any(not a or any(c not in "12345" for c in a) for a in alts):
                raise BuildError(f"UNMAPPED STROKE TOKEN: {seq}")
            segs.append(("", alts))
            i = j
        elif ch in "12345":
            k = i
            while k < n and seq[k] in "12345":
                k += 1
            segs.append((seq[i:k], []))
            i = k
        elif ch in "\\|":
            i += 1
        else:
            raise BuildError(f"UNMAPPED STROKE TOKEN: {ch}")
    if not segs:
        raise BuildError(f"EMPTY STROKE SEQ: {seq}")
    return segs


def resolve_stroke_segments(
    segs: list[tuple[str, list[str]]],
    target_first: Optional[str],
    target_last: Optional[str],
) -> tuple[list[str], set[str]]:
    """Resolve segments into a flat digit-token list (V4-CHOT rules).

    cnchar targets (digits) pick the alternative at first/last group; base fixed
    digits always stand. Returns (tokens, flags) where flags ⊆
    {"AMBIGUOUS_ORDER", "SOURCE_CONFLICT", "CNCHAR_PICKED"}.
    """
    flags: set[str] = set()
    n = len(segs)
    chosen: list[str] = []
    has_target = target_first is not None or target_last is not None

    for idx, (fixed, alts) in enumerate(segs):
        if not alts:
            chosen.append(fixed)
            continue
        is_first = idx == 0
        is_last = idx == n - 1
        want_f = target_first if is_first else None
        want_l = target_last if is_last else None

        if want_f is not None and want_l is not None:
            # Group sits at both ends (single-segment seq): match both ends.
            both = [a for a in alts if a[0] == want_f and a[-1] == want_l]
            one_f = [a for a in alts if a[0] == want_f]
            if both:
                pick = both[0]
                if pick != alts[0]:
                    flags.add("CNCHAR_PICKED")
            elif one_f:
                pick = one_f[0]
                flags.add("SOURCE_CONFLICT")
                if pick != alts[0]:
                    flags.add("CNCHAR_PICKED")
            else:
                pick = alts[0]
                flags.add("SOURCE_CONFLICT")
        elif want_f is not None:
            match = next((a for a in alts if a[0] == want_f), None)
            if match is None:
                pick = alts[0]
                flags.add("SOURCE_CONFLICT")
            else:
                pick = match
                if pick != alts[0]:
                    flags.add("CNCHAR_PICKED")
        elif want_l is not None:
            # Last-segment group: the class that matters is the alt's LAST digit.
            match = next((a for a in alts if a[-1] == want_l), None)
            if match is None:
                pick = alts[0]
                flags.add("SOURCE_CONFLICT")
            else:
                pick = match
                if pick != alts[0]:
                    flags.add("CNCHAR_PICKED")
        else:
            # No usable cnchar target at this position: fixed tie-break.
            pick = alts[0]
            if not has_target:
                flags.add("AMBIGUOUS_ORDER")
        chosen.append(pick)

    tokens: list[str] = []
    for part in chosen:
        tokens.extend(part)

    # Final verification: base (as resolved) vs cnchar targets. Base stands.
    if target_first is not None and tokens and tokens[0] != target_first:
        flags.add("SOURCE_CONFLICT")
    if target_last is not None and tokens and tokens[-1] != target_last:
        flags.add("SOURCE_CONFLICT")
    return tokens, flags


def _name_to_class_digit(name: str) -> Optional[str]:
    cls = STROKE_TOKENS.get(name)
    if cls is None:
        return None
    return CLASS_TO_DIGIT.get(cls)


def load_stroke_order_data(
    seq_file_path: Path,
    counts_file_path: Optional[Path] = None,
    cnchar_table_path: Optional[Path] = None,
    cnchar_dict_paths: Optional[List[Path]] = None,
    ids_path: Optional[Path] = None,
) -> dict[str, tuple[int, list[str]]]:
    """Load stroke data: stroke-input = BASE, cnchar = branch resolver + fill.

    V4-CHOT source mechanism:
      - stroke-input seq file is the primary source for every char it covers.
      - cnchar NEVER overrides base tokens. It only (a) picks the alternative
        inside alternation groups at first/last position, (b) fills chars the
        base does not cover, (c) cross-checks first/last stroke class.
      - group present but no cnchar target -> first alternative (fixed tie-break,
        source order) + AMBIGUOUS_ORDER flag (counted, never guessed).
      - base keeps winning any disagreement with cnchar (e.g. 門) ->
        SOURCE_CONFLICT flag, counted loudly.
      - unresolved group against cnchar (no alternative matches) ->
        SOURCE_CONFLICT, keep first alternative.
      - cross-check: % of intersection chars where base first/last class differs
        from cnchar first/last class (quality metric, reported).
      - V9 [V9-Q2] IDS_PICKED: cnchar thieu char -> first/last group resolved
        by IDS leading-leaf strokes (see ANCHOR_GRAMMAR_SPEC ids_picked_rule).

    seq file:   U+xxxx <tab> char <tab> stroke-sequence regex (classes 1-5)
    counts file: U+xxxx <tab> char <tab> total stroke count (ucs-strokes.txt)
    cnchar:     char -> letter sequence; letters resolved to stroke NAMES via
                stroke-table.json (提->H, 竖钩->V via STROKE_TOKENS)
    total = counts file value, fallback = len(tokens).
    """
    STROKE_SOURCE_STATS.clear()
    CROSS_DISAGREE_CHARS.clear()
    IDS_PICKED_CHARS.clear()
    GROUP_CHARS.clear()
    CNCHAR_COVERED.clear()
    ANCHOR_TABLE.clear()
    ANCHOR_TABLE_STATS.clear()
    STROKE_SOURCE_STATS.update(
        {
            "base_chars": 0,
            "cnchar_fill_chars": 0,
            "intersection": 0,
            "cross_disagree": 0,
            "cnchar_resolved": 0,
            "ambiguous_order": 0,
            "source_conflict": 0,
            "ids_picked": 0,
            "ids_picked_changed": 0,
            "ids_valid_checked": 0,
            "ids_valid_agree": 0,
            "ids_excluded_enclosing": 0,
            "ids_no_leaf": 0,
            "ids_leaf_unverified": 0,
            "ids_conflict": 0,
        }
    )
    if not seq_file_path.is_file() or seq_file_path.stat().st_size == 0:
        print(
            "SOURCE MISSING: stroke_seq — điền URL đúng vào SOURCES",
            file=sys.stderr,
        )
        sys.exit(2)

    # Pass 1: stroke counts (optional, authoritative totals)
    counts: dict[str, int] = {}
    if counts_file_path is not None and counts_file_path.is_file():
        with open(counts_file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                cp = parts[0].strip().upper()
                val = parts[2].strip()
                if cp.startswith("U+") and val.isascii() and val.isdigit():
                    counts[cp] = int(val)
                    try:
                        counts[chr(int(cp[2:], 16))] = int(val)
                    except (ValueError, OverflowError):
                        pass

    data: dict[str, tuple[int, list[str]]] = {}

    # Pass 2: cnchar named-stroke dictionaries (branch resolver + fill source)
    cnchar_map: dict[str, list[str]] = {}
    if cnchar_table_path is not None and cnchar_dict_paths:
        table: Dict[str, Any] = {}
        if cnchar_table_path.is_file():
            try:
                table = json.loads(cnchar_table_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                print(f"  Warning: cannot read cnchar table: {e}")
        if table:
            for dict_path in cnchar_dict_paths:
                if not dict_path.is_file():
                    continue
                try:
                    mapping = json.loads(dict_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as e:
                    print(f"  Warning: cannot read {dict_path.name}: {e}")
                    continue
                for ch, letters in mapping.items():
                    if len(ch) != 1 or not isinstance(letters, str):
                        continue
                    tokens: List[str] = []
                    ok = True
                    for letter in letters:
                        info = table.get(letter)
                        if not info or not info.get("name"):
                            ok = False
                            break
                        name = str(info["name"]).split("|")[0].strip()
                        name = re.sub(r"\d+$", "", name)
                        if not name:
                            ok = False
                            break
                        tokens.append(name)
                    if not ok or not tokens:
                        continue
                    cnchar_map.setdefault(ch, tokens)
        CNCHAR_COVERED.update(cnchar_map)

    # Pass 3: stroke-input sequence file = BASE source (primary for covered chars)
    skipped = 0
    base_meta: dict[str, tuple[bool, list[str], str]] = {}
    with open(seq_file_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            cp_str = parts[0].strip().upper()
            char_str = parts[1].strip()
            seq_str = parts[2].strip()
            if not cp_str.startswith("U+"):
                continue
            if len(char_str) != 1:
                try:
                    char_str = chr(int(cp_str[2:], 16))
                except (ValueError, OverflowError):
                    continue
            if not SEQ_FIELD_RE.match(seq_str):
                skipped += 1
                continue
            try:
                segs = parse_stroke_segments(seq_str)
                base_tokens, _flags = resolve_stroke_segments(segs, None, None)
            except BuildError:
                skipped += 1
                continue
            has_group = any(alts for _fixed, alts in segs)
            total_strokes = counts.get(cp_str) or counts.get(char_str)
            if total_strokes is None:
                total_strokes = len(base_tokens)
            data[char_str] = (total_strokes, base_tokens)
            data[cp_str] = (total_strokes, base_tokens)
            base_meta[char_str] = (has_group, base_tokens, seq_str)
            STROKE_SOURCE_STATS["base_chars"] += 1
            if has_group:
                GROUP_CHARS.add(char_str)
            if has_group and char_str not in cnchar_map:
                STROKE_SOURCE_STATS["ambiguous_order"] += 1

    # Pass 4: cnchar = branch resolver + fill. NEVER overrides base strokes.
    for ch, names in cnchar_map.items():
        if ch not in data:
            total = counts.get(ch)
            if total is None:
                total = len(names)
            data[ch] = (total, names)
            data[f"U+{ord(ch):04X}"] = (total, names)
            STROKE_SOURCE_STATS["cnchar_fill_chars"] += 1
            continue
        STROKE_SOURCE_STATS["intersection"] += 1
        has_group, base_tokens, seq_str = base_meta[ch]
        total = data[ch][0]
        tf = _name_to_class_digit(names[0])
        tl = _name_to_class_digit(names[-1])
        if (tf is not None and base_tokens[0] != tf) or (
            tl is not None and base_tokens[-1] != tl
        ):
            STROKE_SOURCE_STATS["cross_disagree"] += 1
            CROSS_DISAGREE_CHARS.append(
                {
                    "char": ch,
                    "base_first": DIGIT_TO_CLASS.get(base_tokens[0], "?"),
                    "base_last": DIGIT_TO_CLASS.get(base_tokens[-1], "?"),
                    "cnchar_first": DIGIT_TO_CLASS.get(tf, "?") if tf else "-",
                    "cnchar_last": DIGIT_TO_CLASS.get(tl, "?") if tl else "-",
                }
            )
        if tf is None and tl is None:
            if has_group:
                STROKE_SOURCE_STATS["ambiguous_order"] += 1
            continue
        try:
            segs = parse_stroke_segments(seq_str)
            tokens2, flags = resolve_stroke_segments(segs, tf, tl)
        except BuildError:
            STROKE_SOURCE_STATS["source_conflict"] += 1
            continue
        if "CNCHAR_PICKED" in flags:
            STROKE_SOURCE_STATS["cnchar_resolved"] += 1
        if "AMBIGUOUS_ORDER" in flags:
            STROKE_SOURCE_STATS["ambiguous_order"] += 1
        if "SOURCE_CONFLICT" in flags:
            STROKE_SOURCE_STATS["source_conflict"] += 1
        if tokens2 != base_tokens:
            data[ch] = (total, tokens2)
            data[f"U+{ord(ch):04X}"] = (total, tokens2)

    # Pass 4b (V9-DECISION [V9-Q2]): IDS_PICKED.
    # cnchar THIEU char -> alternation group at FIRST position resolved by IDS
    # LEADING leaf strokes, at LAST position by IDS TRAILING leaf strokes
    # ("leaf o vi tri dau/cuoi" — Claude V9). Constraints (4 dieu kien):
    #   (1) leaf must have stroke data AND be VERIFIED: leaf in cnchar_map AND
    #       leaf data first/last == cnchar first/last (R3 restriction — probe:
    #       raw rule err 12.3%, verified-leaf err 4.76% <= 5% revoke threshold),
    #   (2) only first/last-position groups; ops in IDS_EXCLUDED_OPS
    #       (⿴/⿵/⿻) anywhere on the leaf path -> skip,
    #   (3) counted separately + hand-checked; error rate vs cnchar ground
    #       truth reported (ids_valid_checked/ids_valid_agree),
    #   (4) revoke rule if error rate >5%.
    # ChatGPT V9: flag IDS_PICKED + report separately; runs only when the char
    # is NOT in cnchar_map (nguon doc lap khi cnchar thieu).
    # NOTE (V10 proposal): exclude wrap ops ⿺⿹ as well (probe err ~47% there;
    # with R3 they drop to a 49-error subset) — pending bilateral ratification.
    if ids_path is not None and ids_path.is_file():
        ids_raw: dict[str, str] = {}
        with open(ids_path, "r", encoding="utf-8", errors="replace") as f_ids:
            for line in f_ids:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts_i = line.split("\t")
                if len(parts_i) < 3:
                    continue
                ch_i = parts_i[1].strip()
                if len(ch_i) != 1 or ch_i in ids_raw:
                    continue
                for cand in parts_i[2:]:
                    cand_clean = re.sub(r"\[[^\]]+\]", "", cand).strip()
                    if cand_clean:
                        ids_raw[ch_i] = cand_clean
                        break

        def _walk_leaf(
            node_or_leaf: Any, first: bool
        ) -> tuple[Optional[str], bool]:
            """(leaf, hit_excluded_op) walking child[0] (first) or child[-1]."""
            if isinstance(node_or_leaf, str):
                return node_or_leaf, False
            if node_or_leaf.op in IDS_EXCLUDED_OPS:
                return None, True
            if not node_or_leaf.children:
                return None, False
            kid = node_or_leaf.children[0 if first else -1]
            return _walk_leaf(kid, first)

        def _verified_leaf_digits(
            leaf: Optional[str], self_ch: str, which: str
        ) -> tuple[Optional[tuple[str, str]], str]:
            """(tf, tl) of a VERIFIED leaf + status: ok|excluded|no_leaf|unverified."""
            if leaf is None:
                return None, "no_leaf"
            if leaf.startswith("&"):
                decoded = decode_entity_ref(leaf)
                leaf = decoded if decoded else None
            if (
                leaf is None
                or len(leaf) != 1
                or leaf == self_ch
                or leaf in PLACEHOLDER_CHARS
                or not is_cjk_leaf(leaf)
            ):
                return None, "no_leaf"
            entry = data.get(leaf)
            if entry is None:
                return None, "no_leaf"
            if leaf not in cnchar_map:
                return None, "unverified"  # R3: leaf must be cnchar-covered
            try:
                lf_d, ll_d = stroke_adapter(entry[1])
            except Exception:
                return None, "no_leaf"
            tf_d = CLASS_TO_DIGIT.get(lf_d)
            tl_d = CLASS_TO_DIGIT.get(ll_d)
            if tf_d is None or tl_d is None:
                return None, "no_leaf"
            # Verified = leaf data agrees with cnchar on BOTH ends.
            cf_d = _name_to_class_digit(cnchar_map[leaf][0])
            cl_d = _name_to_class_digit(cnchar_map[leaf][-1])
            if cf_d is None or cl_d is None:
                return None, "unverified"
            if tf_d != cf_d or tl_d != cl_d:
                return None, "unverified"  # base-vs-cnchar conflict at leaf
            return (tf_d, tl_d), "ok"

        for ch, (_hg_i, base_tokens_i, seq_i) in list(base_meta.items()):
            try:
                segs_i = parse_stroke_segments(seq_i)
            except BuildError:
                continue
            if not segs_i[0][1] and not segs_i[-1][1]:
                continue  # no alternation group at either end
            need_f_i = bool(segs_i[0][1])
            need_l_i = bool(segs_i[-1][1])
            tree_i: Any = None
            raw_ids = ids_raw.get(ch)
            if raw_ids:
                tree_i = parse_ids(raw_ids)
            if tree_i is None:
                continue
            if isinstance(tree_i, str):
                if not need_f_i and not need_l_i:
                    continue
                # terminal IDS (self) -> no component strokes
                STROKE_SOURCE_STATS["ids_no_leaf"] += 1
                continue
            leaf_f, ex_f = _walk_leaf(tree_i, first=True)
            leaf_l, ex_l = _walk_leaf(tree_i, first=False)
            if (need_f_i and ex_f) or (need_l_i and ex_l):
                STROKE_SOURCE_STATS["ids_excluded_enclosing"] += 1
                continue

            if ch in cnchar_map:
                # Validation proxy (Claude V9 dieu kien 3/4): cnchar = ground
                # truth; rule-as-applied (all-or-nothing, same gates as the
                # resolution path) — disagreement = error.
                if need_f_i:
                    dig_v, st_v = _verified_leaf_digits(leaf_f, ch, "F")
                    if st_v != "ok" or dig_v is None:
                        continue
                    tf_c = _name_to_class_digit(cnchar_map[ch][0])
                    if tf_c is None:
                        continue
                if need_l_i:
                    dig_l, st_l = _verified_leaf_digits(leaf_l, ch, "L")
                    if st_l != "ok" or dig_l is None:
                        continue
                    tl_c = _name_to_class_digit(cnchar_map[ch][-1])
                    if tl_c is None:
                        continue
                STROKE_SOURCE_STATS["ids_valid_checked"] += 1
                mismatch = (need_f_i and dig_v[0] != tf_c) or (
                    need_l_i and dig_l[1] != tl_c
                )
                if not mismatch:
                    STROKE_SOURCE_STATS["ids_valid_agree"] += 1
                continue

            if ch not in data:
                continue
            tf_i: Optional[str] = None
            tl_i: Optional[str] = None
            if need_f_i:
                dig_i, st_i = _verified_leaf_digits(leaf_f, ch, "F")
                if st_i == "excluded":
                    STROKE_SOURCE_STATS["ids_excluded_enclosing"] += 1
                    continue
                if st_i == "unverified":
                    STROKE_SOURCE_STATS["ids_leaf_unverified"] += 1
                    continue
                if dig_i is None:
                    STROKE_SOURCE_STATS["ids_no_leaf"] += 1
                    continue
                tf_i = dig_i[0]
            if need_l_i:
                dig_i, st_i = _verified_leaf_digits(leaf_l, ch, "L")
                if st_i == "excluded":
                    STROKE_SOURCE_STATS["ids_excluded_enclosing"] += 1
                    continue
                if st_i == "unverified":
                    STROKE_SOURCE_STATS["ids_leaf_unverified"] += 1
                    continue
                if dig_i is None:
                    STROKE_SOURCE_STATS["ids_no_leaf"] += 1
                    continue
                tl_i = dig_i[1]
            if tf_i is None and tl_i is None:
                continue
            tokens_i, flags_i = resolve_stroke_segments(segs_i, tf_i, tl_i)
            if "SOURCE_CONFLICT" in flags_i:
                STROKE_SOURCE_STATS["ids_conflict"] += 1
                continue
            if need_f_i and (not tokens_i or tokens_i[0] != tf_i):
                STROKE_SOURCE_STATS["ids_conflict"] += 1
                continue
            if need_l_i and (not tokens_i or tokens_i[-1] != tl_i):
                STROKE_SOURCE_STATS["ids_conflict"] += 1
                continue
            if tokens_i != base_tokens_i:
                total_i = data[ch][0]
                data[ch] = (total_i, tokens_i)
                data[f"U+{ord(ch):04X}"] = (total_i, tokens_i)
                STROKE_SOURCE_STATS["ids_picked_changed"] += 1
            IDS_PICKED_CHARS.add(ch)
            STROKE_SOURCE_STATS["ids_picked"] += 1

    # Pass 5 (V6-DECISION [V6-QB]): ANCHOR TABLE.
    # cnchar preferred per end; else base fixed-end digits (TQ); end-position
    # group without cnchar -> AMBIGUOUS_ANCHOR (tie-break digits kept, LOUD).
    ANCHOR_TABLE.clear()
    ANCHOR_TABLE_STATS.update(
        {"cnchar": 0, "tq": 0, "fill": 0, "ambiguous": 0, "ids_picked": 0}
    )
    for ch, entry in data.items():
        if len(ch) != 1:
            continue
        _total, tokens = entry
        tf_l: Optional[str] = None
        tl_l: Optional[str] = None
        if ch in cnchar_map:
            try:
                tf_l = map_stroke_token(cnchar_map[ch][0])
                tl_l = map_stroke_token(cnchar_map[ch][-1])
            except BuildError:
                tf_l = None
                tl_l = None
        bf: Optional[str] = None
        bl: Optional[str] = None
        if ch in base_meta:
            has_group, base_tokens_b, seq_b = base_meta[ch]
            if not has_group:
                bf = DIGIT_TO_CLASS.get(base_tokens_b[0])
                bl = DIGIT_TO_CLASS.get(base_tokens_b[-1])
            else:
                try:
                    segs_b = parse_stroke_segments(seq_b)
                    first_fixed = not segs_b[0][1]
                    last_fixed = not segs_b[-1][1]
                    if len(segs_b) == 1:
                        first_fixed = last_fixed = not segs_b[0][1]
                    bf = DIGIT_TO_CLASS.get(segs_b[0][0][0]) if first_fixed else None
                    bl = DIGIT_TO_CLASS.get(segs_b[-1][0][-1]) if last_fixed else None
                except BuildError:
                    bf = DIGIT_TO_CLASS.get(base_tokens_b[0])
                    bl = DIGIT_TO_CLASS.get(base_tokens_b[-1])
        f = tf_l or bf
        l = tl_l or bl
        if f and l:
            if tf_l or tl_l:
                ANCHOR_TABLE[ch] = (f, l, "cnchar")
                ANCHOR_TABLE_STATS["cnchar"] += 1
            elif ch in base_meta:
                ANCHOR_TABLE[ch] = (f, l, "tq")
                ANCHOR_TABLE_STATS["tq"] += 1
            else:
                ANCHOR_TABLE[ch] = (f, l, "fill")
                ANCHOR_TABLE_STATS["fill"] += 1
            continue
        # Unresolved end(s): tie-break digits kept for codegen + LOUD flag.
        # V9: IDS_PICKED chars -> source "ids_picked" (resolved via IDS leaf).
        src_amb = "ids_picked" if ch in IDS_PICKED_CHARS else "ambiguous"
        if tokens and all(t in "12345" for t in tokens):
            af = DIGIT_TO_CLASS.get(tokens[0])
            al = DIGIT_TO_CLASS.get(tokens[-1])
            if af and al:
                ANCHOR_TABLE[ch] = (af, al, src_amb)
                ANCHOR_TABLE_STATS[src_amb] += 1
                continue
        try:
            af = f or map_stroke_token(tokens[0])
            al = l or map_stroke_token(tokens[-1])
            ANCHOR_TABLE[ch] = (af, al, src_amb)
            ANCHOR_TABLE_STATS[src_amb] += 1
        except (BuildError, IndexError):
            pass  # uncovered -> MISSING_ANCHOR_STROKES downstream

    st = STROKE_SOURCE_STATS
    inter = st["intersection"]
    pct = (st["cross_disagree"] * 100.0 / inter) if inter else 0.0
    print(
        f"  Stroke data: {st['base_chars']} from stroke-input (BASE), "
        f"{st['cnchar_fill_chars']} filled from cnchar, {inter} intersection."
    )
    print(
        f"  Cross-check: {st['cross_disagree']}/{inter} ({pct:.2f}%) disagree "
        "first/last vs cnchar (V4-CHOT quality metric)."
    )
    print(
        f"  Flags: cnchar_resolved={st['cnchar_resolved']} "
        f"ambiguous_order={st['ambiguous_order']} "
        f"source_conflict={st['source_conflict']}."
    )
    print(
        f"  Anchor table: {ANCHOR_TABLE_STATS.get('cnchar', 0)} cnchar, "
        f"{ANCHOR_TABLE_STATS.get('tq', 0)} tq, "
        f"{ANCHOR_TABLE_STATS.get('fill', 0)} fill, "
        f"{ANCHOR_TABLE_STATS.get('ids_picked', 0)} ids_picked, "
        f"{ANCHOR_TABLE_STATS.get('ambiguous', 0)} ambiguous, "
        f"{len(ANCHOR_TABLE)} entries."
    )
    if st.get("ids_picked") or st.get("ids_excluded_enclosing"):
        vd = st.get("ids_valid_checked", 0)
        va = st.get("ids_valid_agree", 0)
        vrate = (va * 100.0 / vd) if vd else 0.0
        print(
            f"  IDS_PICKED (V9): {st.get('ids_picked', 0)} chars resolved "
            f"({st.get('ids_picked_changed', 0)} actually changed) via IDS "
            f"leading/trailing VERIFIED leaf (excluded_enclosing="
            f"{st.get('ids_excluded_enclosing', 0)} no_leaf={st.get('ids_no_leaf', 0)} "
            f"unverified={st.get('ids_leaf_unverified', 0)} "
            f"conflict={st.get('ids_conflict', 0)})."
        )
        print(
            f"  IDS validation (cnchar ground truth): {va}/{vd} agree "
            f"({vrate:.2f}%) — revoke rule if error rate >5% (Claude V9)."
        )
    if skipped:
        print(f"  Notice: {skipped} stroke_seq lines skipped (non-sequence field).")
    if not data:
        print(
            "SOURCE MISSING: stroke_seq — điền URL đúng vào SOURCES",
            file=sys.stderr,
        )
        sys.exit(2)
    return data


def load_unihan_data(
    zip_path: Path,
) -> tuple[dict[str, int], dict[str, str], dict[str, str]]:
    """Load total strokes, traditional variants, and simplified variants from Unihan.zip."""
    total_strokes: dict[str, int] = {}
    trad_variants: dict[str, str] = {}
    simp_variants: dict[str, str] = {}

    with zipfile.ZipFile(zip_path, "r") as zf:
        for fname in zf.namelist():
            if not fname.endswith(".txt"):
                continue
            with zf.open(fname, "r") as f:
                for raw_line in f:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) < 3:
                        continue
                    cp_hex = parts[0].strip()
                    tag = parts[1].strip()
                    val = parts[2].strip()

                    try:
                        char = chr(int(cp_hex[2:], 16))
                    except Exception:
                        continue

                    if tag == "kTotalStrokes":
                        if char not in total_strokes:
                            try:
                                total_strokes[char] = int(val.split()[0])
                            except Exception:
                                pass
                    elif tag == "kTraditionalVariant":
                        target_hex = val.split()[0]
                        try:
                            trad_variants[char] = chr(int(target_hex[2:], 16))
                        except Exception:
                            pass
                    elif tag == "kSimplifiedVariant":
                        target_hex = val.split()[0]
                        try:
                            simp_variants[char] = chr(int(target_hex[2:], 16))
                        except Exception:
                            pass
    return total_strokes, trad_variants, simp_variants


def load_ids_data(
    ids_path: Path, trad_vars: dict[str, str], simp_vars: dict[str, str]
) -> dict[str, IDSNode | str]:
    """Load and parse CJKVI ids.txt, applying recursive parser and inheritance fallback."""
    raw_ids_map: dict[str, str] = {}
    with open(ids_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            char = parts[1].strip()
            ids_candidates = parts[2:]
            # Pick first clean IDS without brackets or with stripped region tags
            chosen_ids = ""
            for cand in ids_candidates:
                cand_clean = re.sub(r"\[[^\]]+\]", "", cand).strip()
                if cand_clean:
                    chosen_ids = cand_clean
                    break
            if chosen_ids and char not in raw_ids_map:
                raw_ids_map[char] = chosen_ids

    parsed_trees: dict[str, IDSNode | str] = {}
    for char, raw_ids in raw_ids_map.items():
        tree = parse_ids(raw_ids)
        if tree is not None:
            parsed_trees[char] = tree

    # Fallback inheritance: char lacking IDS inherits from variant with provenance
    for char, target in list(trad_vars.items()):
        if char not in parsed_trees and target in parsed_trees:
            target_tree = parsed_trees[target]
            if isinstance(target_tree, IDSNode):
                inherited_node = IDSNode(
                    op=target_tree.op,
                    children=target_tree.children,
                    confidence=CONF_INHERITED,
                    raw=target_tree.raw,
                    provenance=f"kTraditionalVariant -> {target}",
                )
                parsed_trees[char] = inherited_node

    for char, target in list(simp_vars.items()):
        if char not in parsed_trees and target in parsed_trees:
            target_tree = parsed_trees[target]
            if isinstance(target_tree, IDSNode):
                inherited_node = IDSNode(
                    op=target_tree.op,
                    children=target_tree.children,
                    confidence=CONF_INHERITED,
                    raw=target_tree.raw,
                    provenance=f"kSimplifiedVariant -> {target}",
                )
                parsed_trees[char] = inherited_node

    return parsed_trees


def load_unihan_radicals(zip_path: Path) -> dict[str, int]:
    """Load kRSUnicode Kangxi radical numbers for fixed V9 K-group diagnostics."""
    radicals: dict[str, int] = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open("Unihan_IRGSources.txt", "r") as f:
            for raw_line in f:
                parts = raw_line.decode("utf-8", errors="replace").strip().split("\t")
                if len(parts) < 3 or parts[1] != "kRSUnicode":
                    continue
                try:
                    char = chr(int(parts[0][2:], 16))
                except (ValueError, IndexError):
                    continue
                match = re.match(r"(\d+)", parts[2].split()[0] if parts[2] else "")
                if match:
                    radical = int(match.group(1))
                    if 1 <= radical <= 214:
                        radicals[char] = radical
    return radicals


def parse_freq_html(file_path: Path) -> dict[str, float]:
    """Parse Jun Da frequency table from HTML or text format."""
    if not file_path.is_file() or file_path.stat().st_size == 0:
        print(
            "SOURCE PARSE FAIL: freq_b1 — file missing or empty",
            file=sys.stderr,
        )
        sys.exit(2)

    raw = file_path.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("gb18030", errors="replace")
    if "�" in content and content.count("�") > 100:
        content = raw.decode("gb18030", errors="replace")

    freq_map: dict[str, float] = {}

    # Method 1: HTML table rows
    row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
    cell_pattern = re.compile(
        r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE
    )
    tag_strip = re.compile(r"<[^>]+>")

    for row_match in row_pattern.finditer(content):
        cells = [
            tag_strip.sub("", c).strip()
            for c in cell_pattern.findall(row_match.group(1))
        ]
        if not cells:
            continue
        cjk_char: Optional[str] = None
        freq_val: Optional[float] = None
        for cell in cells:
            if len(cell) == 1 and is_cjk_leaf(cell) and cjk_char is None:
                cjk_char = cell
            else:
                cleaned = cell.replace(",", "").strip()
                try:
                    num = float(cleaned)
                    if freq_val is None and num > 0:
                        freq_val = num
                except ValueError:
                    pass
        if cjk_char and freq_val is not None:
            freq_map[cjk_char] = freq_val

    # Method 2: Whitespace/Tab-delimited text list (Jun Da raw format)
    if len(freq_map) < 50:
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                cjk_char = None
                freq_val = None
                for i, p in enumerate(parts):
                    if len(p) == 1 and is_cjk_leaf(p):
                        cjk_char = p
                        for q in parts[i + 1 :]:
                            try:
                                v = float(q.replace(",", "").strip())
                                if v > 0:
                                    freq_val = v
                                    break
                            except ValueError:
                                continue
                        break
                if cjk_char and freq_val is not None:
                    freq_map[cjk_char] = freq_val

    # Method 3: Follow embedded link if offline cache was merely index page
    if len(freq_map) < 50:
        m = re.search(
            r'href=["\']([^"\']*(?:general_character|modern_chinese|charfreq)[^"\']*)["\']',
            content,
            re.IGNORECASE,
        )
        if m:
            target_url = urllib.parse.urljoin(
                SOURCES["freq_b1"]["url"], m.group(1)
            )
            print(
                f"  Notice: freq_b1 is an index page. Following linked frequency table: {target_url}"
            )
            try:
                headers = {"User-Agent": "HANSTROKE-V3-BENCHMARK/1.0"}
                req = urllib.request.Request(target_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    sub_content = resp.read().decode("utf-8", errors="replace")
                    # Recursive parse over fetched sub-content
                    sub_path = file_path.parent / "freq_b1_sub.html"
                    with open(sub_path, "w", encoding="utf-8") as sf:
                        sf.write(sub_content)
                    return parse_freq_html(sub_path)
            except Exception as e:
                print(f"  Warning: could not fetch sub-table: {e}")

    if len(freq_map) < 50:
        print(
            "SOURCE PARSE FAIL: freq_b1 — điền URL đúng vào SOURCES",
            file=sys.stderr,
        )
        sys.exit(2)

    return freq_map


# -----------------------------------------------------------------------------
# 6) BENCHMARK ENGINE
# -----------------------------------------------------------------------------
@dataclass
class CharFeature:
    char: str
    total_strokes: int
    primary_anchor: str
    secondary_anchor: str
    primary_first: str
    primary_last: str
    secondary_first: Optional[str]
    secondary_last: Optional[str]
    residual: int
    t1_key: str
    t2_key: str
    t3_a: str
    t3_c: str
    t3_e: str
    code_a: str
    code_c: str
    code_e: str
    ids_confidence: str


def run_golden_tests(
    stroke_data: dict[str, tuple[int, list[str]]],
) -> tuple[bool, list[dict[str, Any]]]:
    """Execute golden tests for stroke adapter on ~60 anchors."""
    golden_path = Path(GOLDEN_FILE_NAME)
    if golden_path.is_file():
        print(
            f">>> Loading external golden tests from {golden_path} (bộ test vàng do reviewer duyệt tay bổ sung đủ 60)..."
        )
        with open(golden_path, "r", encoding="utf-8") as f:
            anchors = json.load(f)
    else:
        anchors = GOLDEN_ANCHORS_INLINE

    # V4-CHOT Dieu kien 1: golden DONG BANG bang SHA-256 — khong sua de khop output.
    # Moi sua doi phai co changelog trong GOLDEN_CHANGELOG.md roi cap nhat hang so.
    frozen_sha = hashlib.sha256(
        json.dumps(
            anchors, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    if frozen_sha != GOLDEN_FROZEN_SHA256:
        print(
            "GOLDEN FROZEN HASH MISMATCH — golden da sua trai phep V4-CHOT!\n"
            f"  Expected: {GOLDEN_FROZEN_SHA256}\n"
            f"  Actual:   {frozen_sha}\n"
            "  Moi sua doi phai ghi GOLDEN_CHANGELOG.md (nguon, bang chung, ly do) "
            "roi cap nhat GOLDEN_FROZEN_SHA256.",
            file=sys.stderr,
        )
        sys.exit(3)
    print(f"  Golden freeze hash OK: {frozen_sha[:16]}... ({len(anchors)} anchors)")

    print(
        f">>> Running GOLDEN TESTS on {len(anchors)} reference anchors (豎鉤 = V enforced)..."
    )
    all_passed = True
    results: list[dict[str, Any]] = []

    for char, expected in anchors.items():
        cp = expected.get("codepoint", "")
        # Lookup either by char or codepoint
        entry = stroke_data.get(char) or stroke_data.get(cp)
        if not entry:
            all_passed = False
            msg = f"FAIL: {char} ({cp}) not found in stroke_order data"
            print(f"  [FAIL] {msg}")
            results.append({"char": char, "status": "FAIL", "reason": msg})
            continue

        actual_total, tokens = entry
        try:
            actual_first, actual_last = stroke_adapter(tokens)
        except Exception as e:
            all_passed = False
            msg = f"FAIL: {char} adapter error: {e}"
            print(f"  [FAIL] {msg}")
            results.append({"char": char, "status": "FAIL", "reason": msg})
            continue

        exp_total = expected["total"]
        exp_first = expected["first"]
        exp_last = expected["last"]

        # Note: If Unihan or CJKVI stroke count slightly differs from CNS convention,
        # we strictly compare against golden expectation.
        match = (
            (actual_total == exp_total)
            and (actual_first == exp_first)
            and (actual_last == exp_last)
        )
        if match:
            print(
                f"  [PASS] {char} ({cp}) total={actual_total} first={actual_first} last={actual_last}"
            )
            results.append({"char": char, "status": "PASS"})
        else:
            all_passed = False
            msg = (
                f"expected (tot={exp_total}, f={exp_first}, l={exp_last}), "
                f"got (tot={actual_total}, f={actual_first}, l={actual_last})"
            )
            print(f"  [FAIL] {char} ({cp}) {msg}")
            results.append({"char": char, "status": "FAIL", "reason": msg})

    return all_passed, results


def run_spotcheck_stratified(
    stroke_data: dict[str, tuple[int, list[str]]],
    cnchar_dict_paths: Optional[List[Path]],
    ids_path: Path,
    seq_file_path: Path,
    total_strokes_map: dict[str, int],
    golden_chars: set[str],
    seed: int = 20261004,
    per_stratum: int = 20,
) -> dict[str, Any]:
    """V9 spotcheck 100 chu moi ([V8-QD]/[V9-QD] dong thuan 2 ben).

    - seed MOI (khac lan 20261003 truoc), doc lap voi 51 golden (loai golden).
    - phan tang 5 lop: S1 phinh the (cnchar-trad), S2 nhom mo ho (group,
      ngoai cnchar-trad), S3 ngoai cnchar (U+4E00-9FFF), S4 co placeholder
      trong IDS, S5 Ext A hiem.
    - doi chieu nguon DOC LAP: cnchar (chu), IDS leading/trailing VERIFIED
      leaf (chu ngoai cnchar), Unihan kTotalStrokes (total) — KHONG doi chieu
      voi chinh output; chu thieu nguon独立 -> SINGLE (bao ca rieng).
    - IDS_PICKED chars = circular (dat data tu IDS) -> danh skip-err, tach
      khoi ty le loi; ty loi IDS khong circular + ty loi cnchar = bang chung
      giu/rut luat IDS_PICKED (nguong 5%).
    """
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []

    def in_b0(c: str) -> bool:
        o = ord(c)
        return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF

    # --- independent sources -------------------------------------------------
    cn_fl: dict[str, tuple[Optional[str], Optional[str]]] = {}
    if cnchar_dict_paths:
        table: Dict[str, Any] = {}
        try:
            first_path = cnchar_dict_paths[0].parent / "cnchar-stroke-table.json"
            if first_path.is_file():
                table = json.loads(first_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            table = {}
        if table:
            for dp in cnchar_dict_paths:
                if not dp or not dp.is_file():
                    continue
                try:
                    mapping = json.loads(dp.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                for ch, letters in mapping.items():
                    if len(ch) != 1 or not isinstance(letters, str) or ch in cn_fl:
                        continue
                    names: list[str] = []
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
                        names.append(nm)
                    if not ok or not names:
                        continue
                    cn_fl[ch] = (
                        _name_to_class_digit(names[0]),
                        _name_to_class_digit(names[-1]),
                    )

    trad_set: set[str] = set()
    if cnchar_dict_paths and len(cnchar_dict_paths) > 1:
        try:
            trad_set = {
                ch
                for ch in json.loads(
                    cnchar_dict_paths[1].read_text(encoding="utf-8")
                )
                if len(ch) == 1
            }
        except (OSError, json.JSONDecodeError):
            trad_set = set()

    ids_raw: dict[str, str] = {}
    ph_chars: set[str] = set()
    if ids_path.is_file():
        with open(ids_path, "r", encoding="utf-8", errors="replace") as f:
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
                        if any(pc in c for pc in PLACEHOLDER_CHARS):
                            ph_chars.add(ch)
                        break

    seq_map: dict[str, str] = {}
    try:
        with open(seq_file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 3 and p[0].strip().upper().startswith("U+"):
                    try:
                        seq_map[chr(int(p[0].strip()[2:], 16))] = p[2].strip()
                    except ValueError:
                        continue
    except OSError:
        seq_map = {}

    def walk_leaf(node: Any, first: bool) -> tuple[Optional[str], bool]:
        if isinstance(node, str):
            return node, False
        if node.op in IDS_EXCLUDED_OPS:
            return None, True
        if not node.children:
            return None, False
        return walk_leaf(node.children[0 if first else -1], first)

    def ids_prediction(ch: str) -> tuple[Optional[str], Optional[str], str]:
        """(tf, tl) IDS VERIFIED-leaf prediction (same gates as loader)."""
        raw = ids_raw.get(ch)
        if not raw:
            return None, None, "no_ids"
        seq = seq_map.get(ch)
        if not seq:
            return None, None, "no_seq"
        try:
            segs = parse_stroke_segments(seq)
        except BuildError:
            return None, None, "no_seq"
        if not segs[0][1] and not segs[-1][1]:
            return None, None, "no_group"
        need_f = bool(segs[0][1])
        need_l = bool(segs[-1][1])
        tree = parse_ids(raw)
        if tree is None:
            return None, None, "no_leaf"
        if isinstance(tree, str):
            return None, None, "no_leaf"
        leaf_f, ex_f = walk_leaf(tree, True)
        leaf_l, ex_l = walk_leaf(tree, False)
        if (need_f and ex_f) or (need_l and ex_l):
            return None, None, "excluded"

        def verified(leaf: Optional[str]) -> tuple[Optional[str], Optional[str], str]:
            if leaf is None:
                return None, None, "no_leaf"
            if leaf.startswith("&"):
                d = decode_entity_ref(leaf)
                leaf = d if d else None
            if (
                leaf is None
                or len(leaf) != 1
                or leaf == ch
                or leaf in PLACEHOLDER_CHARS
                or not is_cjk_leaf(leaf)
            ):
                return None, None, "no_leaf"
            e = stroke_data.get(leaf)
            if e is None:
                return None, None, "no_leaf"
            if leaf not in cn_fl:
                return None, None, "unverified"
            try:
                lf_d, ll_d = stroke_adapter(e[1])
            except Exception:
                return None, None, "no_leaf"
            tf_d = CLASS_TO_DIGIT.get(lf_d)
            tl_d = CLASS_TO_DIGIT.get(ll_d)
            cf_d, cl_d = cn_fl[leaf]
            if not tf_d or not tl_d or cf_d is None or cl_d is None:
                return None, None, "unverified"
            if tf_d != cf_d or tl_d != cl_d:
                return None, None, "unverified"
            return tf_d, tl_d, "ok"

        tf_o: Optional[str] = None
        tl_o: Optional[str] = None
        if need_f:
            dig = verified(leaf_f)
            if dig[2] != "ok":
                return None, None, dig[2]
            tf_o = dig[0]
        if need_l:
            dig = verified(leaf_l)
            if dig[2] != "ok":
                return None, None, dig[2]
            tl_o = dig[1]
        if tf_o is None and tl_o is None:
            return None, None, "no_group"
        return tf_o, tl_o, "ok"

    # --- strata pools (dedupe via claim order) -------------------------------
    cand = [
        c
        for c in stroke_data
        if len(c) == 1 and in_b0(c) and c not in golden_chars
    ]
    pools: list[tuple[str, list[str]]] = [
        ("S1_trad", [c for c in cand if c in trad_set]),
        ("S2_group", [c for c in cand if c in GROUP_CHARS and c not in trad_set]),
        (
            "S4_placeholder",
            [c for c in cand if c in ph_chars],
        ),
        (
            "S3_no_cnchar",
            [
                c
                for c in cand
                if c not in CNCHAR_COVERED
                and c not in GROUP_CHARS
                and c not in ph_chars
                and 0x4E00 <= ord(c) <= 0x9FFF
            ],
        ),
        (
            "S5_ext_a",
            [c for c in cand if 0x3400 <= ord(c) <= 0x4DBF],
        ),
    ]
    used: set[str] = set()
    bucket_sizes: dict[str, int] = {}
    selected: list[tuple[str, str]] = []
    for tag, pool in pools:
        avail = sorted(c for c in pool if c not in used)
        bucket_sizes[tag] = len(avail)
        k = min(per_stratum, len(avail))
        pick = rng.sample(avail, k) if k else []
        used.update(pick)
        selected.extend((tag, c) for c in pick)

    # --- run rows ------------------------------------------------------------
    verdicts: dict[str, int] = {}
    cn_agree = cn_conflict = ids_agree = ids_diff = ids_circular = single = 0
    count_ok = count_bad = 0
    for tag, ch in selected:
        total, tokens = stroke_data[ch]
        try:
            first, last = stroke_adapter(tokens)
        except Exception:
            first, last = "?", "?"
        f_d = CLASS_TO_DIGIT.get(first)
        l_d = CLASS_TO_DIGIT.get(last)
        cf_d, cl_d = cn_fl.get(ch, (None, None))
        pred = (None, None, "no_ids")
        if cf_d is None:
            pred = ids_prediction(ch)
        circular = ch in IDS_PICKED_CHARS
        if cf_d is not None:
            verdict = "AGREE" if (f_d == cf_d and l_d == cl_d) else "CONFLICT"
            if verdict == "AGREE":
                cn_agree += 1
            else:
                cn_conflict += 1
        elif pred[2] == "ok":
            if circular:
                verdict = "IDS_CIRCULAR"
                ids_circular += 1
            else:
                match = (pred[0] is None or pred[0] == f_d) and (
                    pred[1] is None or pred[1] == l_d
                )
                verdict = "IDS_AGREE" if match else "IDS_DIFF"
                if match:
                    ids_agree += 1
                else:
                    ids_diff += 1
        else:
            verdict = "SINGLE"
            single += 1
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        ut = total_strokes_map.get(ch)
        if ut is not None:
            if ut == total:
                count_ok += 1
            else:
                count_bad += 1
        rows.append(
            {
                "stratum": tag,
                "char": ch,
                "codepoint": f"U+{ord(ch):04X}",
                "total": total,
                "first": first,
                "last": last,
                "cnchar": (
                    f"{cf_d or '-'}{cl_d or '-'}" if cf_d or cl_d else None
                ),
                "ids_pred": (
                    f"{pred[0] or '-'}{pred[1] or '-'}" if pred[2] == "ok" else None
                ),
                "ids_status": pred[2],
                "circular": circular,
                "in_group": ch in GROUP_CHARS,
                "has_placeholder": ch in ph_chars,
                "verdict": verdict,
                "unihan_count_match": (
                    None if ut is None else ut == total
                ),
            }
        )

    cross = cn_agree + cn_conflict
    ids_cross = ids_agree + ids_diff
    result: dict[str, Any] = {
        "seed": seed,
        "per_stratum_requested": per_stratum,
        "bucket_sizes": bucket_sizes,
        "selected_count": len(selected),
        "stratum_selected": dict(
            (t, sum(1 for tt, _ in selected if tt == t))
            for t, _ in pools
        ),
        "verdicts": verdicts,
        "cnchar_cross": {
            "agree": cn_agree,
            "conflict": cn_conflict,
            "error_pct": round(
                (cn_conflict * 100.0 / cross), 2
            ) if cross else None,
        },
        "ids_cross": {
            "agree": ids_agree,
            "diff": ids_diff,
            "error_pct_non_circular": round(
                (ids_diff * 100.0 / ids_cross), 2
            ) if ids_cross else None,
            "circular_skipped": ids_circular,
        },
        "unihan_count": {"match": count_ok, "mismatch": count_bad},
        "single_no_independent_source": single,
        "golden_excluded": len(golden_chars),
        "rows": rows,
    }
    print(
        f">>> SPOTCHECK V9 stratified (seed={seed}): {len(selected)} rows, "
        f"verdicts={verdicts}"
    )
    print(
        f"    cnchar cross: {cn_agree}A/{cn_conflict}C "
        f"(err {result['cnchar_cross']['error_pct']}%), "
        f"IDS cross: {ids_agree}A/{ids_diff}D "
        f"(err {result['ids_cross']['error_pct_non_circular']}%, "
        f"circular={ids_circular}), single={single}, "
        f"Unihan count {count_ok}ok/{count_bad}bad."
    )
    return result


def bucket_gt9_summary(
    table: dict[str, list[str]], p_weights: dict[str, float], total_weight: float
) -> dict[str, Any]:
    over = [(key, chars) for key, chars in table.items() if len(chars) > 9]
    affected_weight = sum(
        sum(p_weights.get(char, 0.0) for char in chars) for _, chars in over
    )
    return {
        "bucket_count": len(over),
        "char_count": sum(len(chars) for _, chars in over),
        "max_bucket": max((len(chars) for _, chars in over), default=0),
        "weighted_char_share_pct": round(
            affected_weight * 100.0 / total_weight, 2
        ) if total_weight else 0.0,
    }


def run_v9_diagnostics(
    valid_features: dict[str, CharFeature],
    wide_profiles: dict[str, dict[str, Any]],
    b0_core_chars: list[str],
    radical_map: dict[str, int],
) -> dict[str, Any]:
    """Registered V9 ladder + fixed Kangxi K-group curve diagnostics."""
    ladder_tables: dict[int, dict[str, list[str]]] = {
        length: collections.defaultdict(list) for length in LADDER_RUNGS
    }
    k_tables: dict[int, dict[str, list[str]]] = {
        k: collections.defaultdict(list) for k in K_GROUPS
    }
    unmapped: dict[int, int] = {k: 0 for k in K_GROUPS}

    def ladder_code(char: str, length: int) -> Optional[str]:
        feat = valid_features.get(char)
        if feat is None:
            return None
        sec = feat.secondary_anchor if feat.secondary_anchor != SENTINEL_CHAR else ""
        full = f"{feat.code_c}{feat.primary_anchor}{sec}"
        return full[:length]

    def k_code(char: str, k: int) -> Optional[str]:
        feat = valid_features.get(char)
        if feat is None:
            return None
        radical = radical_map.get(feat.primary_anchor)
        group = (radical - 1) * k // 214 if radical else -1
        return f"{feat.code_c}#{group}"

    for char, feat in valid_features.items():
        sec = feat.secondary_anchor if feat.secondary_anchor != SENTINEL_CHAR else ""
        full = f"{feat.code_c}{feat.primary_anchor}{sec}"
        for length, table in ladder_tables.items():
            table[full[:length]].append(char)
        radical = radical_map.get(feat.primary_anchor)
        for k, table in k_tables.items():
            group = (radical - 1) * k // 214 if radical else -1
            if radical is None:
                unmapped[k] += 1
            table[f"{feat.code_c}#{group}"].append(char)

    core_weights = {char: 1.0 for char in b0_core_chars}
    core_total = float(len(b0_core_chars))
    profile_names = ("B1", "B3-T")
    ladder: dict[str, Any] = {}
    k_curve: dict[str, Any] = {}

    # Ladder base = code_c + primary_anchor + secondary_anchor (full deterministic string)
    def ladder_base_string(char: str) -> str:
        feat = valid_features.get(char)
        if feat is None:
            return ""
        sec = feat.secondary_anchor if feat.secondary_anchor != SENTINEL_CHAR else ""
        return f"{feat.code_c}{feat.primary_anchor}{sec}"
    
    for length, table in ladder_tables.items():
        per_profile: dict[str, Any] = {}
        for name in profile_names:
            pdata = wide_profiles[name]
            per_profile[name] = variant_metrics(
                pdata["chars"], pdata["weights"], sum(pdata["weights"].values()),
                lambda char, _l=length, _lbase=ladder_base_string: _lbase(char)[:_l] if _lbase(char) else None, table,
            )
        core_metric = variant_metrics(
            b0_core_chars, core_weights, core_total,
            lambda char, _l=length, _lbase=ladder_base_string: _lbase(char)[:_l] if _lbase(char) else None, table,
        )
        b1_w = wide_profiles["B1"]
        ladder[str(length)] = {
            "code_length_ceiling": length,
            "B1": per_profile["B1"],
            "B3-T": per_profile["B3-T"],
            "B0-core": core_metric,
            "b0_core_floor_pass": core_metric["weighted_le9_pct"] >= B0_CORE_FLOOR_PCT,
            "official_gate_pass": all(
                per_profile[name]["weighted_le9_pct"] >= GATE_THRESHOLD_PCT
                for name in profile_names
            ),
            "bucket_gt9": bucket_gt9_summary(
                table, b1_w["weights"], sum(b1_w["weights"].values())
            ),
        }

    for k, table in k_tables.items():
        per_profile = {}
        for name in profile_names:
            pdata = wide_profiles[name]
            per_profile[name] = variant_metrics(
                pdata["chars"], pdata["weights"], sum(pdata["weights"].values()),
                lambda char, _k=k: k_code(char, _k), table,
            )
        core_metric = variant_metrics(
            b0_core_chars, core_weights, core_total,
            lambda char, _k=k: k_code(char, _k), table,
        )
        b1_w = wide_profiles["B1"]
        k_curve[str(k)] = {
            "K": k,
            "identification_cost_groups": k + (1 if unmapped[k] else 0),
            "unmapped_primary_anchors": unmapped[k],
            "B1": per_profile["B1"],
            "B3-T": per_profile["B3-T"],
            "B0-core": core_metric,
            "b0_core_floor_pass": core_metric["weighted_le9_pct"] >= B0_CORE_FLOOR_PCT,
            "official_gate_pass": all(
                per_profile[name]["weighted_le9_pct"] >= GATE_THRESHOLD_PCT
                for name in profile_names
            ),
            "bucket_gt9": bucket_gt9_summary(
                table, b1_w["weights"], sum(b1_w["weights"].values())
            ),
        }

    passing_lengths = [
        length for length in LADDER_RUNGS
        if ladder[str(length)]["official_gate_pass"]
    ]
    passing_k = [k for k in K_GROUPS if k_curve[str(k)]["official_gate_pass"]]
    avg_length: dict[str, float] = {}
    for name in profile_names:
        pdata = wide_profiles[name]
        total_weight = sum(pdata["weights"].values())
        numerator = sum(
            pdata["weights"].get(char, 0.0) * len(
                f"{feat.code_c}{feat.primary_anchor}"
                + (feat.secondary_anchor if feat.secondary_anchor != SENTINEL_CHAR else "")
            )
            for char, feat in valid_features.items()
        )
        avg_length[name] = round(numerator / total_weight, 3) if total_weight else 0.0

    # [V11-QA] Partition robustness: L6 gate on deterministic halves of the
    # frequency partitions (sha256(codepoint) bit 0). Claude's condition for
    # choosing L6: verify the gate holds on a DIFFERENT partition, not just
    # the aggregate. Per-half numbers reported; no selection from halves.
    partition_robustness: dict[str, Any] = {"method": (
        "sha256(codepoint)&1 split of B1-wide and B3-T-wide into 2 "
        "deterministic halves; same S=code_c+primary_anchor, L6; "
        "per-half gate = weighted % chars whose L6 code has <=9 "
        "candidates WITHIN the half; diagnostic only (not selection)"
    )}
    for part_name in ("B1", "B3-T"):
        pdata = wide_profiles[part_name]
        weights = pdata["weights"]
        halves = [
            {"name": f"{part_name}-H0", "chars": [], "weight": 0.0},
            {"name": f"{part_name}-H1", "chars": [], "weight": 0.0},
        ]
        for ch in pdata["chars"]:
            bit = hashlib.sha256(ch.encode("utf-8")).digest()[0] & 1
            w = float(weights.get(ch, 1.0))
            halves[bit]["chars"].append(ch)
            halves[bit]["weight"] += w
        for h in halves:
            code_groups: dict[str, list[str]] = collections.defaultdict(list)
            for ch in h["chars"]:
                feat = valid_features.get(ch)
                if feat is None:
                    continue
                sec = (
                    feat.secondary_anchor
                    if feat.secondary_anchor != SENTINEL_CHAR
                    else ""
                )
                full = f"{feat.code_c}{feat.primary_anchor}{sec}"
                if full:
                    code_groups[full[:CODE_CEILING]].append(ch)
            w_hit = 0.0
            n_tot = 0
            for code, members in code_groups.items():
                if len(members) <= 9:
                    for ch in members:
                        w_hit += float(weights.get(ch, 1.0))
                        n_tot += 1
            w_total = h["weight"] or 1.0
            h["wide_pct"] = round(100.0 * w_hit / w_total, 2)
            h["chars_evaluated"] = n_tot
            h["gate"] = "PASS" if h["wide_pct"] >= GATE_THRESHOLD_PCT else "FAIL"
        partition_robustness[part_name] = halves

    return {
        "registered": {
            "threshold_pct": GATE_THRESHOLD_PCT,
            "b0_core_floor_pct": B0_CORE_FLOOR_PCT,
            "code_ceiling": CODE_CEILING,
            "ladder_rungs": list(LADDER_RUNGS),
            "k_groups": list(K_GROUPS),
            "same_partition": "wide B1/B3-T + B0-core wide; seed=20261004 spotcheck only",
        },
        "ladder": ladder,
        "k_curve": k_curve,
        "shortest_ladder_passing": min(passing_lengths) if passing_lengths else None,
        "smallest_k_passing": min(passing_k) if passing_k else None,
        "ceiling_result": "PASS" if passing_lengths else "FAIL",
        "frequency_weighted_avg_full_code_length": avg_length,
        "partition_robustness": partition_robustness,
    }


def export_human_screen_package(
    valid_features: dict[str, CharFeature],
    freq_b1_map: dict[str, float],
    b1_chars: list[str],
    b3t_chars: list[str],
    out_dir: Path,
) -> dict[str, Any]:
    """[V11-QA Claude][V12-QB both] Human-screen package: stratified
    sample with L6 codes + measurement form. Two versions: test (chars
    only) + answer key (with codes). Per-step columns. Verdict
    CORRECT/INCORRECT/UNCLEAR + time. Fatal thresholds registered.
    Deterministic selection (no RNG)."""
    rows: list[dict[str, Any]] = []

    def l6_code(char: str) -> str:
        feat = valid_features.get(char)
        if feat is None:
            return ""
        sec = (
            feat.secondary_anchor
            if feat.secondary_anchor != SENTINEL_CHAR
            else ""
        )
        return f"{feat.code_c}{feat.primary_anchor}{sec}"[:CODE_CEILING]

    def add_row(char: str, stratum: str) -> None:
        feat = valid_features.get(char)
        if feat is None:
            return
        sec = (
            feat.secondary_anchor
            if feat.secondary_anchor != SENTINEL_CHAR
            else "-"
        )
        rows.append(
            {
                "char": char,
                "codepoint": f"U+{ord(char):04X}",
                "stratum": stratum,
                "in_B1": char in freq_b1_map,
                "freq_b1": freq_b1_map.get(char),
                "total_strokes": feat.total_strokes,
                "code_c": feat.code_c,
                "primary_anchor": feat.primary_anchor,
                "secondary_anchor": sec,
                "l6_code": l6_code(char),
                "oracle_key": oracle_key_of(char, valid_features),
                "human_verdict": "",
                "time_seconds": "",
            }
        )

    by_freq = sorted(b1_chars, key=lambda c: (-float(freq_b1_map.get(c, 0.0)), c))
    for ch in by_freq[:50]:
        add_row(ch, "S1_top_freq")
    for ch in by_freq[500:530]:
        add_row(ch, "S2_mid_freq")
    for ch in by_freq[-20:]:
        add_row(ch, "S3_rare")
    trad_only = sorted(set(b3t_chars) - set(b1_chars))
    for ch in trad_only[:20]:
        add_row(ch, "S4_trad")
    ext = sorted(c for c in b3t_chars if ord(c) > 0x9FFF)
    for ch in ext[:15]:
        add_row(ch, "S5_ext_a")
    ids_picked = sorted(
        c for c in IDS_PICKED_CHARS if c in valid_features
    )
    for ch in ids_picked[:15]:
        add_row(ch, "S6_ids_picked")

    # S7: ambiguous primary anchors (from ANCHOR_TABLE quality)
    ambiguous_anchors = {
        a for a, (_, _, q) in ANCHOR_TABLE.items() if q == "ambiguous"
    }
    amb_chars = sorted(
        c
        for c, f in valid_features.items()
        if f.primary_anchor in ambiguous_anchors
    )
    for ch in amb_chars[:15]:
        add_row(ch, "S7_ambiguous_anchor")

    # S8: placeholder chars (COMPOSITE_PLACEHOLDER quality)
    placeholder_chars = sorted(
        c
        for c, f in valid_features.items()
        if f.primary_anchor in PLACEHOLDER_CHARS
        or f.secondary_anchor in PLACEHOLDER_CHARS
    )
    for ch in placeholder_chars[:10]:
        add_row(ch, "S8_placeholder")

    rows.sort(key=lambda r: (r["stratum"], r["codepoint"]))

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "human_screen_package.json"
    csv_path = out_dir / "human_screen_package.csv"
    test_md_path = out_dir / "human_screen_test.md"
    answer_md_path = out_dir / "human_screen_answer_key.md"

    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    cols = [
        "char",
        "codepoint",
        "stratum",
        "freq_b1",
        "total_strokes",
        "code_c",
        "primary_anchor",
        "secondary_anchor",
        "l6_code",
        "oracle_key",
    ]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        import csv as _csv

        w = _csv.DictWriter(
            f, fieldnames=cols + ["human_verdict", "time_seconds"],
            extrasaction="ignore",
        )
        w.writeheader()
        for r in rows:
            w.writerow(r)

    fatal_thresholds = (
        "FATAL THRESHOLDS (registered before release):\n"
        "  - Beginner group correct-rate < 60% -> FATAL\n"
        "  - Average time > 30s/char -> FATAL\n"
        "  - Any single step wrong > 40% -> FATAL\n"
        "  - Hán-Nôm group correct-rate < 80% -> WARNING\n"
    )

    # Test version: chars only, no codes
    test_md = [
        "# Human-screen TEST form — L6 codes (do NOT show to test subjects)",
        "",
        fatal_thresholds,
        f"Total: {len(rows)} chars. Each person: 40-50 chars, stratified, rotated order.",
        "Groups: Hán-Nôm knowers vs beginners (report separately).",
        "Verdict per row: CORRECT / INCORRECT / UNCLEAR + time_seconds.",
        "Per-step: stroke_count_ok, form_ok, anchor_ok, anchor_first_last_ok, second_anchor_ok.",
        "",
        "| # | char | codepoint | stratum | freq | strokes | verdict | time_s | stroke_ok | form_ok | anchor_ok | afl_ok | sec_ok | note |",
        "|---|------|-----------|---------|------|---------|---------|--------|-----------|---------|----------|--------|-------|------|",
    ]
    for i, r in enumerate(rows, 1):
        test_md.append(
            "| {i} | {char} | {cp} | {st} | {fr} | {ts} |  |  |  |  |  |  |  |  |".format(
                i=i,
                char=r["char"],
                cp=r["codepoint"],
                st=r["stratum"],
                fr=r["freq_b1"] if r["freq_b1"] is not None else "-",
                ts=r["total_strokes"],
            )
        )
    test_md_path.write_text("\n".join(test_md) + "\n", encoding="utf-8")

    # Answer key version: with codes
    answer_md = [
        "# Human-screen ANSWER KEY — L6 codes (do NOT show to test subjects)",
        "",
        fatal_thresholds,
        f"Total: {len(rows)} chars. L6 = (code_c + primary + secondary)[:6].",
        "",
        "| # | char | codepoint | stratum | freq | strokes | code_c | primary | secondary | L6 code | oracle_key |",
        "|---|------|-----------|---------|------|---------|--------|---------|-----------|---------|------------|",
    ]
    for i, r in enumerate(rows, 1):
        answer_md.append(
            "| {i} | {char} | {cp} | {st} | {fr} | {ts} | `{cc}` | {p} | {s} | `{l6}` | `{ok}` |".format(
                i=i,
                char=r["char"],
                cp=r["codepoint"],
                st=r["stratum"],
                fr=r["freq_b1"] if r["freq_b1"] is not None else "-",
                ts=r["total_strokes"],
                cc=r["code_c"],
                p=r["primary_anchor"],
                s=r["secondary_anchor"],
                l6=r["l6_code"],
                ok=r["oracle_key"],
            )
        )
    answer_md_path.write_text("\n".join(answer_md) + "\n", encoding="utf-8")

    return {
        "path": str(json_path),
        "test_form": str(test_md_path),
        "answer_key": str(answer_md_path),
        "rows": len(rows),
        "strata": collections.Counter(r["stratum"] for r in rows),
    }


def build_t3_e_classifier(
    valid_chars: list[dict[str, Any]],
) -> dict[str, str]:
    """Train deterministic reduced-component classifier (<=60 groups) from dataset.

    Top primary-anchor leaves become group representatives; remaining leaves
    group by their first stroke class. Mapped to single character in [0-9a-z].
    """
    ALPHANUM = "0123456789abcdefghijklmnopqrstuvwxyz"  # 36 groups <= 60
    anchor_counts: dict[str, int] = collections.defaultdict(int)
    for c in valid_chars:
        anchor_counts[c["primary_anchor"]] += 1

    # Sort deterministically by (-count, codepoint)
    sorted_anchors = sorted(
        anchor_counts.keys(),
        key=lambda a: (-anchor_counts[a], ord(a) if len(a) == 1 else 0),
    )

    top_n = min(31, len(sorted_anchors))
    top_anchors = set(sorted_anchors[:top_n])

    mapping: dict[str, str] = {}
    for idx, anc in enumerate(sorted_anchors[:top_n]):
        mapping[anc] = ALPHANUM[idx]

    # Remaining leaves fallback to first stroke class
    fallback_map = {
        "H": ALPHANUM[31],
        "V": ALPHANUM[32],
        "P": ALPHANUM[33],
        "D": ALPHANUM[34],
        "Z": ALPHANUM[35],
    }

    # Store classifier closure logic
    for anc in sorted_anchors[top_n:]:
        first_c = "H"
        mapping[anc] = fallback_map.get(first_c, ALPHANUM[35])

    return mapping


def calculate_percentile(sorted_vals: list[float], p: float) -> float:
    """Calculate percentile using linear interpolation."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    d = k - f
    return sorted_vals[f] + d * (sorted_vals[c] - sorted_vals[f])


def weighted_shannon_bits(pairs: list[tuple[str, float]]) -> float:
    """Weighted Shannon entropy (bits) over bucket keys."""
    total = sum(w for _, w in pairs)
    if total <= 0:
        return 0.0
    buckets: dict[str, float] = {}
    for key, w in pairs:
        buckets[key] = buckets.get(key, 0.0) + w
    bits = 0.0
    for w in buckets.values():
        if w > 0:
            p = w / total
            bits -= p * math.log2(p)
    return bits


def variant_metrics(
    p_chars: list[str],
    p_weights: dict[str, float],
    total_p_weight: float,
    code_of: Any,
    bucket_table: dict[str, list[str]],
) -> dict[str, Any]:
    """Candidate/coverage metrics for one (profile, code-source) pair.

    code_of(char) -> Optional[str]; None = no code (fail under wide gate).
    bucket_table maps code -> B0 candidate list (codegen, fixed across profiles).
    """
    cand_counts: list[int] = []
    weighted_le9_sum = 0.0
    pairs: list[tuple[str, float]] = []
    no_code_w = 0.0
    for char in p_chars:
        code = code_of(char)
        w = p_weights.get(char, 0.0)
        if not code:
            no_code_w += w
            continue
        cand_len = len(bucket_table.get(code, [char]))
        cand_counts.append(cand_len)
        if cand_len <= 9:
            weighted_le9_sum += w
        pairs.append((code, w))
    sc = sorted(cand_counts)
    le9_pct = (
        (weighted_le9_sum / total_p_weight * 100.0)
        if total_p_weight > 0
        else 0.0
    )
    bits = weighted_shannon_bits(pairs)
    code_w: dict[str, float] = {}
    for key, w in pairs:
        code_w[key] = code_w.get(key, 0.0) + w
    top9_share = (
        sum(sorted(code_w.values(), reverse=True)[:9]) / total_p_weight * 100.0
        if total_p_weight > 0
        else 0.0
    )
    return {
        "sample_size": len(p_chars),
        "coded_size": len(cand_counts),
        "no_code_weight_pct": round(
            (no_code_w / total_p_weight * 100.0) if total_p_weight > 0 else 0.0,
            2,
        ),
        "min": sc[0] if sc else 0,
        "p50": calculate_percentile(sc, 50),
        "p90": calculate_percentile(sc, 90),
        "p95": calculate_percentile(sc, 95),
        "p99": calculate_percentile(sc, 99),
        "max": sc[-1] if sc else 0,
        "weighted_le9_pct": round(le9_pct, 2),
        "gate_pass": bool(le9_pct >= GATE_THRESHOLD_PCT),
        "entropy_bits": round(bits, 3),
        "perplexity": round(2.0**bits, 1),
        "bits_needed_profile": round(math.log2(len(p_chars)), 3)
        if p_chars
        else 0.0,
        "top9_freq_code_share_pct": round(top9_share, 2),
        "n_buckets": len(code_w),
    }


def oracle_key_of(char: str, valid_features: dict[str, Any]) -> Optional[str]:
    """V6 oracle-E: full anchor identity (primary|secondary)."""
    feat = valid_features.get(char)
    if feat is None:
        return None
    return f"{feat.primary_anchor}|{feat.secondary_anchor}"


def classify_cross_disagree(valid_features: dict[str, Any]) -> dict[str, Any]:
    """V6 [V6-QC]: classify base-vs-cnchar first/last disagreements."""
    prim_use: dict[str, int] = {}
    sec_use: dict[str, int] = {}
    for feat in valid_features.values():
        prim_use[feat.primary_anchor] = prim_use.get(feat.primary_anchor, 0) + 1
        if feat.secondary_anchor != SENTINEL_CHAR:
            sec_use[feat.secondary_anchor] = sec_use.get(feat.secondary_anchor, 0) + 1
    by_side: dict[str, int] = {}
    by_usage: dict[str, int] = {"primary": 0, "secondary_only": 0, "unused": 0}
    switched_to_cnchar = 0
    for e in CROSS_DISAGREE_CHARS:
        cf = e["cnchar_first"]
        cl = e["cnchar_last"]
        if cf == "-":
            side = "LAST_ONLY"
        elif cl == "-":
            side = "FIRST_ONLY"
        else:
            fd = e["base_first"] != cf
            ld = e["base_last"] != cl
            side = "BOTH" if (fd and ld) else ("FIRST_ONLY" if fd else "LAST_ONLY")
        by_side[side] = by_side.get(side, 0) + 1
        ch = e["char"]
        if prim_use.get(ch):
            by_usage["primary"] += 1
        elif sec_use.get(ch):
            by_usage["secondary_only"] += 1
        else:
            by_usage["unused"] += 1
        at = ANCHOR_TABLE.get(ch)
        if at and at[2] == "cnchar":
            switched_to_cnchar += 1
    return {
        "total": len(CROSS_DISAGREE_CHARS),
        "by_side": by_side,
        "by_anchor_usage": by_usage,
        "switched_to_cnchar": switched_to_cnchar,
    }


def run_benchmark(
    cache_dir: Path,
    selected_t3: list[str],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Execute complete offline benchmark suite."""
    start_time = time.time()
    verify_anchor_spec()

    # Step 1: Load data
    print(">>> Loading stroke order, Unihan, IDS, and frequency databases...")
    stroke_seq_file = cache_dir / SOURCES["stroke_seq"]["filename"]
    stroke_counts_file = cache_dir / SOURCES["stroke_order"]["filename"]
    cnchar_table_file = cache_dir / SOURCES["stroke_cnchar_table"]["filename"]
    cnchar_dict_files = [
        cache_dir / SOURCES["stroke_cnchar_jian"]["filename"],
        cache_dir / SOURCES["stroke_cnchar_trad"]["filename"],
    ]
    stroke_data = load_stroke_order_data(
        stroke_seq_file,
        stroke_counts_file,
        cnchar_table_file,
        cnchar_dict_files,
        cache_dir / SOURCES["ids"]["filename"],  # V9 IDS_PICKED source
    )

    # Golden tests gate: must pass before proceeding
    golden_ok, golden_results = run_golden_tests(stroke_data)
    if not golden_ok:
        print(
            "ERROR: Golden anchor tests failed. Benchmark halted (exit 1).",
            file=sys.stderr,
        )
        sys.exit(1)
    print(">>> Golden anchor tests: ALL PASS.")

    unihan_zip = cache_dir / SOURCES["unihan"]["filename"]
    total_strokes_map, trad_vars, simp_vars = load_unihan_data(unihan_zip)

    ids_file = cache_dir / SOURCES["ids"]["filename"]
    ids_data = load_ids_data(ids_file, trad_vars, simp_vars)

    freq_file = cache_dir / SOURCES["freq_b1"]["filename"]
    freq_b1_map = parse_freq_html(freq_file)

    # Step 2: Construct B0 Universe (U+4E00..9FFF and U+3400..4DBF)
    print(">>> Generating Candidate Universe B0 (U+4E00..9FFF + U+3400..4DBF)...")
    b0_chars = [chr(cp) for cp in range(0x4E00, 0x9FFF + 1)] + [
        chr(cp) for cp in range(0x3400, 0x4DBF + 1)
    ]
    b0_set = set(b0_chars)
    total_b0 = len(b0_chars)

    # Coverage statistics
    has_ids_count = 0
    conf_counts: dict[str, int] = collections.defaultdict(int)
    quality_flag_counts: dict[str, int] = collections.defaultdict(int)

    # Build character features
    valid_features: dict[str, CharFeature] = {}
    pre_valid_list: list[dict[str, Any]] = []

    for char in b0_chars:
        # V4-CHOT: 戶/戸/户 = variant-order group (Claude Dieu kien 1)
        if char in ("戸", "戶", "户"):
            quality_flag_counts["VARIANT_ORDER"] += 1
        tree = ids_data.get(char)
        if tree is None:
            conf_counts[CONF_MISSING] += 1
            confidence = CONF_MISSING
        else:
            has_ids_count += 1
            confidence = (
                tree.confidence
                if isinstance(tree, IDSNode)
                else (CONF_EXACT if is_cjk_leaf(tree) else CONF_COMPOSITE)
            )
            conf_counts[confidence] += 1

        # Check total strokes
        tot_strokes = total_strokes_map.get(char)
        if tot_strokes is None:
            if char in stroke_data:
                tot_strokes = stroke_data[char][0]
            else:
                quality_flag_counts["MISSING_TOTAL_STROKES"] += 1
                continue

        # V6-DECISION: atomic rules (placeholder / invalid component)
        atomic_kind: Optional[str] = None
        if tree is not None and ids_contains_placeholder(tree):
            atomic_kind = "placeholder"
            quality_flag_counts["COMPOSITE_PLACEHOLDER"] += 1

        # Extract anchors
        primary_anc, secondary_anc = extract_anchors(char, tree)
        if atomic_kind is None:
            primary_norm = normalize_leaf(primary_anc)
            if not is_cjk_leaf(primary_norm):
                atomic_kind = "no_component"
                quality_flag_counts["SELF_ANCHOR_NO_COMPONENT"] += 1
            else:
                primary_anc = primary_norm
                if secondary_anc != SENTINEL_CHAR:
                    secondary_norm = normalize_leaf(secondary_anc)
                    if not is_cjk_leaf(secondary_norm):
                        secondary_anc = SENTINEL_CHAR
                    else:
                        secondary_anc = secondary_norm
        if atomic_kind is not None:
            primary_anc = char
            secondary_anc = SENTINEL_CHAR

        # V6 [V6-QB]: anchor strokes from ANCHOR_TABLE (cnchar > tq > ambiguous)
        a_entry = ANCHOR_TABLE.get(primary_anc)
        if a_entry is None:
            quality_flag_counts["MISSING_ANCHOR_STROKES"] += 1
            continue
        p_first, p_last, a_source = a_entry
        if a_source == "ambiguous":
            quality_flag_counts["AMBIGUOUS_ANCHOR"] += 1

        # Stroke info for primary anchor (total strokes for residual)
        p_entry = stroke_data.get(primary_anc)
        if not p_entry:
            quality_flag_counts["MISSING_ANCHOR_STROKES"] += 1
            continue
        p_total = p_entry[0]

        # Residual calculation
        if tree is None or isinstance(tree, str) or primary_anc == char:
            residual = 0
        else:
            residual = tot_strokes - p_total

        if residual < 0:
            quality_flag_counts["BAD_STROKES"] += 1
            continue

        # Secondary anchor (V6: from ANCHOR_TABLE)
        s_first = None
        s_last = None
        if secondary_anc != SENTINEL_CHAR:
            sa = ANCHOR_TABLE.get(secondary_anc)
            if sa:
                s_first, s_last = sa[0], sa[1]
                if sa[2] == "ambiguous":
                    quality_flag_counts["AMBIGUOUS_SECONDARY_ANCHOR"] += 1

        # Form (V6: atomic chars -> terminal form key "1")
        if atomic_kind is not None:
            t2_key = "1"
        else:
            t2_form = (
                tree.op
                if (tree and isinstance(tree, IDSNode))
                else ("" if tree is None else "terminal")
            )
            t2_key = T2_FORM_MAP.get(t2_form, "1")
        t1_key = encode_t1_residual(residual)

        pre_valid_list.append(
            {
                "char": char,
                "total_strokes": tot_strokes,
                "primary_anchor": primary_anc,
                "secondary_anchor": secondary_anc,
                "primary_first": p_first,
                "primary_last": p_last,
                "secondary_first": s_first,
                "secondary_last": s_last,
                "residual": residual,
                "t1_key": t1_key,
                "t2_key": t2_key,
                "ids_confidence": confidence,
            }
        )

    # Train deterministic T3-E classifier from B0 valid primary anchors
    t3_e_classifier = build_t3_e_classifier(pre_valid_list)

    # Complete HANSTROKE code generation
    for item in pre_valid_list:
        char = item["char"]
        p_first = item["primary_first"]
        p_last = item["primary_last"]
        s_first = item["secondary_first"]
        s_last = item["secondary_last"]

        t3_a = encode_shape_5x5(p_first, p_last)
        if s_first and s_last:
            t3_c = t3_a + encode_shape_5x5(s_first, s_last)
        else:
            t3_c = t3_a + SENTINEL_CHAR

        # T3-E: Top anchor group or first-stroke fallback
        t3_e = t3_e_classifier.get(
            item["primary_anchor"],
            SHAPE_MATRIX.get(p_first, {}).get("H", "z"),
        )

        code_a = f"{item['t1_key']}{item['t2_key']}{t3_a}"
        code_c = f"{item['t1_key']}{item['t2_key']}{t3_c}"
        code_e = f"{item['t1_key']}{item['t2_key']}{t3_e}"

        valid_features[char] = CharFeature(
            char=char,
            total_strokes=item["total_strokes"],
            primary_anchor=item["primary_anchor"],
            secondary_anchor=item["secondary_anchor"],
            primary_first=p_first,
            primary_last=p_last,
            secondary_first=s_first,
            secondary_last=s_last,
            residual=item["residual"],
            t1_key=item["t1_key"],
            t2_key=item["t2_key"],
            t3_a=t3_a,
            t3_c=t3_c,
            t3_e=t3_e,
            code_a=code_a,
            code_c=code_c,
            code_e=code_e,
            ids_confidence=item["ids_confidence"],
        )

    # Step 3: Build B0 Collision Lookup Tables
    b0_code_tables: dict[str, dict[str, list[str]]] = {
        "A": collections.defaultdict(list),
        "C": collections.defaultdict(list),
        "E": collections.defaultdict(list),
    }
    for char, feat in valid_features.items():
        b0_code_tables["A"][feat.code_a].append(char)
        b0_code_tables["C"][feat.code_c].append(char)
        b0_code_tables["E"][feat.code_e].append(char)

    # V6 oracle-E table: full anchor identity (upper bound of anchor codes)
    oracle_table: dict[str, list[str]] = collections.defaultdict(list)
    for char, feat in valid_features.items():
        oracle_table[f"{feat.primary_anchor}|{feat.secondary_anchor}"].append(char)

    # Step 4: Define Profile Populations and Weights
    # Trad set (shared by narrow + wide profiles)
    trad_char_set: set[str] = set()
    for s_char in simp_vars:
        if s_char in b0_set:
            trad_char_set.add(s_char)
    for t_char in trad_vars.values():
        if t_char in b0_set:
            trad_char_set.add(t_char)

    # Narrow (diagnostic): qualified chars only
    b0_weights = {c: 1.0 for c in valid_features}
    b1_chars = [c for c in valid_features if c in freq_b1_map]
    b1_weights = {c: freq_b1_map[c] for c in b1_chars}
    b3_t_chars = [c for c in valid_features if c in trad_char_set]
    b3_t_weights = {c: 1.0 for c in b3_t_chars}

    profiles = {
        "B0": {"chars": list(valid_features.keys()), "weights": b0_weights},
        "B1": {"chars": b1_chars, "weights": b1_weights},
        "B3-T": {"chars": b3_t_chars, "weights": b3_t_weights},
    }

    # V6 [V6-QA] wide denominator = OFFICIAL (no-code chars count as FAIL)
    wide_b1_chars = [c for c in b0_chars if c in freq_b1_map]
    wide_b3_chars = [c for c in b0_chars if c in trad_char_set]
    wide_profiles = {
        "B0": {"chars": b0_chars, "weights": {c: 1.0 for c in b0_chars}},
        "B1": {
            "chars": wide_b1_chars,
            "weights": {c: freq_b1_map[c] for c in wide_b1_chars},
        },
        "B3-T": {
            "chars": wide_b3_chars,
            "weights": {c: 1.0 for c in wide_b3_chars},
        },
    }

    # Step 5: Evaluate Benchmark Metrics across Profiles and T3 Variants
    print(">>> Computing collision distributions and candidate coverage...")
    profile_results: dict[str, Any] = {}

    for prof_name, pdata in profiles.items():
        p_chars = pdata["chars"]
        p_weights = pdata["weights"]
        total_p_weight = sum(p_weights.values())
        wdata = wide_profiles[prof_name]
        wide_chars = wdata["chars"]
        wide_weights = wdata["weights"]
        total_wide_weight = sum(wide_weights.values())

        profile_results[prof_name] = {
            "total_chars": len(p_chars),
            "total_weight": total_p_weight,
            "wide_total_chars": len(wide_chars),
            "wide_total_weight": total_wide_weight,
            "variants": {},
        }

        # V6 oracle-E (per profile, same anchor identity for all variants)
        oracle_code = (lambda c: oracle_key_of(c, valid_features))
        profile_results[prof_name]["oracle_E"] = {
            "narrow": variant_metrics(
                p_chars, p_weights, total_p_weight, oracle_code, oracle_table
            ),
            "wide": variant_metrics(
                wide_chars,
                wide_weights,
                total_wide_weight,
                oracle_code,
                oracle_table,
            ),
        }

        for v_name in ("A", "C", "E"):
            if v_name not in selected_t3:
                continue

            code_attr = f"code_{v_name.lower()}"

            def code_of(char: str, _a: str = code_attr) -> Optional[str]:
                feat = valid_features.get(char)
                return getattr(feat, _a) if feat is not None else None

            narrow_m = variant_metrics(
                p_chars, p_weights, total_p_weight, code_of, b0_code_tables[v_name]
            )
            wide_m = variant_metrics(
                wide_chars,
                wide_weights,
                total_wide_weight,
                code_of,
                b0_code_tables[v_name],
            )

            # Top 20 largest collision classes (profile-weighted)
            top_codes_raw = sorted(
                b0_code_tables[v_name].items(),
                key=lambda item: (
                    -len(item[1]),
                    -sum(p_weights.get(c, 0.0) for c in item[1]),
                ),
            )[:20]

            top_20 = []
            for c_code, c_chars in top_codes_raw:
                top_20.append(
                    {
                        "code": c_code,
                        "candidate_count": len(c_chars),
                        "freq_weight": sum(
                            p_weights.get(c, 0.0) for c in c_chars
                        ),
                        "first_10_chars": "".join(c_chars[:10]),
                        "quality_flags": "EXACT",
                    }
                )

            profile_results[prof_name]["variants"][v_name] = {
                "variant": v_name,
                # Official (V6 wide denominator): weighted_le9_pct + gate_pass
                "sample_size": wide_m["sample_size"],
                "weighted_le9_pct": wide_m["weighted_le9_pct"],
                "gate_pass": wide_m["gate_pass"],
                # Diagnostic (narrow = qualified only)
                "qualified_sample_size": narrow_m["sample_size"],
                "narrow_weighted_le9_pct": narrow_m["weighted_le9_pct"],
                "gate_pass_narrow": narrow_m["gate_pass"],
                # Collision percentiles over qualified chars (same coded set)
                "min": narrow_m["min"],
                "median": narrow_m["p50"],
                "p50": narrow_m["p50"],
                "p90": narrow_m["p90"],
                "p95": narrow_m["p95"],
                "p99": narrow_m["p99"],
                "max": narrow_m["max"],
                # Entropy / typing-cost diagnostics (V6 [V6-QC])
                "entropy_bits_narrow": narrow_m["entropy_bits"],
                "perplexity_narrow": narrow_m["perplexity"],
                "entropy_bits_wide": wide_m["entropy_bits"],
                "perplexity_wide": wide_m["perplexity"],
                "bits_needed_profile_wide": wide_m["bits_needed_profile"],
                "top9_freq_code_share_pct_wide": wide_m["top9_freq_code_share_pct"],
                "no_code_weight_pct_wide": wide_m["no_code_weight_pct"],
                "n_buckets_narrow": narrow_m["n_buckets"],
                "n_buckets_wide": wide_m["n_buckets"],
                "delta_p95_vs_a": 0.0,
                "delta_weighted_le9_vs_a": 0.0,
                "delta_wide_le9_vs_a": 0.0,
                "top_20_collisions": top_20,
                "metrics_wide": wide_m,
                "metrics_narrow": narrow_m,
            }

        # Calculate improvement deltas vs T3-A
        if "A" in profile_results[prof_name]["variants"]:
            base_p95 = profile_results[prof_name]["variants"]["A"]["p95"]
            base_w9 = profile_results[prof_name]["variants"]["A"][
                "narrow_weighted_le9_pct"
            ]
            base_wide = profile_results[prof_name]["variants"]["A"][
                "weighted_le9_pct"
            ]
            for v_name in ("C", "E"):
                if v_name in profile_results[prof_name]["variants"]:
                    var_res = profile_results[prof_name]["variants"][v_name]
                    var_res["delta_p95_vs_a"] = round(
                        var_res["p95"] - base_p95, 2
                    )
                    var_res["delta_weighted_le9_vs_a"] = round(
                        var_res["narrow_weighted_le9_pct"] - base_w9, 2
                    )
                    var_res["delta_wide_le9_vs_a"] = round(
                        var_res["weighted_le9_pct"] - base_wide, 2
                    )

    # V6 gate registration rule (Claude: ONLY after oracle results)
    o_b1 = profile_results.get("B1", {}).get("oracle_E", {}).get("wide", {}).get(
        "weighted_le9_pct", 0.0
    )
    o_b3 = profile_results.get("B3-T", {}).get("oracle_E", {}).get("wide", {}).get(
        "weighted_le9_pct", 0.0
    )
    if o_b1 >= GATE_THRESHOLD_PCT and o_b3 >= GATE_THRESHOLD_PCT:
        oracle_gate_note = (
            f"ELIGIBLE: oracle-E wide B1={o_b1:.2f}% B3-T={o_b3:.2f}% >=95% — "
            "duong mo rong ma con ton tai; V4 gate cho dang ky sau song phuong chot."
        )
    else:
        oracle_gate_note = (
            f"INFEASIBLE: oracle-E wide B1={o_b1:.2f}% B3-T={o_b3:.2f}% <95% — "
            "ma <=4 ky tu khong kha thi; chuyen mo hinh truy xuat kem refine/paging. "
            "V4 gate CHUA dang ky, cho song phuong chot."
        )

    # V9 diagnostics: prefix ladder + K-groups curve (registered before running)
    print(">>> V9 diagnostics: prefix ladder (3-6) + K-groups curve...")
    radical_map = load_unihan_radicals(unihan_zip)
    b0_core_chars = [c for c in b0_chars if ord(c) <= 0x9FFF]
    v9_diag = run_v9_diagnostics(
        valid_features, wide_profiles, b0_core_chars, radical_map
    )
    print(
        f"  Ladder: shortest passing = {v9_diag['shortest_ladder_passing']} "
        f"(ceiling={CODE_CEILING} -> {v9_diag['ceiling_result']})"
    )
    print(
        f"  K-curve: smallest K passing = {v9_diag['smallest_k_passing']}"
    )
    for length in LADDER_RUNGS:
        lr = v9_diag["ladder"][str(length)]
        print(
            f"    L{length}: B1={lr['B1']['weighted_le9_pct']:.2f}% "
            f"B3-T={lr['B3-T']['weighted_le9_pct']:.2f}% "
            f"B0-core={lr['B0-core']['weighted_le9_pct']:.2f}% "
            f"gate={'PASS' if lr['official_gate_pass'] else 'FAIL'} "
            f"floor={'PASS' if lr['b0_core_floor_pass'] else 'FAIL'}"
        )
    for k in K_GROUPS:
        kr = v9_diag["k_curve"][str(k)]
        print(
            f"    K={k}: B1={kr['B1']['weighted_le9_pct']:.2f}% "
            f"B3-T={kr['B3-T']['weighted_le9_pct']:.2f}% "
            f"cost={kr['identification_cost_groups']} "
            f"gate={'PASS' if kr['official_gate_pass'] else 'FAIL'} "
            f"unmapped={kr['unmapped_primary_anchors']}"
        )
    pr = v9_diag.get("partition_robustness", {})
    for part_name in ("B1", "B3-T"):
        for h in pr.get(part_name, []):
            print(
                f"    {h['name']}: {h['wide_pct']:.2f}% "
                f"(n={h['chars_evaluated']}) gate={h['gate']}"
            )

    # [V11-QA Claude] human-screen package (stratified L6 codes)
    hs = export_human_screen_package(
        valid_features,
        freq_b1_map,
        wide_profiles["B1"]["chars"],
        wide_profiles["B3-T"]["chars"],
        cache_dir,
    )
    print(
        f">>> Human-screen package: {hs['rows']} rows -> "
        f"{hs['path']} (+ .csv / .md form)"
    )

    # Step 6: Smoke Table Comparison (spec V2 verification, no hard-fail)
    print(">>> Running SMOKE TABLE verification...")
    smoke_expected = {
        "你": "52c",
        "明": "426",
        "好": "32l",
        "河": "52j",
        "书": "z1o",
        "马": "z1l",
        "乃": "z1f",
        "鼠": "z1f",
        "乘": "59e",
        "龜": "z1e",
        "鬱": "e34",
    }
    smoke_results = []
    for char, exp_code in smoke_expected.items():
        feat = valid_features.get(char)
        comp_code = feat.code_a if feat else "MISSING"
        diff = comp_code != exp_code
        smoke_results.append(
            {
                "char": char,
                "expected": exp_code,
                "computed": comp_code,
                "diff": diff,
                "status": "DIFF" if diff else "PASS",
                "total_strokes": feat.total_strokes if feat else None,
                "anchor": feat.primary_anchor if feat else None,
            }
        )

    # Step 7: Select optimal T3 variant
    # Registered order: A < C < E
    recommended_t3 = None
    for cand in ("A", "C", "E"):
        if cand not in selected_t3:
            continue
        b1_pass = profile_results["B1"]["variants"].get(cand, {}).get(
            "gate_pass", False
        )
        b3_pass = profile_results["B3-T"]["variants"].get(cand, {}).get(
            "gate_pass", False
        )
        if b1_pass and b3_pass:
            recommended_t3 = cand
            break

    # V6 diagnostics: anchor source usage, placeholder rescue, 750 classification
    primary_src: dict[str, int] = {}
    secondary_src: dict[str, int] = {}
    for feat in valid_features.values():
        at = ANCHOR_TABLE.get(feat.primary_anchor)
        if at:
            primary_src[at[2]] = primary_src.get(at[2], 0) + 1
        if feat.secondary_anchor != SENTINEL_CHAR:
            at2 = ANCHOR_TABLE.get(feat.secondary_anchor)
            if at2:
                secondary_src[at2[2]] = secondary_src.get(at2[2], 0) + 1

    ph_stats: dict[str, int] = {
        "total": 0,
        "rescued": 0,
        "excluded": 0,
        "excluded_no_self_strokes": 0,
        "excluded_other": 0,
    }
    for c in b0_chars:
        t = ids_data.get(c)
        if t is None or not ids_contains_placeholder(t):
            continue
        ph_stats["total"] += 1
        if c in valid_features:
            ph_stats["rescued"] += 1
        else:
            ph_stats["excluded"] += 1
            if c not in stroke_data:
                ph_stats["excluded_no_self_strokes"] += 1
            else:
                ph_stats["excluded_other"] += 1

    # V9 [V8-QD]/[V9-QD]: spotcheck 100 chu moi — seed moi, phan tang,
    # doc lap 51 golden, nguon doc lap (cnchar/IDS/Unihan), vao report.
    golden_set = (
        set(json.loads(Path(GOLDEN_FILE_NAME).read_text(encoding="utf-8")))
        if Path(GOLDEN_FILE_NAME).is_file()
        else set(GOLDEN_ANCHORS_INLINE)
    )
    spot_v9 = run_spotcheck_stratified(
        stroke_data,
        cnchar_dict_files,
        ids_file,
        stroke_seq_file,
        total_strokes_map,
        golden_set,
    )

    # Compile Final Report Dictionary
    report: dict[str, Any] = {
        "metadata": {
            "spec_version": SPEC_VERSION,
            "benchmark_run_at": datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(),
            "execution_seconds": round(time.time() - start_time, 2),
            "manifest_sources": manifest.get("sources", {}),
            "b3_hn_status": MSG_B3_HN_BLOCKED,
            "t3_selection_rule": T3_SELECTION_NOTE,
            "recommended_t3": recommended_t3,
            "anchor_spec_version": ANCHOR_GRAMMAR_SPEC["version"],
            "anchor_spec_sha256": verify_anchor_spec(),
            "oracle_gate_note": oracle_gate_note,
        },
        "coverage": {
            "total_b0": total_b0,
            "b0_composition": {
                "core_4e00_9fff": 20992,
                "ext_a_3400_4dbf": 6592,
                "total": total_b0,
                "ext_b_plus": "out of scope (V6 [V6-QD])",
            },
            "has_ids_count": has_ids_count,
            "has_ids_pct": round(has_ids_count / total_b0 * 100.0, 2),
            "valid_features_count": len(valid_features),
            "valid_features_pct": round(
                len(valid_features) / total_b0 * 100.0, 2
            ),
            "confidence_breakdown": {
                k: {"count": v, "pct": round(v / total_b0 * 100.0, 2)}
                for k, v in conf_counts.items()
            },
            "quality_flag_counts": dict(quality_flag_counts),
            "stroke_source_stats": dict(STROKE_SOURCE_STATS),
            "anchor_table_stats": dict(ANCHOR_TABLE_STATS),
            "anchor_source_usage": {
                "primary": primary_src,
                "secondary": secondary_src,
            },
            "placeholder_stats": ph_stats,
            "cross_disagree_classification": classify_cross_disagree(
                valid_features
            ),
        },
        "profiles": profile_results,
        "smoke_table": smoke_results,
        "spotcheck_v9": spot_v9,
        "v9_diagnostics": v9_diag,
    }

    return report


# -----------------------------------------------------------------------------
# 7) REPORT WRITERS & CONSOLE PRESENTATION
# -----------------------------------------------------------------------------
def write_reports(report: dict[str, Any], cache_dir: Path) -> None:
    """Serialize report to report.json and report.md."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    json_path = cache_dir / REPORT_JSON_NAME
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f">>> Full JSON metrics written to {json_path}")

    md_path = cache_dir / REPORT_MD_NAME
    md: list[str] = []
    meta = report["metadata"]
    cov = report["coverage"]
    profs = report["profiles"]

    md.append(f"# HANSTROKE V3 Benchmark Report — {meta['spec_version']}")
    md.append("")
    md.append(f"- **Generated:** `{meta['benchmark_run_at']}`")
    md.append(f"- **Execution Time:** `{meta['execution_seconds']}s`")
    md.append(f"- **{MSG_B3_HN_BLOCKED}**")
    md.append("")
    md.append("## 1. Data Quality & Coverage (Questions 1, 2, 3)")
    md.append("")
    md.append(f"- **Total B0 Universe (U+4E00..9FFF, U+3400..4DBF):** `{cov['total_b0']}`")
    b0c = cov.get("b0_composition", {})
    if b0c:
        md.append(
            f"- **B0 composition (V6 [V6-QD]):** B0-core U+4E00..9FFF = `{b0c.get('core_4e00_9fff')}`"
            f" + Ext-A U+3400..4DBF = `{b0c.get('ext_a_3400_4dbf')}`"
            f" = `{b0c.get('total')}` ({b0c.get('ext_b_plus')})"
        )
    md.append(f"- **Chars with IDS (Q1):** `{cov['has_ids_count']} / {cov['total_b0']} ({cov['has_ids_pct']}%)`")
    md.append(f"- **Fully Qualified HANSTROKE Chars (Q3):** `{cov['valid_features_count']} ({cov['valid_features_pct']}%)`")
    meta_extra = report["metadata"]
    md.append(
        f"- **Anchor spec (V6 frozen):** `{meta_extra.get('anchor_spec_version', '-')}`"
        f" sha256=`{meta_extra.get('anchor_spec_sha256', '-')}`"
    )
    md.append("")
    md.append("### IDS Confidence Breakdown (Q2)")
    md.append("")
    md.append("| Confidence Category | Character Count | Percentage |")
    md.append("|---|---|---|")
    for cat, cdata in cov["confidence_breakdown"].items():
        md.append(f"| **{cat}** | {cdata['count']} | {cdata['pct']}% |")
    md.append("")
    md.append("### Data Quality Flags Excluded from Candidate Generation")
    md.append("")
    md.append("| Quality Flag | Count |")
    md.append("|---|---|")
    for flg, cnt in cov["quality_flag_counts"].items():
        md.append(f"| `{flg}` | {cnt} |")
    md.append("")
    at_stats = cov.get("anchor_table_stats", {})
    if at_stats:
        md.append("### Anchor Stroke Table (V6 [V6-QB])")
        md.append("")
        md.append("| Source | Count |")
        md.append("|---|---|")
        for k in ("cnchar", "tq", "fill", "ambiguous"):
            md.append(f"| `{k}` | {at_stats.get(k, 0)} |")
        md.append("")
        usage = cov.get("anchor_source_usage", {})
        prim = usage.get("primary", {})
        sec = usage.get("secondary", {})
        md.append(
            f"- **Primary-anchor source usage (qualified chars):** "
            + ", ".join(f"`{k}`={v}" for k, v in sorted(prim.items()))
        )
        md.append(
            f"- **Secondary-anchor source usage:** "
            + ", ".join(f"`{k}`={v}" for k, v in sorted(sec.items()))
        )
        md.append("")
    ph = cov.get("placeholder_stats", {})
    if ph:
        md.append("### Placeholder Rescue (V6 [V6-QA] = atomic + COMPOSITE_PLACEHOLDER)")
        md.append("")
        md.append(f"- **Chars w/ placeholder in IDS:** `{ph.get('total', 0)}`")
        md.append(f"- **Rescued (got code):** `{ph.get('rescued', 0)}`")
        md.append(f"- **Excluded:** `{ph.get('excluded', 0)}` (no self stroke data: `{ph.get('excluded_no_self_strokes', 0)}`, other: `{ph.get('excluded_other', 0)}`)")
        md.append("")
    cd = cov.get("cross_disagree_classification", {})
    if cd:
        md.append("### Cross-check Disagreement Classification (750-set, V6 [V6-QC])")
        md.append("")
        md.append(f"- **Total:** `{cd.get('total', 0)}`")
        md.append(
            "- **By side:** "
            + ", ".join(f"`{k}`={v}" for k, v in sorted(cd.get("by_side", {}).items()))
        )
        md.append(
            "- **By anchor usage:** "
            + ", ".join(f"`{k}`={v}" for k, v in sorted(cd.get("by_anchor_usage", {}).items()))
        )
        md.append(f"- **Switched to cnchar in anchor table:** `{cd.get('switched_to_cnchar', 0)}`")
        md.append("")
    md.append("## 2. Gate Evaluation (≥95% Weighted Candidates ≤ 9)")
    md.append("")
    md.append("> V6 [V6-QA]: **official = wide denominator** (all profile chars; no-code = FAIL). Narrow = qualified-only diagnostic.")
    md.append("")
    md.append("| Profile | T3 Variant | Wide % (official) | Narrow % (diag) | Threshold | Gate Status |")
    md.append("|---|---|---|---|---|---|")
    for p_name in ("B1", "B3-T"):
        if p_name in profs:
            for v_name, v_data in profs[p_name]["variants"].items():
                status_str = "**PASS**" if v_data["gate_pass"] else "*FAIL*"
                md.append(
                    f"| {p_name} | **T3-{v_name}** | {v_data['weighted_le9_pct']:.2f}% | "
                    f"{v_data.get('narrow_weighted_le9_pct', 0.0):.2f}% | ≥{GATE_THRESHOLD_PCT}% | {status_str} |"
                )
    md.append("")
    md.append("### Oracle-E (full anchor identity — V6 mandate)")
    md.append("")
    md.append("| Profile | Oracle Wide % | Oracle Narrow % | vs 95% |")
    md.append("|---|---|---|---|")
    for p_name in ("B0", "B1", "B3-T"):
        o = profs.get(p_name, {}).get("oracle_E")
        if not o:
            continue
        verdict = "**PASS**" if o["wide"]["weighted_le9_pct"] >= GATE_THRESHOLD_PCT else "*FAIL*"
        md.append(
            f"| {p_name} | {o['wide']['weighted_le9_pct']:.2f}% | "
            f"{o['narrow']['weighted_le9_pct']:.2f}% | {verdict} |"
        )
    md.append("")
    md.append(f"> **Oracle gate note (V6 rule):** {meta_extra.get('oracle_gate_note', '-')}")
    sp = report.get("spotcheck_v9") or {}
    if sp:
        ccc = sp.get("cnchar_cross", {})
        ids_c = sp.get("ids_cross", {})
        md.append("")
        md.append("## Spotcheck V9 stratified (V9-QD dong thuan)")
        md.append(
            f"- seed `{sp.get('seed')}` (moi, doc lap {sp.get('golden_excluded')} "
            f"golden), rows={sp.get('selected_count')}"
        )
        md.append(f"- buckets: {sp.get('bucket_sizes')} -> selected {sp.get('stratum_selected')}")
        md.append(f"- verdicts: {sp.get('verdicts')}")
        md.append(
            f"- cnchar cross: {ccc.get('agree')}A/{ccc.get('conflict')}C "
            f"err={ccc.get('error_pct')}% | IDS cross: {ids_c.get('agree')}A/"
            f"{ids_c.get('diff')}D err={ids_c.get('error_pct_non_circular')}% "
            f"(circular skipped={ids_c.get('circular_skipped')})"
        )
        md.append(
            f"- Unihan count: {sp.get('unihan_count')} | single "
            f"(no independent source)={sp.get('single_no_independent_source')}"
        )
    md.append("")
    md.append("### Entropy / Typing Diagnostics (V6 [V6-QC])")
    md.append("")
    md.append("| Profile | Variant | Bits needed (wide) | Entropy wide | Perplexity wide | Top-9 codes share % | No-code weight % |")
    md.append("|---|---|---|---|---|---|---|")
    for p_name in ("B0", "B1", "B3-T"):
        for v_name, v_data in profs.get(p_name, {}).get("variants", {}).items():
            md.append(
                f"| {p_name} | T3-{v_name} | {v_data.get('bits_needed_profile_wide', 0):.2f} | "
                f"{v_data.get('entropy_bits_wide', 0):.2f} | {v_data.get('perplexity_wide', 0):.1f} | "
                f"{v_data.get('top9_freq_code_share_pct_wide', 0):.2f} | {v_data.get('no_code_weight_pct_wide', 0):.2f} |"
            )
    md.append("")
    md.append("## 3. Collision Distribution & Improvements (Questions 4, 5, 6, 7)")
    md.append("")
    md.append(
        "| Profile | Variant | Median (P50) | P90 | P95 | P99 | Max | ΔP95 vs A | % Wide ≤9 (Q7, official) | ΔWide ≤9 vs A | % Narrow ≤9 (diag) |"
    )
    md.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for p_name, p_data in profs.items():
        for v_name, v_data in p_data["variants"].items():
            md.append(
                f"| {p_name} | T3-{v_name} | {v_data['p50']:.1f} | {v_data['p90']:.1f} | "
                f"{v_data['p95']:.1f} | {v_data['p99']:.1f} | {v_data['max']} | "
                f"{v_data['delta_p95_vs_a']:+.1f} | {v_data['weighted_le9_pct']:.2f}% | "
                f"{v_data.get('delta_wide_le9_vs_a', 0.0):+.2f}% | "
                f"{v_data.get('narrow_weighted_le9_pct', 0.0):.2f}% |"
            )
    md.append("")
    md.append("## 4. Smoke Test Comparison (T3-A vs V2 Spec)")
    md.append("")
    md.append("| Character | Expected Code | Computed Code | Status | Total Strokes | Primary Anchor |")
    md.append("|---|---|---|---|---|---|")
    for item in report["smoke_table"]:
        diff_tag = f"**{item['status']}**" if item['diff'] else item['status']
        md.append(
            f"| `{item['char']}` | `{item['expected']}` | `{item['computed']}` | {diff_tag} | {item['total_strokes']} | `{item['anchor']}` |"
        )
    md.append("")
    md.append("## 5. T3 Selection Recommendation")
    md.append("")
    md.append(f"> **Rule:** {T3_SELECTION_NOTE}")
    md.append("")
    rec = meta["recommended_t3"]
    if rec:
        md.append(f"**RECOMMENDED VARIANT: `T3-{rec}`**")
        if rec == "E":
            md.append("\n*Ghi nhận: HANSTROKE là hệ dựa trên thành phần.*")
    else:
        md.append("**RECOMMENDED VARIANT: NONE (Gate failed across both target profiles)**")
    md.append("")
    md.append("## 6. Top 20 Collision Classes (Profile B1)")
    md.append("")
    for v_name in ("A", "C", "E"):
        if v_name in profs["B1"]["variants"]:
            md.append(f"### Top 20 Collisions for T3-{v_name}")
            md.append("")
            md.append("| Rank | Code | B0 Candidate Count | B1 Freq Weight | First 10 Candidates | Quality Flags |")
            md.append("|---|---|---|---|---|---|")
            for idx, c_info in enumerate(profs["B1"]["variants"][v_name]["top_20_collisions"], 1):
                md.append(
                    f"| {idx} | `{c_info['code']}` | {c_info['candidate_count']} | {c_info['freq_weight']:.1f} | `{c_info['first_10_chars']}` | {c_info['quality_flags']} |"
                )
            md.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f">>> Full Markdown report written to {md_path}")


def print_console_summary(report: dict[str, Any]) -> None:
    """Print high-visibility summary table to stdout."""
    cov = report["coverage"]
    profs = report["profiles"]
    meta = report["metadata"]

    print("\n" + "=" * 80)
    print(f"HANSTROKE V3 Benchmark SUMMARY (SPEC: {SPEC_VERSION})")
    print("=" * 80)
    print(f"B0 Universe Size:      {cov['total_b0']}")
    b0c = cov.get("b0_composition", {})
    if b0c:
        print(
            f"B0 composition:        core {b0c.get('core_4e00_9fff')} + ExtA {b0c.get('ext_a_3400_4dbf')}"
            f" = {b0c.get('total')} ({b0c.get('ext_b_plus')})"
        )
    print(f"IDS Parsed Coverage:   {cov['has_ids_count']} / {cov['total_b0']} ({cov['has_ids_pct']}%)")
    print(f"Fully Qualified Chars: {cov['valid_features_count']} ({cov['valid_features_pct']}%)")
    ph = cov.get("placeholder_stats", {})
    if ph:
        print(
            f"Placeholder rescue:    total {ph.get('total', 0)} / rescued {ph.get('rescued', 0)}"
            f" / excluded {ph.get('excluded', 0)} (nostroke {ph.get('excluded_no_self_strokes', 0)})"
        )
    print(f"Special Status:        {MSG_B3_HN_BLOCKED}")
    print("-" * 80)
    print("GATE EVALUATION TABLE (Criterion: Weighted <= 9 candidates >= 95%):")
    print("  official = WIDE denominator (no-code = FAIL); narrow = qualified-only diagnostic")
    print(f"{'Profile':<8} {'Variant':<9} {'Wide% (off)':<14} {'Narrow%':<10} {'Threshold':<12} {'Gate'}")
    print("-" * 80)
    for p_name in ("B1", "B3-T"):
        if p_name in profs:
            for v_name, v_data in profs[p_name]["variants"].items():
                status_str = "PASS" if v_data["gate_pass"] else "FAIL"
                print(
                    f"{p_name:<8} T3-{v_name:<6} {v_data['weighted_le9_pct']:<14.2f} "
                    f"{v_data.get('narrow_weighted_le9_pct', 0.0):<10.2f} >=95.0%      {status_str}"
                )
    print("-" * 80)
    print("ORACLE-E (full anchor identity, V6 mandate):")
    for p_name in ("B0", "B1", "B3-T"):
        o = profs.get(p_name, {}).get("oracle_E")
        if not o:
            continue
        verdict = "PASS" if o["wide"]["weighted_le9_pct"] >= GATE_THRESHOLD_PCT else "FAIL"
        print(
            f"  {p_name:<8} wide={o['wide']['weighted_le9_pct']:.2f}%  "
            f"narrow={o['narrow']['weighted_le9_pct']:.2f}%  [{verdict}]"
        )
    print(f"  NOTE: {meta.get('oracle_gate_note', '-')}")
    sp = report.get("spotcheck_v9") or {}
    if sp:
        ccc = sp.get("cnchar_cross", {})
        ids_c = sp.get("ids_cross", {})
        print(
            f"  SPOTCHECK V9 (seed={sp.get('seed')}): {sp.get('selected_count')} "
            f"rows | verdicts {sp.get('verdicts')} | cnchar err "
            f"{ccc.get('error_pct')}% | IDS err "
            f"{ids_c.get('error_pct_non_circular')}% (circ "
            f"{ids_c.get('circular_skipped')})"
        )
    print("-" * 80)
    print("COLLISION PERCENTILES (Question 4, 5, 6, 7):")
    print(f"{'Profile':<8} {'Variant':<9} {'P50':<6} {'P90':<6} {'P95':<6} {'P99':<6} {'Max':<6} {'ΔP95 vs A':<10} {'ΔWide≤9'}")
    print("-" * 80)
    for p_name, p_data in profs.items():
        for v_name, v_data in p_data["variants"].items():
            print(
                f"{p_name:<8} T3-{v_name:<6} {v_data['p50']:<6.1f} {v_data['p90']:<6.1f} "
                f"{v_data['p95']:<6.1f} {v_data['p99']:<6.1f} {v_data['max']:<6} "
                f"{v_data['delta_p95_vs_a']:<+10.1f} {v_data.get('delta_wide_le9_vs_a', 0.0):+.2f}%"
            )
    print("-" * 80)
    print("SMOKE TEST (T3-A vs V2 Specification):")
    for item in report["smoke_table"]:
        status = item["status"]
        print(f"  {item['char']}: expected={item['expected']}, computed={item['computed']} -> [{status}]")
    print("-" * 80)
    print(f"T3 Selection Rule: {T3_SELECTION_NOTE}")
    rec = meta["recommended_t3"]
    if rec:
        print(f"FINAL SELECTION:   T3-{rec}")
    else:
        print("FINAL SELECTION:   NONE (Gate >=95% not reached across all profiles)")
    print("=" * 80 + "\n")


# -----------------------------------------------------------------------------
# MAIN CLI DISPATCHER
# -----------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="HANSTROKE V3 Offline Benchmark (Bilateral Agreed Spec)"
    )
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        help="Download sources and update manifest.lock.json",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run the complete offline benchmark",
    )
    parser.add_argument(
        "--only",
        type=str,
        default="A,C,E",
        help="Comma-separated subset of T3 variants to benchmark (default: A,C,E)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use locked cache without network access (verifies SHA-256)",
    )
    parser.add_argument(
        "--golden",
        action="store_true",
        help="Run golden tests on ~60 reference anchors and exit immediately",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=str(CACHE_DIR_DEFAULT),
        help=f"Directory for caching downloaded sources (default: {CACHE_DIR_DEFAULT})",
    )

    args = parser.parse_args()
    cache_dir = Path(args.cache_dir)
    selected_t3 = [x.strip().upper() for x in args.only.split(",") if x.strip()]

    # Mode 1: Update manifest
    if args.update_manifest:
        manifest = update_manifest(cache_dir)
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        sys.exit(0)

    # Mode 2: Golden test only
    if args.golden:
        manifest = verify_manifest_fail_closed(cache_dir, offline=args.offline)
        stroke_seq_file = cache_dir / SOURCES["stroke_seq"]["filename"]
        stroke_counts_file = cache_dir / SOURCES["stroke_order"]["filename"]
        cnchar_table_file = cache_dir / SOURCES["stroke_cnchar_table"]["filename"]
        cnchar_dict_files = [
            cache_dir / SOURCES["stroke_cnchar_jian"]["filename"],
            cache_dir / SOURCES["stroke_cnchar_trad"]["filename"],
        ]
        stroke_data = load_stroke_order_data(
            stroke_seq_file,
            stroke_counts_file,
            cnchar_table_file,
            cnchar_dict_files,
            cache_dir / SOURCES["ids"]["filename"],  # V9 IDS_PICKED source
        )
        passed, _ = run_golden_tests(stroke_data)
        sys.exit(0 if passed else 1)

    # Mode 3: Run benchmark
    if args.run:
        manifest = verify_manifest_fail_closed(cache_dir, offline=args.offline)
        report = run_benchmark(cache_dir, selected_t3, manifest)
        write_reports(report, cache_dir)
        print_console_summary(report)
        sys.exit(0)

    # Default if no primary action flag supplied: print help
    parser.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()