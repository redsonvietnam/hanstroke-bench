# HANSTROKE V3 Benchmark Report — CHOT-2026-10-03

- **Generated:** `2026-10-03T09:28:02.923371+00:00`
- **Execution Time:** `4.65s`
- **B3-HN: BLOCKED — chưa có nguồn tần suất Hán-Nôm có provenance; không thay bằng B1/B3-T**

## 1. Data Quality & Coverage (Questions 1, 2, 3)

- **Total B0 Universe (U+4E00..9FFF, U+3400..4DBF):** `27584`
- **B0 composition (V6 [V6-QD]):** B0-core U+4E00..9FFF = `20992` + Ext-A U+3400..4DBF = `6592` = `27584` (out of scope (V6 [V6-QD]))
- **Chars with IDS (Q1):** `27566 / 27584 (99.93%)`
- **Fully Qualified HANSTROKE Chars (Q3):** `27172 (98.51%)`
- **Anchor spec (V6 frozen):** `V9-DECISION-2026-10-03` sha256=`88def0d267678ccf99a605495751485782b2cad0b30c05ddeed8148b808d0f32`

### IDS Confidence Breakdown (Q2)

| Confidence Category | Character Count | Percentage |
|---|---|---|
| **EXACT** | 27362 | 99.2% |
| **COMPOSITE** | 196 | 0.71% |
| **INHERITED** | 8 | 0.03% |
| **MISSING** | 18 | 0.07% |

### Data Quality Flags Excluded from Candidate Generation

| Quality Flag | Count |
|---|---|
| `SELF_ANCHOR_NO_COMPONENT` | 34 |
| `MISSING_ANCHOR_STROKES` | 412 |
| `COMPOSITE_PLACEHOLDER` | 131 |
| `AMBIGUOUS_ANCHOR` | 2704 |
| `AMBIGUOUS_SECONDARY_ANCHOR` | 675 |
| `VARIANT_ORDER` | 3 |

### Anchor Stroke Table (V6 [V6-QB])

| Source | Count |
|---|---|
| `cnchar` | 9504 |
| `tq` | 12740 |
| `fill` | 0 |
| `ambiguous` | 2685 |

- **Primary-anchor source usage (qualified chars):** `ambiguous`=2704, `cnchar`=18520, `ids_picked`=403, `tq`=5545
- **Secondary-anchor source usage:** `ambiguous`=675, `cnchar`=22401, `ids_picked`=188, `tq`=2868

### Placeholder Rescue (V6 [V6-QA] = atomic + COMPOSITE_PLACEHOLDER)

- **Chars w/ placeholder in IDS:** `131`
- **Rescued (got code):** `131`
- **Excluded:** `0` (no self stroke data: `0`, other: `0`)

### Cross-check Disagreement Classification (750-set, V6 [V6-QC])

- **Total:** `750`
- **By side:** `BOTH`=14, `FIRST_ONLY`=547, `LAST_ONLY`=189
- **By anchor usage:** `primary`=79, `secondary_only`=104, `unused`=567
- **Switched to cnchar in anchor table:** `750`

## 2. Gate Evaluation (≥95% Weighted Candidates ≤ 9)

> V6 [V6-QA]: **official = wide denominator** (all profile chars; no-code = FAIL). Narrow = qualified-only diagnostic.

| Profile | T3 Variant | Wide % (official) | Narrow % (diag) | Threshold | Gate Status |
|---|---|---|---|---|---|
| B1 | **T3-A** | 13.43% | 13.96% | ≥95.0% | *FAIL* |
| B1 | **T3-C** | 63.04% | 65.49% | ≥95.0% | *FAIL* |
| B1 | **T3-E** | 4.97% | 5.17% | ≥95.0% | *FAIL* |
| B3-T | **T3-A** | 10.12% | 10.24% | ≥95.0% | *FAIL* |
| B3-T | **T3-C** | 67.29% | 68.15% | ≥95.0% | *FAIL* |
| B3-T | **T3-E** | 7.58% | 7.68% | ≥95.0% | *FAIL* |

### Oracle-E (full anchor identity — V6 mandate)

| Profile | Oracle Wide % | Oracle Narrow % | vs 95% |
|---|---|---|---|
| B0 | 98.25% | 99.74% | **PASS** |
| B1 | 96.00% | 99.73% | **PASS** |
| B3-T | 98.62% | 99.88% | **PASS** |

