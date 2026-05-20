# Luật suy diễn quan hệ ẩn

## Tổng quan

Tài liệu mô tả các luật suy diễn dùng để phát hiện **quan hệ ẩn** trên đồ thị tri thức doanh nghiệp niêm yết Việt Nam. Mỗi luật dựa trên ngưỡng pháp lý về công bố sở hữu và kiểm soát.

## Ngưỡng pháp lý

| Ngưỡng | Tỷ lệ | Căn cứ pháp lý | Ý nghĩa |
|--------|-------|-----------------|---------|
| Cổ đông lớn | ≥ 5% | [TT 96/2020/TT-BTC](https://thuvienphapluat.vn/van-ban/Chung-khoan/Thong-tu-96-2020-TT-BTC-cong-bo-thong-tin-hoat-dong-tren-thi-truong-chung-khoan-457417.aspx) | Phải công bố cổ đông lớn |
| Chủ sở hữu hưởng lợi (CSHL) | ≥ 25% | [NĐ 168/2025/NĐ-CP](https://thuvienphapluat.vn/van-ban/Doanh-nghiep/Nghi-dinh-168-2025-ND-CP-huong-dan-Luat-Doanh-nghiep-2025-558001.aspx), [Luật Doanh nghiệp 2025](https://thuvienphapluat.vn/van-ban/Doanh-nghiep/Luat-Doanh-nghiep-2025-556998.aspx) | Xác định CSHL |
| Kiểm soát tuyệt đối | ≥ 50% | [Luật Chứng khoán 2019](https://thuvienphapluat.vn/van-ban/Chung-khoan/Luat-Chung-khoan-2019-431476.aspx) | Tỷ lệ kiểm soát tuyệt đối |

## Phân loại mức ảnh hưởng

| % sở hữu gián tiếp / gộp | `influence_level` | Nhãn cạnh Neo4j |
|--------------------------|-------------------|-----------------|
| &lt; 5% | NONE | Không tạo cạnh |
| 5% ≤ x &lt; 25% | LOW | `CÓ_LỢI_ÍCH_GIÁN_TIẾP` |
| 25% ≤ x &lt; 50% | MEDIUM | `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI` |
| ≥ 50% | HIGH | `KIỂM_SOÁT_GIÁN_TIẾP` |

Catalog API và UI: `backend/app/rule_catalog.py` (`R01`–`R04`). Mã luật trên cạnh: `r.inferred_from`.

**Tên quan hệ Neo4j dùng Unicode tiếng Việt** (vd. `LÀ_CỔ_ĐÔNG_CỦA`, `KIỂM_SOÁT_GIA_ĐÌNH`) — không dùng slug ASCII như `KIEM_SOAT_GIA_DINH`.

| `inferred_from` | Tên luật (UI) | Loại cạnh Neo4j được tạo |
|-----------------|--------------|-------------------------|
| R01 | Luật 1 | `KIỂM_SOÁT_GIA_ĐÌNH` |
| R02 | Luật 2 | `SỞ_HỮU_GIÁN_TIẾP` |
| R03 | Luật 3 | `CÓ_LỢI_ÍCH_GIÁN_TIẾP` (LOW), `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI` (MEDIUM), `KIỂM_SOÁT_GIÁN_TIẾP` (HIGH) |
| R04 | Luật 4 | `CÙNG_CỔ_ĐÔNG_LỚN` (công ty ↔ công ty) |

**R02 và R03:** R02 yêu cầu `(a)-[:LÀ_CỔ_ĐÔNG_CỦA]->(b)` và liên kết công ty con tới `c`; luôn tạo `SỞ_HỮU_GIÁN_TIẾP`. R03 cho phép hop đầu `r1` rộng hơn và chọn một trong ba loại cạnh theo dải %. Cả hai bỏ qua nếu % gộp/gián tiếp &lt; 5%.

**Mã cũ:** `R07` → `R03`, `R12` → `R04` qua `migrate_legacy_inferred_rule_ids()` khi chạy inference / khởi động API.

---

## Luật R01: Gộp sở hữu vợ chồng

### Mô tả

Khi vợ chồng (A và B) cùng là cổ đông một công ty C, hệ thống cộng tỷ lệ sở hữu. Giúp nhận diện kiểm soát gia đình khi từng người dưới ngưỡng công bố nhưng tổng gộp đáng kể.

### Logic

```
(A) --[VỢ_CHỒNG]-- (B)
(A) --[LÀ_CỔ_ĐÔNG_CỦA: x%]--> (C)
(B) --[LÀ_CỔ_ĐÔNG_CỦA: y%]--> (C)
=> (A) --[KIỂM_SOÁT_GIA_ĐÌNH: (x+y)%]--> (C)
```

### Căn cứ pháp lý

- **Nghị định 168/2025/NĐ-CP** Điều 6: xác định CSHL gồm sở hữu của vợ/chồng.
- **TT 96/2020/TT-BTC**: gộp sở hữu vợ chồng khi công bố.

### Thuộc tính trên cạnh tạo mới

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

### Ví dụ

Ông Đào Mạnh Khang (P_100) nắm 20% ABB, vợ (P_12345) nắm 15,5% ABB. Kiểm soát gia đình gộp = 35,5% (`MEDIUM`, trên ngưỡng CSHL).

### Cypher tương đương

**Bước 1 — Khám phá** (`run_r01_spousal_aggregation`):

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

**Bước 2 — Tạo cạnh** (Python: `combined_pct = (own_a + own_b) * 100`, bỏ qua nếu &lt; 5%):

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

`$influence` = `LOW` | `MEDIUM` | `HIGH` theo `combined_pct` (ngưỡng 5 / 25 / 50). `ownership` trên `LÀ_CỔ_ĐÔNG_CỦA` lưu **phân số** (0,15 = 15%).

---

## Luật R02: Sở hữu gián tiếp qua công ty con

### Mô tả

Tính sở hữu gián tiếp khi A nắm B, B (hoặc quan hệ công ty con) nắm C. Tỷ lệ gián tiếp = tích hai tỷ lệ.

### Logic

```
(A) --[LÀ_CỔ_ĐÔNG_CỦA: x]--> (B)
(B) --[CÓ_CÔNG_TY_CON: y]--> (C)   (hoặc chiều LÀ_CÔNG_TY_CON_CỦA)
=> (A) --[SỞ_HỮU_GIÁN_TIẾP: (x*y)%]--> (C)
```

### Căn cứ pháp lý

- **Luật Chứng khoán 2019** Điều 4: định nghĩa sở hữu gián tiếp khi công bố.
- **TT 96/2020/TT-BTC**: công bố sở hữu gián tiếp qua công ty con.

### Thuộc tính trên cạnh tạo mới

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

### Ví dụ

FPT (C_FPT) nắm 30% FPT Trading; FPT Trading nắm 51% công ty con bán lẻ. Sở hữu gián tiếp FPT = 30% × 51% = 15,3% (`LOW`, trên ngưỡng 5%).

### Cypher tương đương

**Bước 1 — Khám phá** (hai hướng `CÓ_CÔNG_TY_CON` / `LÀ_CÔNG_TY_CON_CỦA`):

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

## Luật R03: Ảnh hưởng gián tiếp theo ngưỡng

### Mô tả

Luật tổng quát: đường 2 bước A → B → C (B có công ty con C), tính % gián tiếp và gán **một trong ba** loại cạnh theo ngưỡng 5 / 25 / 50. Phiên bản nâng cấp so với logic suy diễn đơn giản ban đầu.

### Logic

```
(A) --[r1: quan hệ bất kỳ, ownership x]--> (B)
(B) --[CÓ_CÔNG_TY_CON: ownership y]--> (C)

indirect_pct = x_frac * y_frac * 100   (xem run_r03_indirect_influence)

  < 5%   => BỎ QUA
  5–25%  => (A)-[:CÓ_LỢI_ÍCH_GIÁN_TIẾP]->(C)     [LOW]
  25–50% => (A)-[:ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI]->(C)  [MEDIUM]
  >= 50% => (A)-[:KIỂM_SOÁT_GIÁN_TIẾP]->(C)       [HIGH]
```

Trên UI, cả ba loại cạnh R03 hiển thị chung là **Ảnh hưởng gián tiếp** kèm mức Thấp / Trung bình / Cao (`inferred_edge_label_display_vi`).

### Căn cứ pháp lý

- **TT 96/2020/TT-BTC**: ≥ 5% phải công bố.
- **NĐ 168/2025/NĐ-CP**: ≥ 25% xét CSHL.
- **Luật Chứng khoán 2019**: ≥ 50% kiểm soát tuyệt đối.

### Thuộc tính trên cạnh tạo mới

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

### Ví dụ

Nguyễn Văn A (P_100) nắm 30% VPBank (C_VPB); VPBank nắm 51% quỹ con. Gián tiếp = 15,3%. Vì 5% ≤ 15,3% &lt; 25% → tạo `CÓ_LỢI_ÍCH_GIÁN_TIẾP` (`LOW`).

### Cypher tương đương

**Bước 1 — Khám phá** (hop đầu rộng hơn R02; loại trừ cạnh R03 đã có):

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

Nhánh khác: thay `CÓ_LỢI_ÍCH_GIÁN_TIẾP` + `LOW` bằng `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI` + `MEDIUM` (25–50%) hoặc `KIỂM_SOÁT_GIÁN_TIẾP` + `HIGH` (≥ 50%). Không dùng một `MERGE` với `type(r)` động — runtime tạo đúng một `type()` cố định mỗi bản ghi.

---

## Luật R04: Liên kết qua cùng cổ đông lớn

### Mô tả

Cùng một cá nhân (`P_*`) nắm ≥ 5% tại hai công ty niêm yết (`C_*`) → tạo `C_x -[:CÙNG_CỔ_ĐÔNG_LỚN]-> C_y` (`c.id < d.id`, hai đầu đều là công ty).

### Thuộc tính trên cạnh tạo mới

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

### Cypher tương đương

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

**Bước 2 — Tạo cạnh** (giữa hai công ty):

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

## Chạy suy diễn

### Trong Python

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
# Chạy suy diễn thủ công
curl -X POST http://localhost:5001/api/inference/run

# Liệt kê quan hệ ẩn
curl http://localhost:5001/api/inferred-relations

# Lọc theo mức ảnh hưởng
curl http://localhost:5001/api/inferred-relations?level=HIGH
```

## Ghi chú triển khai

1. **Vòng lặp WHILE:** mỗi luật lặp đến khi không còn cạnh mới, đảm bảo suy diễn đủ trên đồ thị.

2. **Xử lý theo lô:** mặc định 500 bản ghi/lượt, tránh tràn bộ nhớ trên graph lớn.

3. **Idempotent:** `MERGE` + `ON CREATE SET` — chạy lại an toàn, chỉ thêm cạnh chưa có.

4. **Ngưỡng 5%:** không tạo cạnh khi % gián tiếp/gộp dưới 5%, giảm nhiễu.
