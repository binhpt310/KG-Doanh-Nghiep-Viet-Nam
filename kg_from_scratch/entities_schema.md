
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

### 🔗 **Quan hệ (Edges) và các trường đi kèm**

| Loại quan hệ                  | Trường props                                      |
|-------------------------------|--------------------------------------------------|
| `LÀ_CỔ_ĐÔNG_CỦA`             | `shares` (số cổ phiếu), `ownership` (tỷ lệ %)    |
| `MANAGES` / `IS_OFFICER`     | (trống)                                          |
| `CÓ_CÔNG_TY_CON`             | (trống)                                          |
| `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI`   | `inferred: true`                                 |

***