> **Oracle gate note (V6 rule):** ELIGIBLE: oracle-E wide B1=96.00% B3-T=98.62% >=95% — duong mo rong ma con ton tai; V4 gate cho dang ky sau song phuong chot.

## Spotcheck V9 stratified (V9-QD dong thuan)
- seed `20261004` (moi, doc lap 117 golden), rows=100
- buckets: {'S1_trad': 2567, 'S2_group': 11870, 'S4_placeholder': 125, 'S3_no_cnchar': 5457, 'S5_ext_a': 6392} -> selected {'S1_trad': 20, 'S2_group': 20, 'S4_placeholder': 20, 'S3_no_cnchar': 20, 'S5_ext_a': 20}
- verdicts: {'AGREE': 40, 'CONFLICT': 1, 'SINGLE': 52, 'IDS_CIRCULAR': 7}
- cnchar cross: 40A/1C err=2.44% | IDS cross: 0A/0D err=None% (circular skipped=7)
- Unihan count: {'match': 90, 'mismatch': 10} | single (no independent source)=52

### Entropy / Typing Diagnostics (V6 [V6-QC])

| Profile | Variant | Bits needed (wide) | Entropy wide | Perplexity wide | Top-9 codes share % | No-code weight % |
|---|---|---|---|---|---|---|
| B0 | T3-A | 14.75 | 8.89 | 474.4 | 7.93 | 1.49 |
| B0 | T3-C | 14.75 | 12.29 | 4992.9 | 1.46 | 1.49 |
| B0 | T3-E | 14.75 | 8.31 | 316.6 | 19.46 | 1.49 |
| B1 | T3-A | 13.28 | 7.62 | 196.1 | 19.98 | 3.74 |
| B1 | T3-C | 13.28 | 8.89 | 474.1 | 18.15 | 3.74 |
| B1 | T3-E | 13.28 | 5.94 | 61.4 | 47.40 | 3.74 |
| B3-T | T3-A | 12.50 | 8.54 | 372.2 | 9.81 | 1.26 |
| B3-T | T3-C | 12.50 | 11.20 | 2355.6 | 3.22 | 1.26 |
| B3-T | T3-E | 12.50 | 8.05 | 265.7 | 18.25 | 1.26 |

## 3. Collision Distribution & Improvements (Questions 4, 5, 6, 7)

| Profile | Variant | Median (P50) | P90 | P95 | P99 | Max | ΔP95 vs A | % Wide ≤9 (Q7, official) | ΔWide ≤9 vs A | % Narrow ≤9 (diag) |
|---|---|---|---|---|---|---|---|---|---|---|
| B0 | T3-A | 81.0 | 195.0 | 223.0 | 306.0 | 306 | +0.0 | 9.00% | +0.00% | 9.14% |
| B0 | T3-C | 6.0 | 22.0 | 27.0 | 43.0 | 52 | -196.0 | 65.89% | +56.89% | 66.89% |
| B0 | T3-E | 69.0 | 635.0 | 712.0 | 838.0 | 838 | +489.0 | 5.15% | -3.85% | 5.23% |
| B1 | T3-A | 75.0 | 190.0 | 223.0 | 306.0 | 306 | +0.0 | 13.43% | +0.00% | 13.96% |
| B1 | T3-C | 6.0 | 22.0 | 27.0 | 43.0 | 52 | -196.0 | 63.04% | +49.61% | 65.49% |
| B1 | T3-E | 80.0 | 635.0 | 712.0 | 838.0 | 838 | +489.0 | 4.97% | -8.46% | 5.17% |
| B3-T | T3-A | 69.0 | 173.0 | 206.0 | 271.2 | 306 | +0.0 | 10.12% | +0.00% | 10.24% |
| B3-T | T3-C | 5.0 | 23.0 | 29.0 | 43.0 | 52 | -177.0 | 67.29% | +57.17% | 68.15% |
| B3-T | T3-E | 57.0 | 507.0 | 635.0 | 838.0 | 838 | +429.0 | 7.58% | -2.54% | 7.68% |

## 4. Smoke Test Comparison (T3-A vs V2 Spec)

