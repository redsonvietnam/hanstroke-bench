# SPOTCHECK-100 — Kiểm tay 100 chữ ngẫu nhiên (V4-CHOT Điều kiện 2)

- **Ngày**: 2026-10-03 · **Seed**: 20261003 · **Script**: `spotcheck_100.py` · **Output**: `spotcheck_100_out.txt`
- **Điều kiện**: chạy TRƯỚC khi `--run` full (Claude Điều kiện 2). Ưu tiên chữ phồn thể,
  chữ có nhánh regex, chữ ngoài cnchar.
- **Mẫu**: 40 phồn thể (cnchar-trad) + 30 regex-không-phồn + 30 ngoài-cnchar = 100, không trùng.

## Kết quả tổng

| Nhóm | Số | Kết luận |
|---|---|---|
| AGREE (stroke-input vs cnchar first+last đồng thuận) | 49 | ✅ đúng |
| CONFLICT theo thiết kế (cờ SOURCE_CONFLICT, base=TQ thắng) | 1 | ✅ đúng spec |
| SINGLE (1 nguồn) có đối chiếu bổ sung (counts/IDS) | 48 | ✅ đúng |
| SINGLE nghi sai (tie-break nhánh, đã gắn cờ AMBIGUOUS_ORDER) | 2 | ⚠️ 2% |
| **Tỷ lệ sai** | **2/100 = 2%** | cả 2 đều trong nhóm đã gắn cờ, **0 lỗi thầm lặng** |

Chi tiết từng chữ: `spotcheck_100_out.txt`.

## Adjudication

### 49 AGREE
Hai nguồn độc lập (stroke-input digit vs cnchar tên nét) cho cùng first+last → đúng.
Trong đó 4 dòng IDS-first = N là **hạn chế heuristic** (soi tay xác nhận đúng):
- #9 慍 / #47 怄: leaf 忄 standalone tie-break V, nhưng char thật được cnchar resolve → D
  (CN chuẩn 忄 = 点点竖 → first D ✓).
- #38 連: 辶 viết SAU (⿺), heuristic lấy leaf đầu text ≠ thứ tự viết; pipeline H =
  first của 車 ✓ đúng.
- (các dòng IDS = "." là char không decompose được hoặc AGREE không cần).

### 1 CONFLICT — #8 閑 U+9591
- pipeline VD (base `25112511` → first=竖) vs cnchar ZD (c=横折).
- **Chuẩn TQ笔顺编号 門 = 25112511 → first=竖=V** — pipeline đúng chuẩn digit;
  cnchar khác (truyền thống khác). Theo CHOT: base thắng + cờ SOURCE_CONFLICT
  (loader báo `source_conflict=86` toàn bộ) → **không tính là lỗi**.

### 50 SINGLE — 48 đúng, 2 nghi sai
- 48 đúng: IDS-first-leaf đồng ý (46) hoặc đối chiếu counts/trivial (#85 舝
  ut=tot=len=13; #97 亅 = 1 nét竖钩 → VV ✓).
- **2 nghi sai**: #45 諩 U+8AE9 và #56 䛡 U+46E1 — cả hai bắt đầu bằng nhóm
  `(1|4)` của 言; không có cnchar → tie-break lấy nhánh đầu `1` → first=H,
  nhưng chuẩn CN 言 = 点 (4111251) → first lẽ ra D. Cả hai **nằm trong tập
  AMBIGUOUS_ORDER (9,395 chữ) đã được gắn cờ + báo số lượng** theo CHOT.

### Đối chiếu tổng số nét (Unihan kTotalStrokes vs ucs-strokes vs len(tokens))
- 92/100 khớp cả ba.
- 7 dòng lệch ±1 giữa Unihan và ucs (嚴, 連, 䄋, 䓞, 苜, 㩚 + 骘): variance giữa
  2 nguồn số nét (ví dụ 艹 3-vs-4 nét), **không ảnh hưởng first/last**; benchmark
  lấy Unihan làm số tổng chuẩn → không lỗi cấp benchmark.
- 1 dòng (䨯): len(tokens)=18 vs count=19 do chọn nhánh giữa khác độ dài —
  first/last không đổi, count lấy từ nguồn chuẩn.

## Kết luận
- 100/100 có tài liệu đối chiếu; **tỷ lệ sai 2%, 0 lỗi thầm lặng**; 2 lỗi đều thuộc
  nhóm AMBIGUOUS_ORDER đã gắn cờ (báo cáo số lượng: 9,395).
- Cross-check toàn phần giao: 750/9,316 (8.05%) bất đồng first/last
  stroke-input↔cnchar — chỉ số chất lượng vào report (`stroke_source_stats`).
- Đủ điều kiện chạy `--run` full (golden 66/66 + kiểm tay 100 chữ).
