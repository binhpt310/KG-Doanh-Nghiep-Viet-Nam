# Schema thực thể (Entity) trong Neo4j

Tài liệu tham chiếu cho node/edge trong graph sau `push_to_neo4j`. Luật suy diễn: `inference_rules.md`, catalog UI: `app/rule_catalog.py`.

## Schema các trường dữ liệu của 1 thực thể (Entity)

### Có 2 loại node trong KG hiện tại:

#### 🧑 **Person** (prefix id: `P_xxxxx`)

| Field        | Kiểu          | Mô tả                              |
|--------------|---------------|------------------------------------|
| `id`         | `string`      | ID duy nhất, ví dụ `P_8587`        |
| `name`       | `string`      | Họ tên đầy đủ, ví dụ `Trần Hùng Huy` |
| `type`       | `string`      | `"Person"`                         |
| `dateOfBirth`| `string/null` | Ngày sinh, ví dụ `"25/10/1971"`    |
| `homeTown`   | `string/null` | Quê quán, ví dụ `"Phú Yên"`        |
| `placeOfBirth`| `string/null`| Nơi sinh, ví dụ `"Tp. Hồ Chí Minh"`|
| `isForeign`  | `boolean/null`| Có phải người nước ngoài không     |

#### 🏢 **Company** (prefix id: `C_xxx` hoặc `C_INST_xxxxx`)

| Field   | Kiểu     | Mô tả                          |
|---------|----------|--------------------------------|
| `id`    | `string` | ID duy nhất, ví dụ `C_ACB`, `C_INST_7127` |
| `name`  | `string` | Tên công ty/tổ chức            |
| `type`  | `string` | `"Company"`                    |
| `props` | `object` | Hiện tại thường rỗng `{}` cho Company |

### 🔗 **Quan hệ quan sát (không suy diễn)**

Cạnh nạp từ FireAnt / preprocess. `ownership` trên cổ đông thường là **phân số** (0.05 = 5%).

| `type(r)` | Hướng điển hình | Thuộc tính thường gặp |
|-----------|-----------------|------------------------|
| `LÀ_CỔ_ĐÔNG_CỦA` | Person/Institution → Company | `shares`, `ownership` |
| `LÃNH_ĐẠO_CAO_NHẤT` | Person → Company | `label`, chức vụ (nếu có) |
| `CÓ_CÔNG_TY_CON` | Company → Company (con) | `ownership` (tỷ lệ sở hữu CT con) |
| `LÀ_CÔNG_TY_CON_CỦA` | Company (con) → Company (mẹ) | `ownership` |
| `VỢ_CHỒNG`, `CHA_MẸ`, `ANH_CHỊ`, … | Person ↔ Person | quan hệ gia đình |
| `LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO` | Person → Company | `leaderName`, `position`, `familyRelation` |

---

### 🔗 **Quan hệ ẩn (suy diễn — `inferred: true`)**

Sinh bởi `inference_rules.py` sau `push_to_neo4j`. Mọi cạnh ẩn có `inferred_from` ∈ `R01` | `R02` | `R03` | `R04` (legacy: `R07`→`R03`, `R12`→`R04`). Catalog + text UI: `app/rule_catalog.py`, `GET /api/rules`. Chi tiết Cypher: `inference_rules.md`.

| `inferred_from` | `type(r)` (Neo4j) | Tên trên UI | Thuộc tính chính trên cạnh |
|-----------------|-------------------|-------------|----------------------------|
| **R01** | `KIỂM_SOÁT_GIA_ĐÌNH` | Kiểm soát gia đình | `combined_ownership_pct`, `ownership_a`, `ownership_b`, `spouse_id`, `spouse_name`, `influence_level`, `path` |
| **R02** | `SỞ_HỮU_GIÁN_TIẾP` | Sở hữu gián tiếp | `indirect_ownership_pct`, `r1_ownership`, `r2_ownership`, `influence_level`, `path` |
| **R03** | `CÓ_LỢI_ÍCH_GIÁN_TIẾP` | Ảnh hưởng gián tiếp (Thấp) | `indirect_ownership_pct`, `influence_level` = `LOW`, `r1_label`, `r1_ownership`, `r2_ownership`, `path` |
| **R03** | `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI` | Ảnh hưởng gián tiếp (Trung bình) | cùng nhóm; `influence_level` = `MEDIUM` (25% ≤ gián tiếp &lt; 50%) |
| **R03** | `KIỂM_SOÁT_GIÁN_TIẾP` | Ảnh hưởng gián tiếp (Cao) | cùng nhóm; `influence_level` = `HIGH` (≥ 50%) |
| **R04** | `CÙNG_CỔ_ĐÔNG_LỚN` | Cùng cổ đông lớn | `shared_holder_id`, `shared_holder_name`, `ownership_c`, `ownership_d` (cạnh **Company → Company**) |

**Ghi chú:**

- **R02 vs R03:** cùng có thể đi qua chuỗi tới công ty con, nhưng R02 bắt buộc hop đầu `LÀ_CỔ_ĐÔNG_CỦA` và luôn tạo `SỞ_HỮU_GIÁN_TIẾP`; R03 hop đầu linh hoạt hơn và chọn một trong ba `type()` theo ngưỡng 5 / 25 / 50.
- Cạnh ẩn thường có `label` trùng `type(r)` và `dashes: true` trên API graph.
- Ngưỡng %: &lt; 5% không tạo cạnh; `influence_level` = `LOW` | `MEDIUM` | `HIGH` (hoặc `NONE` nếu bị loại trước khi ghi).

**Truy vấn mẫu — liệt kê quan hệ ẩn:**

```cypher
MATCH (a:Entity)-[r]->(b:Entity)
WHERE coalesce(r.inferred, false) = true
RETURN type(r) AS rel, r.inferred_from AS rule,
       a.id AS from_id, b.id AS to_id,
       r.indirect_ownership_pct AS pct,
       r.influence_level AS level
LIMIT 50
```

**Lọc theo luật:**

```cypher
MATCH (a:Entity)-[r:KIỂM_SOÁT_GIÁN_TIẾP]->(b:Entity)
WHERE r.inferred_from = 'R01'
RETURN a.name, b.name, r.combined_ownership_pct
LIMIT 20
```

