# Schema thực thể (Entity) trong Neo4j

Tài liệu tham chiếu cho node/edge trong graph sau `push_to_neo4j`. Luật suy diễn: [inference_rules.md](inference_rules.md), catalog UI: `backend/app/rule_catalog.py`.

**Tổng quan (snapshot 2026-05-21):** 2 711 công ty, 7 702 cá nhân, 10 413 node, 19 122 cạnh (119 loại `type(r)`), 280 cạnh ẩn (R01=32, R02=16, R03=232, R04=0). Số cạnh theo loại: xem bảng bên dưới.

## Schema các trường dữ liệu của 1 thực thể (Entity)

### Có 2 loại node trong KG hiện tại:

#### **Person** (tiền tố id: `P_xxxxx`)

| Field        | Kiểu          | Mô tả                              |
|--------------|---------------|------------------------------------|
| `id`         | `string`      | ID duy nhất, ví dụ `P_8587`        |
| `name`       | `string`      | Họ tên đầy đủ, ví dụ `Trần Hùng Huy` |
| `type`       | `string`      | `"Person"`                         |
| `dateOfBirth`| `string/null` | Ngày sinh, ví dụ `"25/10/1971"`    |
| `homeTown`   | `string/null` | Quê quán, ví dụ `"Phú Yên"`        |
| `placeOfBirth`| `string/null`| Nơi sinh, ví dụ `"Tp. Hồ Chí Minh"`|
| `isForeign`  | `boolean/null`| Có phải người nước ngoài không     |

#### **Company** (tiền tố id: `C_xxx` hoặc `C_INST_xxxxx`)

| Field   | Kiểu     | Mô tả                          |
|---------|----------|--------------------------------|
| `id`    | `string` | ID duy nhất, ví dụ `C_ACB`, `C_INST_7127` |
| `name`  | `string` | Tên công ty/tổ chức            |
| `type`  | `string` | `"Company"`                    |
| `symbol`| `string` | Mã chứng khoán (nếu có), ví dụ `"VCB"` |
| `props` | `object` | Các thuộc tính bổ sung: `symbol`, `exchange`, `industry`, `price` (từ FireAnt) |

### **Quan hệ quan sát (không suy diễn)**

Cạnh nạp từ FireAnt / preprocess. `ownership` trên cổ đông thường là **phân số** (0.05 = 5%).

FireAnt API endpoint `symbols/{symbol}/subsidiaries` trả về danh sách kèm trường `type` (0–4). Pipeline sau đó **phân loại** thành các cạnh riêng biệt thay vì gộp chung, giúp LLM và người dùng truy vấn chính xác.

#### Phân loại quan hệ công ty theo `type` từ FireAnt

| FireAnt `type` | Tên gốc (API) | Nhãn Neo4j | Ngưỡng sở hữu điển hình | Ý nghĩa pháp lý & nghiệp vụ |
|---|---|---|---|---|
| **0** | Subsidiary | `CÓ_CÔNG_TY_CON` / `LÀ_CÔNG_TY_CON_CỦA` | ≥ 50% | **Công ty con:** công ty mẹ nắm quyền kiểm soát tuyệt đối (≥50% vốn điều lệ hoặc quyền biểu quyết). Có quyền bổ nhiệm lãnh đạo, chi phối chính sách tài chính và hoạt động. Được hợp nhất báo cáo tài chính. (Căn cứ: Luật Doanh nghiệp, Luật Chứng khoán 2019) |
| **1** | Linked | `CÓ_CÔNG_TY_LIÊN_KẾT` | 20–50% | **Công ty liên kết:** nhà đầu tư có ảnh hưởng đáng kể (≥20% quyền biểu quyết) nhưng **không** kiểm soát. Có thể cử đại diện vào HĐQT, tham gia quyết định chính sách nhưng không chi phối tuyệt đối. Hạch toán theo phương pháp vốn chủ sở hữu. (Căn cứ: VAS 07, IAS 28) |
| **2** | Venture | `LIÊN_DOANH_VỚI` | 20–50% (đồng kiểm soát) | **Liên doanh:** hai hay nhiều bên cùng góp vốn và **cùng kiểm soát** thực thể kinh tế. Khác với công ty liên kết ở chỗ quyền kiểm soát được chia sẻ qua thỏa thuận, không bên nào đơn phương chi phối. (Căn cứ: VAS 08, IFRS 11) |
| **3** | Investment | `ĐẦU_TƯ_VÀO` | < 20% | **Đầu tư góp vốn:** khoản đầu tư thuần túy tài chính, không có ảnh hưởng đáng kể hay quyền kiểm soát. Nhà đầu tư chỉ hưởng cổ tức và lợi nhuận từ chênh lệch giá, không tham gia điều hành. Thường là cổ phiếu niêm yết nắm giữ dưới ngưỡng công bố cổ đông lớn. |
| **4** | Unknown | *(bị loại bỏ)* | 0% hoặc không xác định | **Không phân loại được hoặc ownership = 0:** dữ liệu không đủ để xác định bản chất quan hệ. Pipeline hiện tại bỏ qua hoàn toàn để tránh nhiễu. Thường là các công ty có quan hệ tín dụng/cầm cố với ngân hàng, không phải quan hệ sở hữu. |

