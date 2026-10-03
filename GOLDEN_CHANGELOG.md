# GOLDEN_CHANGELOG — Vòng 4 CHỐT (2026-10-03)

Áp dụng theo V3-DECISION song phương (ChatGPT "ĐỒNG Ý CHỐT." + Claude V3-DECISION).
Mọi sửa đổi golden phải ghi tại đây (nguồn, bằng chứng, lý do) trước khi cập nhật
`GOLDEN_FROZEN_SHA256` trong `benchmark_v3.py`. Không sửa golden để khớp output.

Golden hiện tại: 66 anchors.
SHA-256 (json.dumps, sort_keys, separators=(",",":"), utf-8):
`bfacb120eec9e04e364ddc09109fe5af81c0b2b1c15df0b2ad0f7350c173cbaf`

## Sửa 5 anchors

### 1. 氵 U+6C35 — last: D → H
- **Nguồn**: digit 5-class + CHỐT Q2(a) 提→H.
- **Bằng chứng**: stroke-input seq `441` (last digit 1 = 横/H); chữ 氵 = 水 radical,
  nét cuối là 提, và CHỐT vòng 4 xác nhận 提 = H (khớp digit nguồn: 5-class gộp
  提 vào nhóm ngang? — thực tế digit nguồn cho `441`: 4=点 4=点 1=横).
- **Lý do**: golden cũ (last=D) dựng theo lời kể "spec V2 ghi 提→D" — CHỐT V4
  xác nhận câu đó là nhầm; adapter bảng đã đổi 提→H.

### 2. 手 U+624B — last: Z → V
- **Nguồn**: CHỐT 竖钩 = V (spec 5-class).
- **Bằng chứng**: stroke-input `3112` (last 2 = 竖/V); cnchar-jian `sjjg`
  (last g = 竖钩 → STROKE_TOKENS 竖钩=V).
- **Lý do**: golden cũ last=Z đi ngược CHỐT 竖钩=V.

### 3. 戸 U+6238 — first: D → H
- **Nguồn**:笔顺编号 chuẩn TQ 1513 + 文化庁.
- **Bằng chứng**: stroke-input `1513` (first 1 = 横/H); Unihan kTotalStrokes=4;
  ids.txt `⿱一尸` (thành phần trên = 一 → nét đầu横).
- **Lý do**: golden cũ first=D theo "点の戸" biến thể — CHỐT chọn 一の戸 (H)
  làm neo chuẩn; gắn quality_flag=VARIANT_ORDER khi benchmark xử lý
  戶/戸/户.

### 4. 疒 U+7592 — last: D → H
- **Nguồn**: CHỐT Q2(a) 提→H.
- **Bằng chứng**: stroke-input `41341` (last 1 = 横/H), nét cuối = 提.
- **Lý do**: như 氵 (golden cũ theo lời kể提→D).

### 5. 馬 U+99AC — (first,last): (V,H) → (H,D)
- **Nguồn**: đồng thuận 2 nguồn.
- **Bằng chứng**: stroke-input `(12|21)11254444` → nhánh đầu `12` → first=1=横(H),
  last=4=捺(D); cnchar-trad `jfjjfrdkkk` → j=横→H, k=点→D. Hai nguồn cùng (H,D);
  Unihan kTotalStrokes=10 khớp total.
- **Lý do**: golden cũ (V,H) không khớp nguồn nào.

## Thêm 3 anchors (63 → 66)

### 6. 戶 U+6236 — {total:4, first:P, last:H}
- **Bằng chứng**: stroke-input `3351` → first=3=撇(P), last=1=横(H);
  cnchar-trad `sscj` → first=撇(P), last=横(H); ids.txt `⿱丿尸` (丿 → P).
  3 nguồn đồng thuận.

### 7. 户 U+6237 — {total:4, first:D, last:P}
- **Bằng chứng**: stroke-input `4513` → first=4=点(D), last=3=撇(P);
  cnchar-jian `kcjs` → first=点(D), last=撇(P); ids.txt `⿱丶尸` (丶 → D).
  3 nguồn đồng thuận.
  (U+6237 KHÔNG kế thừa từ U+6238 — Claude Điều kiện bổ sung.)

### 8. 以 U+4EE5 — {total:4, first:Z, last:D}
- **Bằng chứng**: cnchar-jian `hksk` → first=竖提 → STROKE_TOKENS 竖提=Z;
  stroke-input `(5|21)434` → nhánh cnchar chọn = `5` → first=Z, last=4=D.
- **Mục đích**: neo kiểm chứng CHỐT "thêm golden riêng cho 竖提 → Z".

## Cơ chế nguồn (V4-CHOT) — sửa trong load_stroke_order_data
- stroke-input = BASE; cnchar CHỈ chọn nhánh regex (first/last) + điền chars
  thiếu, KHÔNG bao giờ ghi đè.