| Character | Expected Code | Computed Code | Status | Total Strokes | Primary Anchor |
|---|---|---|---|---|---|
| `你` | `52c` | `52c` | PASS | 7 | `亻` |
| `明` | `426` | `426` | PASS | 8 | `日` |
| `好` | `32l` | `32l` | PASS | 6 | `女` |
| `河` | `52j` | `52g` | **DIFF** | 8 | `氵` |
| `书` | `z1o` | `z1o` | PASS | 4 | `书` |
| `马` | `z1l` | `z1l` | PASS | 3 | `马` |
| `乃` | `z1f` | `MISSING` | **DIFF** | None | `None` |
| `鼠` | `z1f` | `z1f` | PASS | 13 | `鼠` |
| `乘` | `59e` | `59e` | PASS | 10 | `禾` |
| `龜` | `z1e` | `z1b` | **DIFF** | 16 | `龜` |
| `鬱` | `e34` | `o34` | **DIFF** | 29 | `木` |

## 5. T3 Selection Recommendation

> **Rule:** Chọn T3 đơn giản nhất đạt gate, thứ tự A < C < E; nếu chỉ E đạt → ghi nhận HANSTROKE là hệ dựa trên thành phần

**RECOMMENDED VARIANT: NONE (Gate failed across both target profiles)**

## 6. Top 20 Collision Classes (Profile B1)

### Top 20 Collisions for T3-A

| Rank | Code | B0 Candidate Count | B1 Freq Weight | First 10 Candidates | Quality Flags |
|---|---|---|---|---|---|
| 1 | `821` | 306 | 949061.0 | `埝埞域埠埡埢埣埤埥埦` | EXACT |
| 2 | `921` | 279 | 501658.0 | `嘏堖堗堘堙堚堛堜堞堟` | EXACT |
| 3 | `421` | 252 | 3126707.0 | `圻圽圿址坁坂坃坄坅坆` | EXACT |
| 4 | `521` | 245 | 813348.0 | `噽坡坢坤坥坦坧坨坩坪` | EXACT |
| 5 | `621` | 239 | 968673.0 | `喆垌垍垎垏垑垓垖垗垘` | EXACT |
| 6 | `826` | 223 | 229098.0 | `唩唪唫唬唭唯唰唱唲唳` | EXACT |
| 7 | `82g` | 221 | 552574.0 | `亸凄凅准凇凈凉凊凋凌` | EXACT |
| 8 | `a21` | 216 | 142161.0 | `塲塴塶塷塸塼塽塿墁墂` | EXACT |
| 9 | `92g` | 207 | 329918.0 | `减凐凑淵渘渙渚減渜渝` | EXACT |
| 10 | `721` | 206 | 870841.0 | `嚭垶垷垸垺垻垾垿埁埂` | EXACT |
| 11 | `021` | 206 | 162970.0 | `堽塉塊塌塎塏塐塒塓塕` | EXACT |
| 12 | `926` | 195 | 184114.0 | `啣啺啼啽啾啿喀喁喂喃` | EXACT |
| 13 | `924` | 190 | 95357.0 | `朅棩椯椱椲椳椴椵椶椷` | EXACT |
| 14 | `824` | 189 | 130624.0 | `棅棆棇棈棉棋棌棍棎棏` | EXACT |
| 15 | `426` | 186 | 1088878.0 | `吘吙吚吜吟吠吡吣吤吥` | EXACT |
| 16 | `82b` | 185 | 50782.0 | `勝敫朇朜朠濌燄皗皘脹` | EXACT |
| 17 | `526` | 180 | 398931.0 | `呝呞呟呠呡呢呣呤呥呦` | EXACT |
| 18 | `42g` | 176 | 1282946.0 | `冰冱冲决冴啟攱敦敨敩` | EXACT |
| 19 | `b21` | 173 | 190071.0 | `囍墀墝增墠墡墢墣墤墥` | EXACT |
| 20 | `52g` | 170 | 1281023.0 | `况冶冷冸冹冺冻沫沬沭` | EXACT |

### Top 20 Collisions for T3-C