> **Tại sao phải tách riêng?** Trước đây (phiên bản cũ) tất cả type 0–4 đều bị gộp thành `CÓ_CÔNG_TY_CON`. Điều này khiến LLM trả lời sai nghiêm trọng: ví dụ MBB được liệt kê có 40+ "công ty con" bao gồm cả CEO, HAG, REE — những công ty MBB chỉ có quan hệ tín dụng (type=4, ownership=0%). Sau khi tách, MBB còn 8 công ty con thực sự.

#### Bảng quan hệ quan sát

| `type(r)` | Hướng điển hình | Thuộc tính thường gặp | Số cạnh |
|-----------|-----------------|------------------------|---------|
| `LÀ_CỔ_ĐÔNG_CỦA` | Person/Institution → Company | `shares`, `ownership` | 4 761 |
| `LÃNH_ĐẠO_CAO_NHẤT` | Person → Company | `label` | 259 |
| `CÓ_CÔNG_TY_CON` | Company → Company | `ownership` | 746 |
| `LÀ_CÔNG_TY_CON_CỦA` | Company → Company | `ownership` | 95 |
| `CÓ_CÔNG_TY_LIÊN_KẾT` | Company → Company | `ownership` | 177 |
| `LIÊN_DOANH_VỚI` | Company → Company | `ownership` | 30 |
| `ĐẦU_TƯ_VÀO` | Company → Company | `ownership` | 179 |
| `VỢ_CHỒNG`, `CHA_MẸ`, `ANH_CHỊ`, … (56 loại) | Person ↔ Person | — | ~8 630 |
| `LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO` | Person → Company | `leaderName`, `position`, `familyRelation` | 960 |
| Các chức danh (25+ loại: `CHỦ_TỊCH_HĐQT`, `TỔNG_GIÁM_ĐỐC`, …) | Person → Company | `label` | ~3 000 |

---

### **Quan hệ ẩn (suy diễn — `inferred: true`)**

Sinh bởi `backend/inference_rules.py` sau `push_to_neo4j`. Mọi cạnh ẩn có `inferred_from` ∈ `R01` | `R02` | `R03` | `R04` (legacy: `R07`→`R03`, `R12`→`R04`). Catalog + text UI: `backend/app/rule_catalog.py`, `GET /api/rules`. Chi tiết Cypher: [inference_rules.md](inference_rules.md).

| `inferred_from` | `type(r)` (Neo4j) | Tên trên UI | Thuộc tính chính trên cạnh |
|-----------------|-------------------|-------------|----------------------------|
| **R01** | `KIỂM_SOÁT_GIA_ĐÌNH` | Kiểm soát gia đình | `combined_ownership_pct`, `ownership_a`, `ownership_b`, `spouse_id`, `spouse_name`, `influence_level`, `path` |
| **R02** | `SỞ_HỮU_GIÁN_TIẾP` | Sở hữu gián tiếp | `indirect_ownership_pct`, `r1_ownership`, `r2_ownership`, `influence_level`, `path` |
| **R03** | `CÓ_LỢI_ÍCH_GIÁN_TIẾP` | Ảnh hưởng gián tiếp (Thấp) | `indirect_ownership_pct`, `influence_level` = `LOW`, `r1_label`, `r1_ownership`, `r2_ownership`, `path` |
| **R03** | `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI` | Ảnh hưởng gián tiếp (Trung bình) | cùng nhóm; `influence_level` = `MEDIUM` (25% ≤ gián tiếp &lt; 50%) |
| **R03** | `KIỂM_SOÁT_GIÁN_TIẾP` | Ảnh hưởng gián tiếp (Cao) | cùng nhóm; `influence_level` = `HIGH` (≥ 50%) |
| **R04** | `CÙNG_CỔ_ĐÔNG_LỚN` | Cùng cổ đông lớn | `shared_holder_id`, `shared_holder_name`, `ownership_c`, `ownership_d` (cạnh **Company → Company**) |

**Ghi chú:**

- **R02 vs R03:** R02 yêu cầu `(a)-[:LÀ_CỔ_ĐÔNG_CỦA]->(b)` rồi `(b)-[:CÓ_CÔNG_TY_CON]->(c)` hoặc `(c)-[:LÀ_CÔNG_TY_CON_CỦA]->(b)`; luôn tạo `SỞ_HỮU_GIÁN_TIẾP`. R03 cho phép hop đầu `r1` rộng hơn nhưng vẫn yêu cầu hop thứ hai là `CÓ_CÔNG_TY_CON` (chỉ type=0 — công ty con thực sự). Các quan hệ `CÓ_CÔNG_TY_LIÊN_KẾT`, `LIÊN_DOANH_VỚI`, `ĐẦU_TƯ_VÀO` (type=1,2,3) không tham gia vào R02/R03.
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

