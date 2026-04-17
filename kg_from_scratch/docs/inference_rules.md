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

| Indirect Ownership % | Influence Level | Relation Label |
|---------------------|-----------------|----------------|
| < 5% | NONE | No relation created (skipped) |
| 5% <= x < 25% | LOW | `CO_LOI_ICH_GIAN_TIEP` |
| 25% <= x < 50% | MEDIUM | `ANH_HUONG_GIAN_TIEP_TOI` |
| >= 50% | HIGH | `KIEM_SOAT_GIAN_TIEP` |

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
  "label": "KIEM_SOAT_GIA_DINH",
  "path": "P_100<=>P_12345->C_ABC"
}
```

### Example

Mr. Dao Manh Khang (P_100) owns 20% of ABB. His wife (P_12345) owns 15.5% of ABB. Combined family control = 35.5% (MEDIUM influence, above UBO threshold).

### Equivalent Cypher

```cypher
MATCH (a:Entity)-[spouse_rel]-(b:Entity)
WHERE type(spouse_rel) = 'VỢ_CHỒNG'
MATCH (a)-[r1:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
MATCH (b)-[r2:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
WHERE r1.ownership IS NOT NULL AND r2.ownership IS NOT NULL
WITH a, b, c,
     toFloat(r1.ownership) + toFloat(r2.ownership) AS combined
WHERE combined >= 0.05
MERGE (a)-[r:KIỂM_SOÁT_GIA_ĐÌNH]->(c)
SET r.inferred = true,
    r.inferred_from = 'R01',
    r.combined_ownership_pct = combined * 100,
    r.influence_level = CASE
      WHEN combined * 100 >= 50 THEN 'HIGH'
      WHEN combined * 100 >= 25 THEN 'MEDIUM'
      WHEN combined * 100 >= 5 THEN 'LOW'
    END
```

---

## Rule R02: Indirect Ownership Chain

### Description

Calculates indirect ownership when entity A owns a percentage of B, and B owns (or controls as subsidiary) entity C. The indirect ownership is the product of the two ownership percentages.

### Logic

```
(A) --[LA_CO_DONG_CUA: x%]--> (B)
(B) --[CO_CONG_TY_CON: y%]--> (C)
=> (A) --[SO_HUU_GIAN_TIEP: (x*y)%]--> (C)
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
  "label": "SO_HUU_GIAN_TIEP",
  "path": "P_100->C_XYZ->C_ABC"
}
```

### Example

FPT (C_FPT) owns 30% of FPT Trading (C_FPT_TRADE). FPT Trading owns 51% of a retail subsidiary. FPT's indirect ownership = 30% * 51% = 15.3% (LOW influence, above disclosure threshold).

### Equivalent Cypher

```cypher
MATCH (a:Entity)-[r1:LA_CO_DONG_CUA]->(b:Entity)
MATCH (b)-[r2:CO_CONG_TY_CON]->(c:Entity)
WHERE r1.ownership IS NOT NULL AND r2.ownership IS NOT NULL
WITH a, c, r1, r2,
     toFloat(r1.ownership) * toFloat(r2.ownership) AS indirect
WHERE indirect >= 0.05
MERGE (a)-[r:SO_HUU_GIAN_TIEP]->(c)
SET r.inferred = true,
    r.inferred_from = 'R02',
    r.indirect_ownership_pct = indirect * 100,
    r.r1_ownership = toFloat(r1.ownership) * 100,
    r.r2_ownership = toFloat(r2.ownership) * 100,
    r.influence_level = CASE
      WHEN indirect * 100 >= 50 THEN 'HIGH'
      WHEN indirect * 100 >= 25 THEN 'MEDIUM'
      WHEN indirect * 100 >= 5 THEN 'LOW'
    END
```

---

## Rule R07: Indirect Influence (Threshold-Based)

### Description

The most comprehensive rule. Finds any 2-hop path where A has a relation to B, and B owns C as a subsidiary. Calculates indirect ownership percentage and creates a typed influence relation based on legal thresholds. This is an upgraded version of the original simple inference logic.

### Logic

```
(A) --[r1: any relation, ownership x%]--> (B)
(B) --[CO_CONG_TY_CON: ownership y%]--> (C)

indirect_ownership = (x/100) * (y/100) * 100

Result based on indirect_ownership:
  < 5%  => SKIP (no relation)
  5-25% => (A) --[CO_LOI_ICH_GIAN_TIEP]--> (C)    [LOW]
  25-50%=> (A) --[ANH_HUONG_GIAN_TIEP_TOI]--> (C) [MEDIUM]
  >=50% => (A) --[KIEM_SOAT_GIAN_TIEP]--> (C)     [HIGH]
```

### Legal Basis

- **TT 96/2020/TT-BTC**: >= 5% requires disclosure.
- **NĐ 168/2025/NĐ-CP**: >= 25% qualifies as UBO (significant influence).
- **Luật Chứng khoán 2019**: >= 50% constitutes absolute control.

### Properties on Created Relation

```json
{
  "inferred": true,
  "inferred_from": "R07",
  "indirect_ownership_pct": 15.3,
  "influence_level": "LOW",
  "r1_ownership": 30.0,
  "r2_ownership": 51.0,
  "r1_label": "LA_CO_DONG_CUA",
  "path": "P_100->C_VPB->C_VPB_FUND",
  "label": "CO_LOI_ICH_GIAN_TIEP"
}
```

### Example

Person Nguyen Van A (P_100) is a 30% shareholder of VPBank (C_VPB). VPBank owns 51% of VPBank Fund (C_VPB_FUND) as a subsidiary. Indirect ownership = 30% * 51% = 15.3%. Since 5% <= 15.3% < 25%, relation `CO_LOI_ICH_GIAN_TIEP` (LOW) is created.

### Equivalent Cypher

```cypher
MATCH (a:Entity)-[r1]->(b:Entity)-[r2:CO_CONG_TY_CON]->(c:Entity)
WHERE a <> c
  AND type(r1) <> 'CO_CONG_TY_CON'
  AND r2.ownership IS NOT NULL AND r2.ownership > 0
WITH a, b, c, r1, r2,
     coalesce(toFloat(r1.ownership), 1.0) * toFloat(r2.ownership) AS indirect_pct
WHERE indirect_pct >= 0.05
MERGE (a)-[r]->(c)
  WHERE type(r) = CASE
    WHEN indirect_pct >= 0.50 THEN 'KIEM_SOAT_GIAN_TIEP'
    WHEN indirect_pct >= 0.25 THEN 'ANH_HUONG_GIAN_TIEP_TOI'
    ELSE 'CO_LOI_ICH_GIAN_TIEP'
  END
SET r.inferred = true,
    r.inferred_from = 'R07',
    r.indirect_ownership_pct = indirect_pct * 100,
    r.influence_level = CASE
      WHEN indirect_pct * 100 >= 50 THEN 'HIGH'
      WHEN indirect_pct * 100 >= 25 THEN 'MEDIUM'
      ELSE 'LOW'
    END,
    r.r1_ownership = coalesce(toFloat(r1.ownership), 1.0) * 100,
    r.r2_ownership = toFloat(r2.ownership) * 100,
    r.path = a.id + '->' + b.id + '->' + c.id
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
#  'R07_indirect_influence': 48, 'total': 65, 'elapsed_seconds': 3.42}
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