| Rank | Code | B0 Candidate Count | B1 Freq Weight | First 10 Candidates | Quality Flags |
|---|---|---|---|---|---|
| 1 | `a21e` | 52 | 52.0 | `摐摖摠摿榖歎瑴瑽璁璡` | EXACT |
| 2 | `z1e~` | 46 | 4710759.0 | `久乐乑乗人兆兎入八匓` | EXACT |
| 3 | `z14~` | 46 | 4439260.0 | `丈不专东其埓夀寸專惠` | EXACT |
| 4 | `8214` | 46 | 60551.0 | `域埬堎戫捷捺掁掑掕掚` | EXACT |
| 5 | `421e` | 45 | 746256.0 | `坂坄坆坎扳扵扷扻抅抓` | EXACT |
| 6 | `9214` | 43 | 6381.0 | `堜堞堧堿揀揍揲揳揻揼` | EXACT |
| 7 | `434j` | 42 | 407926.0 | `忑态怷怸恐惎惑感慐慗` | EXACT |
| 8 | `a24e` | 42 | 2306.0 | `樅樢樧樬橡殦豵驄鳷鳺` | EXACT |
| 9 | `42ge` | 41 | 875924.0 | `啟敦敨敩数敵敾次歆歊` | EXACT |
| 10 | `424e` | 40 | 229544.0 | `敇敐救敕杴杸松板构枖` | EXACT |
| 11 | `921e` | 39 | 83581.0 | `堘堠堢堫堸塅塠揔換揪` | EXACT |
| 12 | `9244` | 38 | 790.0 | `椷楔楝楪楱楲楳殜豮頍` | EXACT |
| 13 | `a2be` | 38 | 63.0 | `鏓鏦鏫鏭鐌鴅鴝鴭鴰鴲` | EXACT |
| 14 | `a2ee` | 38 | 22.0 | `穄鰶鱌鳰鴁鴒鴔鴙鴟鴩` | EXACT |
| 15 | `4214` | 37 | 352560.0 | `坏坛戩戬扰扶找技抎抔` | EXACT |
| 16 | `z16~` | 35 | 1958388.0 | `且业丬临円冉凸凹卐口` | EXACT |
| 17 | `621b` | 34 | 219785.0 | `垍垎垖垢垥垧括拰拴拾` | EXACT |
| 18 | `82g4` | 33 | 27950.0 | `凇凌凍涱涷涿淇淋淞淢` | EXACT |
| 19 | `021e` | 33 | 9943.0 | `塊塖塡塢塮塳彀搇搝搩` | EXACT |
| 20 | `4264` | 32 | 354041.0 | `吠吥吰吱呋呍呔咓战戙` | EXACT |

### Top 20 Collisions for T3-E

| Rank | Code | B0 Candidate Count | B1 Freq Weight | First 10 Candidates | Quality Flags |
|---|---|---|---|---|---|
| 1 | `42v` | 838 | 8896333.0 | `兓冰冱冲决冴刱制剙勵` | EXACT |
| 2 | `43v` | 712 | 9096303.0 | `丙乏交亥产亲企众会伞` | EXACT |
| 3 | `52v` | 651 | 3364351.0 | `俎况冶冷冸冹冺冻匏噽` | EXACT |
| 4 | `92v` | 635 | 745332.0 | `减凐凑勰匘嘏壻對帽帿` | EXACT |
| 5 | `82v` | 571 | 2142387.0 | `亸凄凅准凇凈凉凊凋凌` | EXACT |
| 6 | `62v` | 507 | 3845080.0 | `兟冼冽冾冿净務協喆嗠` | EXACT |
| 7 | `a2v` | 506 | 104691.0 | `凗叇幑幒幓幔幖幗幘幛` | EXACT |
| 8 | `22v` | 502 | 5192399.0 | `从倝凯凱切刈刉刊刋刌` | EXACT |
| 9 | `72v` | 446 | 1862884.0 | `乿兢凁凂凃啎嚭孫孭孵` | EXACT |
| 10 | `33v` | 435 | 8333245.0 | `主举互亓五些亣仚仝仺` | EXACT |
| 11 | `53v` | 414 | 4763465.0 | `両丢並丵买亘亚亨亩亶` | EXACT |
| 12 | `z1v` | 410 | 32744082.0 | `一七丈不与丏丐丑专且` | EXACT |
| 13 | `63v` | 360 | 3031679.0 | `两享京侴俞兖兪兹兺养` | EXACT |
| 14 | `02v` | 334 | 321792.0 | `亁冁凒凓凔凕博叆囅嬲` | EXACT |
| 15 | `32v` | 296 | 11405820.0 | `乾冮冯刼剏剱劒劔加勱` | EXACT |
| 16 | `73v` | 272 | 2205138.0 | `丽亟亭亮亯亰亱倉兗兠` | EXACT |
| 17 | `b2v` | 244 | 213588.0 | `凘嚲囍壿奲幜幝幞幟幠` | EXACT |
| 18 | `83v` | 240 | 1024281.0 | `亳冡冢冣冤冥冦冧叢嗧` | EXACT |
| 19 | `23v` | 172 | 7111702.0 | `万三下丌乇么乊乔乬乽` | EXACT |
| 20 | `c2v` | 161 | 34706.0 | `凙凚凛凜幧幨幪幯彇彊` | EXACT |
