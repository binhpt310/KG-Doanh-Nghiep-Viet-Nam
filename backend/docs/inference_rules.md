# Hidden Relations Inference Rules

## Overview

This document describes the inference rules used to discover hidden relationships in the Knowledge Graph of Vietnamese listed companies. Each rule is based on Vietnamese legal thresholds for ownership disclosure and control.

## Legal Thresholds

| Threshold | Percentage | Legal Basis | Meaning |
|-----------|-----------|-------------|---------|
| Large Shareholder | >= 5% | [TT 96/2020/TT-BTC](https://thuvienphapluat.vn/van-ban/Chung-khoan/Thong-tu-96-2020-TT-BTC-cong-bo-thong-tin-hoat-dong-tren-thi-truong-chung-khoan-457417.aspx) | Must disclose as large shareholder |
| Ultimate Beneficial Owner (UBO) | >= 25% | [NĐ 168/2025/NĐ-CP](https://thuvienphapluat.vn/van-ban/Doanh-nghiep/Nghi-dinh-168-2025-ND-CP-huong-dan-Luat-Doanh-nghiep-2025-558001.aspx), [Luật Doanh nghiệp 2025](https://thuvienphapluat.vn/van-ban/Doanh-nghiep/Luat-Doanh-nghiep-2025-556998.aspx) | Classified as UBO |
| Absolute Control | >= 50% | [Luật Chứng khoán 2019](https://thuvienphapluat.vn/van-ban/Chung-khoan/Luat-Chung-khoan-2019-431476.aspx) | Absolute controlling stake |

## Influence Level Classification

| Indirect Ownership % | Influence Level | Relation Label (Neo4j) |
|---------------------|-----------------|---------------------------|
| < 5% | NONE | No relation created (skipped) |
| 5% <= x < 25% | LOW | `CÓ_LỢI_ÍCH_GIÁN_TIẾP` |
| 25% <= x < 50% | MEDIUM | `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI` |
| >= 50% | HIGH | `KIỂM_SOÁT_GIÁN_TIẾP` |

Catalog API và UI: `backend/app/rule_catalog.py` (`R01`–`R04`). Mã luật trên cạnh: `r.inferred_from`.

**Neo4j relationship `type()` names use Vietnamese Unicode** (e.g. `LÀ_CỔ_ĐÔNG_CỦA`, `KIỂM_SOÁT_GIA_ĐÌNH`) — not ASCII slugs like `KIEM_SOAT_GIA_DINH`.

| `inferred_from` | UI law name | Neo4j edge type(s) created |
|-----------------|-------------|----------------------------|
| R01 | Luật 1 | `KIỂM_SOÁT_GIA_ĐÌNH` |
| R02 | Luật 2 | `SỞ_HỮU_GIÁN_TIẾP` |
| R03 | Luật 3 | `CÓ_LỢI_ÍCH_GIÁN_TIẾP` (LOW), `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI` (MEDIUM), `KIỂM_SOÁT_GIÁN_TIẾP` (HIGH) |
| R04 | Luật 4 | `CÙNG_CỔ_ĐÔNG_LỚN` (company ↔ company) |

**R02 vs R03:** R02 requires `(a)-[:LÀ_CỔ_ĐÔNG_CỦA]->(b)` and subsidiary link to `c`; always `SỞ_HỮU_GIÁN_TIẾP`. R03 allows a broader first hop `r1` and picks one of three R03 edge types by indirect % bands. Both skip when indirect/combined % &lt; 5%.

**Legacy IDs:** `R07` → `R03`, `R12` → `R04` via `migrate_legacy_inferred_rule_ids()` at inference/API startup.

---

## Rule R01: Spousal Ownership Aggregation

### Description

When a married couple (A and B) each hold ownership stakes in the same company C, their combined ownership is calculated. This is critical for identifying family-controlled entities where individual stakes may be below disclosure thresholds but combined stakes are significant.

### Logic

```
(A) --[VỢ_CHỒNG]-- (B)
(A) --[LÀ_CỔ_ĐÔNG_CỦA: x%]--> (C)
(B) --[LÀ_CỔ_ĐÔNG_CỦA: y%]--> (C)
=> (A) --[KIỂM_SOÁT_GIA_ĐÌNH: (x+y)%]--> (C)
```
(Neo4j dùng đúng kiểu quan hệ như trong `inference_rules.py`.)

### Legal Basis

- **Nghị định 168/2025/NĐ-CP** Article 6: UBO determination includes ownership held by spouse.
- **TT 96/2020/TT-BTC**: Spousal ownership must be aggregated for disclosure purposes.

### Properties on Created Relation

```json
{
  "inferred": true,
  "inferred_from": "R01",
  "combined_ownership_pct": 35.5,
  "ownership_a": 20.0,
  "ownership_b": 15.5,
  "spouse_id": "P_12345",
  "spouse_name": "Nguyen Van B",
  "influence_level": "MEDIUM",
  "label": "KIỂM_SOÁT_GIA_ĐÌNH",
  "path": "P_100<=>P_12345->C_ABC"
}
```

### Example

Mr. Dao Manh Khang (P_100) owns 20% of ABB. His wife (P_12345) owns 15.5% of ABB. Combined family control = 35.5% (MEDIUM influence, above UBO threshold).

### Equivalent Cypher

**Bước 1 — Khám phá cặp vợ chồng cùng cổ đông một DN** (`run_r01_spousal_aggregation`):

```cypher
MATCH (a:Entity)-[spouse_rel]-(b:Entity)
WHERE type(spouse_rel) = 'VỢ_CHỒNG'
MATCH (a)-[r1:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
MATCH (b)-[r2:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
WHERE r1.ownership IS NOT NULL AND r2.ownership IS NOT NULL
  AND a <> b
  AND NOT EXISTS { (a)-[:KIỂM_SOÁT_GIA_ĐÌNH]->(c) }
RETURN a.id AS A, b.id AS B, c.id AS C,
       toFloat(r1.ownership) AS own_a,
       toFloat(r2.ownership) AS own_b
LIMIT 500
```

**Bước 2 — Tạo cạnh** (Python gán `combined_pct = (own_a + own_b) * 100`, bỏ qua nếu &lt; 5%):

```cypher
MATCH (a:Entity {id: $src})
MATCH (c:Entity {id: $tgt})
MERGE (a)-[r:KIỂM_SOÁT_GIA_ĐÌNH]->(c)
ON CREATE SET r.inferred = true,
              r.inferred_from = 'R01',
              r.combined_ownership_pct = $combined_pct,
              r.ownership_a = $own_a_pct,
              r.ownership_b = $own_b_pct,
              r.spouse_id = $spouse_id,
              r.spouse_name = $spouse_name,
              r.influence_level = $influence,
              r.label = 'KIỂM_SOÁT_GIA_ĐÌNH',
              r.path = $path
```

`$influence` = `LOW` | `MEDIUM` | `HIGH` theo `combined_pct` (ngưỡng 5 / 25 / 50). `ownership` trên `LÀ_CỔ_ĐÔNG_CỦA` lưu **phân số** (0.15 = 15%).

---

## Rule R02: Indirect Ownership Chain

### Description

Calculates indirect ownership when entity A owns a percentage of B, and B owns (or controls as subsidiary) entity C. The indirect ownership is the product of the two ownership percentages.

### Logic

```
(A) --[LÀ_CỔ_ĐÔNG_CỦA: x]--> (B)
(B) --[CÓ_CÔNG_TY_CON: y]--> (C)   (or reverse LÀ_CÔNG_TY_CON_CỦA)
=> (A) --[SỞ_HỮU_GIÁN_TIẾP: (x*y)%]--> (C)
```

### Legal Basis

- **Luật Chứng khoán 2019** Article 4: Defines indirect ownership for reporting requirements.
- **TT 96/2020/TT-BTC**: Indirect ownership through subsidiaries must be disclosed.

### Properties on Created Relation

```json
{
  "inferred": true,
  "inferred_from": "R02",
  "indirect_ownership_pct": 15.3,
  "r1_ownership": 30.0,
  "r2_ownership": 51.0,
  "influence_level": "LOW",
  "label": "SỞ_HỮU_GIÁN_TIẾP",
  "path": "P_100->C_XYZ->C_ABC"
}
```

### Example

FPT (C_FPT) owns 30% of FPT Trading (C_FPT_TRADE). FPT Trading owns 51% of a retail subsidiary. FPT's indirect ownership = 30% * 51% = 15.3% (LOW influence, above disclosure threshold).

### Equivalent Cypher

**Bước 1 — Khám phá chuỗi cổ đông → công ty con** (hai hướng `CÓ_CÔNG_TY_CON` / `LÀ_CÔNG_TY_CON_CỦA`):

```cypher
CALL () {
  MATCH (a:Entity)-[r1:LÀ_CỔ_ĐÔNG_CỦA]->(b:Entity)
  MATCH (b:Entity)-[r2:CÓ_CÔNG_TY_CON]->(c:Entity)
  WHERE r2.ownership IS NOT NULL
  RETURN a, b, c, r1, r2
  UNION
  MATCH (a:Entity)-[r1:LÀ_CỔ_ĐÔNG_CỦA]->(b:Entity)
  MATCH (c:Entity)-[r2:LÀ_CÔNG_TY_CON_CỦA]->(b:Entity)
  WHERE r2.ownership IS NOT NULL
  RETURN a, b, c, r1, r2
}
WITH a, b, c, r1, r2
WHERE r1.ownership IS NOT NULL
  AND a <> c
  AND NOT EXISTS { (a)-[:SỞ_HỮU_GIÁN_TIẾP]->(c) }
  AND NOT EXISTS { (a)-[:LÀ_CỔ_ĐÔNG_CỦA]->(c) }
RETURN a.id AS A, c.id AS C,
       toFloat(r1.ownership) AS own_ab,
       toFloat(r2.ownership) AS own_bc
LIMIT 500
```

**Bước 2 — Tạo cạnh** (`indirect_pct = own_ab * own_bc * 100`, bỏ qua nếu &lt; 5%):

```cypher
MATCH (a:Entity {id: $src})
MATCH (c:Entity {id: $tgt})
MERGE (a)-[r:SỞ_HỮU_GIÁN_TIẾP]->(c)
ON CREATE SET r.inferred = true,
              r.inferred_from = 'R02',
              r.indirect_ownership_pct = $indirect_pct,
              r.r1_ownership = $r1_pct,
              r.r2_ownership = $r2_pct,
              r.influence_level = $influence,
              r.label = 'SỞ_HỮU_GIÁN_TIẾP',
              r.path = $path
```

---

## Rule R03: Indirect Influence (Threshold-Based)

### Description

The most comprehensive rule. Finds any 2-hop path where A has a relation to B, and B owns C as a subsidiary. Calculates indirect ownership percentage and creates a typed influence relation based on legal thresholds. This is an upgraded version of the original simple inference logic.

### Logic

```
(A) --[r1: any relation, ownership x]--> (B)
(B) --[CÓ_CÔNG_TY_CON: ownership y]--> (C)

indirect_pct = x_frac * y_frac * 100   (see run_r03_indirect_influence)

  < 5%   => SKIP
  5–25%  => (A)-[:CÓ_LỢI_ÍCH_GIÁN_TIẾP]->(C)     [LOW]
  25–50% => (A)-[:ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI]->(C)  [MEDIUM]
  >= 50% => (A)-[:KIỂM_SOÁT_GIÁN_TIẾP]->(C)       [HIGH]
```

On the web UI, all three R03 types display as **Ảnh hưởng gián tiếp** with level Thấp / Trung bình / Cao (`rule_catalog.inferred_edge_label_display_vi`).

### Legal Basis

- **TT 96/2020/TT-BTC**: >= 5% requires disclosure.
- **NĐ 168/2025/NĐ-CP**: >= 25% qualifies as UBO (significant influence).
- **Luật Chứng khoán 2019**: >= 50% constitutes absolute control.

### Properties on Created Relation

```json
{
  "inferred": true,
  "inferred_from": "R03",
  "indirect_ownership_pct": 15.3,
  "influence_level": "LOW",
  "r1_ownership": 30.0,
  "r2_ownership": 51.0,
  "r1_label": "LÀ_CỔ_ĐÔNG_CỦA",
  "path": "P_100->C_VPB->C_VPB_FUND",
  "label": "CÓ_LỢI_ÍCH_GIÁN_TIẾP"
}
```

### Example

Person Nguyen Van A (P_100) is a 30% shareholder of VPBank (C_VPB). VPBank owns 51% of VPBank Fund (C_VPB_FUND) as a subsidiary. Indirect ownership = 30% * 51% = 15.3%. Since 5% <= 15.3% < 25%, relation `CÓ_LỢI_ÍCH_GIÁN_TIẾP` (LOW) is created.

### Equivalent Cypher

**Bước 1 — Khám phá đường 2 bước** (hop đầu rộng hơn R02; loại trừ cạnh R03 đã có):

```cypher
CALL () {
  MATCH (a:Entity)-[r1]->(b:Entity)-[r2:CÓ_CÔNG_TY_CON]->(c:Entity)
  WHERE type(r1) <> 'CÓ_CÔNG_TY_CON'
    AND r2.ownership IS NOT NULL
    AND r2.ownership > 0
  RETURN a, b, c, r1, r2
  UNION
  MATCH (a:Entity)-[r1]->(b:Entity)<-[r2:LÀ_CÔNG_TY_CON_CỦA]-(c:Entity)
  WHERE type(r1) <> 'LÀ_CÔNG_TY_CON_CỦA'
    AND r2.ownership IS NOT NULL
    AND r2.ownership > 0
  RETURN a, b, c, r1, r2
}
WITH a, b, c, r1, r2
WHERE a <> c
  AND NOT EXISTS { (a)-[:CÓ_LỢI_ÍCH_GIÁN_TIẾP]->(c) }
  AND NOT EXISTS { (a)-[:ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI]->(c) }
  AND NOT EXISTS { (a)-[:KIỂM_SOÁT_GIÁN_TIẾP]->(c) }
  AND NOT EXISTS { (a)-[:ẢNH_HƯỞNG_GIÁN_TIẾP]->(c) }
RETURN a.id AS A, c.id AS C,
       r1.label AS r1_label,
       coalesce(toFloat(r1.ownership), 1.0) AS r1_ownership,
       toFloat(r2.ownership) AS r2_ownership
LIMIT 500
```

**Bước 2 — Tạo cạnh** (Python chọn `rel_label` theo `indirect_pct`; ví dụ nhánh LOW):

```cypher
MATCH (a:Entity {id: $src})
MATCH (c:Entity {id: $tgt})
MERGE (a)-[r:CÓ_LỢI_ÍCH_GIÁN_TIẾP]->(c)
ON CREATE SET r.inferred = true,
              r.inferred_from = 'R03',
              r.indirect_ownership_pct = $indirect_pct,
              r.influence_level = 'LOW',
              r.r1_ownership = $r1_pct,
              r.r2_ownership = $r2_pct,
              r.r1_label = $r1_label,
              r.path = $path,
              r.label = 'CÓ_LỢI_ÍCH_GIÁN_TIẾP'
```

Các nhánh khác: thay `CÓ_LỢI_ÍCH_GIÁN_TIẾP` + `LOW` bằng `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI` + `MEDIUM` (25–50%) hoặc `KIỂM_SOÁT_GIÁN_TIẾP` + `HIGH` (≥ 50%). Không dùng một `MERGE` chung với `type(r)` động — runtime tạo đúng một `type()` cố định mỗi bản ghi.

---

## Rule R04: Shared Major Shareholder

### Description

When the same person (`P_*`) holds ≥ 5% in two listed companies (`C_*`), create `C_x -[:CÙNG_CỔ_ĐÔNG_LỚN]-> C_y` (`c.id < d.id`, both endpoints are companies).

### Properties on Created Relation

```json
{
  "inferred": true,
  "inferred_from": "R04",
  "label": "CÙNG_CỔ_ĐÔNG_LỚN",
  "shared_holder_id": "P_12345",
  "ownership_c": 0.08,
  "ownership_d": 0.06
}
```

### Equivalent Cypher

**Bước 1 — Khám phá** (`run_r04_shared_major_shareholder`):

```cypher
MATCH (n:Entity)-[r1:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
MATCH (n)-[r2:LÀ_CỔ_ĐÔNG_CỦA]->(d:Entity)
WHERE c.id STARTS WITH 'C_' AND d.id STARTS WITH 'C_'
  AND c.id < d.id
  AND n.id STARTS WITH 'P_'
  AND r1.ownership IS NOT NULL AND r2.ownership IS NOT NULL
  AND toFloat(r1.ownership) >= 0.05 AND toFloat(r2.ownership) >= 0.05
  AND NOT EXISTS { (c)-[x]->(d) WHERE type(x) = 'CÙNG_CỔ_ĐÔNG_LỚN' }
RETURN c.id AS cid, d.id AS did, n.id AS nid, n.name AS nname,
       toFloat(r1.ownership) AS o1, toFloat(r2.ownership) AS o2
LIMIT 500
```

**Bước 2 — Tạo cạnh** (giữa hai công ty, không phải Person → Company):

```cypher
MATCH (c:Entity {id: $cid})
MATCH (d:Entity {id: $did})
MERGE (c)-[r:CÙNG_CỔ_ĐÔNG_LỚN]->(d)
ON CREATE SET r.inferred = true,
              r.inferred_from = 'R04',
              r.label = 'CÙNG_CỔ_ĐÔNG_LỚN',
              r.shared_holder_id = $nid,
              r.shared_holder_name = $nname,
              r.ownership_c = $o1,
              r.ownership_d = $o2
```

---

## Execution

### Programmatic Usage

```python
from inference_rules import run_all_inference_rules
from neo4j import GraphDatabase

driver = GraphDatabase.driver("neo4j://localhost:7687", auth=("neo4j", "password"))
results = run_all_inference_rules(driver, batch_size=500)
print(results)
# {'R01_spousal_aggregation': 5, 'R02_indirect_ownership': 12,
#  'R03_indirect_influence': 48, 'R04_shared_major_shareholder': 3,
#  'total': 68, 'elapsed_seconds': 3.42}
```

### REST API

```bash
# Trigger manual inference
curl -X POST http://localhost:5001/api/inference/run

# Get all inferred relations
curl http://localhost:5001/api/inferred-relations

# Filter by influence level
curl http://localhost:5001/api/inferred-relations?level=HIGH
```

## Implementation Notes

1. **WHILE True Pattern**: Each rule loops internally until no new relations are found, ensuring all possible inferences are made regardless of graph depth.

2. **Batch Processing**: Rules process records in configurable batches (default 500) to prevent memory issues on large graphs.

3. **Idempotency**: Relations are created with `MERGE` + `ON CREATE SET`, so re-running is safe and only creates new relations.

4. **Threshold Enforcement**: Relations below 5% indirect ownership are NOT created, avoiding noise from insignificant connections.