- Nhánh không có cnchar → nhánh đầu (tie-break cố định) + cờ AMBIGUOUS_ORDER.
- Base khác cnchar (門) hoặc nhánh không khớp → base thắng + cờ SOURCE_CONFLICT.
- Cross-check: % bất đồng first/last trên phần giao — in lúc load + vào report.

## V9-DECISION 2026-10-03: +51 golden (66 -> 117, hash moi)

- **Quyet dinh**: [V9-Q2] dong thuan ChatGPT + Claude — "them ngay 49 AGREE +
  諩/䛡 tu nguon doc lap, chi coi la regression; changelog + hash moi".
- **49 AGREE (U+52DB 勛 ... U+82E1 苡)**: spotcheck_100 (seed 20261003) —
  pipeline first/last == cnchar first/last (hai nguon doc lap dong y ca hai dau);
  total = loader baseline (khop len(toks)).
  - **Luu y Unihan kTotalStrokes**: khop 45/49; 4 chu lech variant:
    嚴 (Unihan 20 vs 19), 連 (11 vs 10), 骘 (12 vs 13), 苜 (9 vs 8) —
    giu total = loader ground truth cho regression, ghi nhan bien the.
- **2 chu con lai**: cnchar khong co 諩 U+8AE9 / 䛡 U+46E1 → IDS_PICKED:
  IDS leading leaf 諩=⿰言並, 䛡=⿰言𠯑; 言 = golden dong bang (D,H);
  nhom (1|4) o vi tri dau chon 4 → first=D; cuoi fixed → last=H.
  Golden: 諩 {total:15, D, H}, 䛡 {total:14, D, H}.
- **GOLDEN_FROZEN_SHA256 = 83d444d66bf594b095ed3a3424a86dcb2f4624c703bef91d3f885181500a569d**
  (117 anchors; verify OK; 117/117 PASS — golden_out_v9.txt).
- **ANCHOR_SPEC_SHA256 = 887b71a1e147f49adc7462f6584514afa8199f58dc7512007c6aae6ee41375b7**
  (version V9-DECISION-2026-10-03): +ids_picked_rule (R3 verified leaf,
  trailing leaf cho cuoi, validation + nguong rut luat 5%),
  +v4_gate_registered ([V9-Q1]: B1/B3-T >=95% wide <=9 ung vien, B0-core
  san >=90% unweighted wide, tran 6 ky tu, bao avg length),
  anchor_stroke_source +ids_picked.
- **IDS_PICKED (pass 4b)**: 2,829 chu resolve (743 doi that), validation
  1239/1298 = 95.45% (loi 4.55% < 5% nguong rut luat Claude);
  excluded_enclosing(⿴⿵⿻)=134, no_leaf=154, unverified=2342, conflict=89.
  De-xuat V10: mo rong loai ⿺⿹ (probe ~47% loi tren tap cnchar) — cho phep
  dong thuan 2 ben truoc vong chay cuoi.

## V11-DECISION 2026-10-03: thu hoi wrap ops ⿺⿹ trong IDS_PICKED

- **Bang chung**: probe_wrap.py — validation rule-as-applied tren tap
  cnchar ground truth, phan tach theo root op:
  OTHER ops (⿰⿱⿲⿳⿸⿶⿷...) 1199/1201 = 99.83% (err 0.17%);
  WRAP ⿺⿹ 40/97 = 41.24% (err 58.76% >> 5% revoke threshold).
- **Quyet dinh**: V11-QC dong thuan ChatGPT + Claude — Claude: "mở
  rộng ⿺⿹ chỉ cho tập leaf đã verify, validation riêng, đóng băng
  luật bằng hash rồi chạy lại L5/L6"; ChatGPT: "tỷ lệ lỗi ~47% ...
  quá lớn để chấp nhận chỉ vì R4 tổng thể 99.77%". Đo lường riêng
  cho thấy leaf da verify vẫn 58.76% err → RÚT LUẬT cho ⿺⿹.
- **Thay đổi**: IDS_EXCLUDED_OPS = {⿴,⿵,⿻,⿺,⿹} (them ⿺⿹);
  ids_picked_rule trong ANCHOR_GRAMMAR_SPEC cap nhat;
  ANCHOR_SPEC_SHA256 = 88def0d267678ccf99a605495751485782b2cad0b30
  c05ddeed8148b808d0f32.
- **Ảnh hưởng**: chu ⿺⿹ (ví dụ 连/近/廷...) khong duoc IDS resolve
  nua → quay ve tie-break base + AMBIGUOUS_ANCHOR (loud). Golden 117
  khong thay đổi (khong co golden char nao root ⿺⿹ co nhom mơ hồ).
- **Chạy lại**: golden 117/117 PASS; benchmark full -> ladder L5/L6
  cap nhat trong report.json.
