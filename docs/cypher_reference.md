# Tham chiếu truy vấn Cypher cho KG Việt Nam

Tài liệu mẫu truy vấn đồ thị doanh nghiệp niêm yết. Dùng làm template khi sinh Cypher chính xác.

**Dùng trong code:** `generate_cypher_with_llm()` tại `backend/script.py` (đọc file này lúc chạy). Chế độ agentic bật khi UI gửi `reasoning: true` trên `POST /api/query`.

## 1. Nhãn node và ID

- Mọi node có nhãn `:Entity`.
- Nhãn bổ sung: `:Person`, `:Company` (tùy dữ liệu).
- **ID:**
  - Công ty: `C_[MÃ]` (vd. `C_VIC`, `C_TCB`).
  - Cá nhân: `P_[ID]` (vd. `P_12345`).

## 2. Loại quan hệ cơ bản

- `(P)-[:LÃNH_ĐẠO_CAO_NHẤT]->(C)`: P là lãnh đạo cao nhất / Chủ tịch HĐQT của C.
- `(A)-[:LÀ_CỔ_ĐÔNG_CỦA]->(B)`: A là cổ đông của B (thuộc tính: `shares`, `ownership` — thường là phân số).
- `(A)-[:CÓ_CÔNG_TY_CON]->(B)`: B là công ty con của A (chỉ type=0 từ FireAnt — công ty con thực sự, tỷ lệ sở hữu >50%).
- `(A)-[:CÓ_CÔNG_TY_LIÊN_KẾT]->(B)`: B là công ty liên kết của A (type=1, tỷ lệ 20-50%).
- `(A)-[:LIÊN_DOANH_VỚI]->(B)`: A liên doanh với B (type=2).
- `(A)-[:ĐẦU_TƯ_VÀO]->(B)`: A có khoản đầu tư góp vốn vào B (type=3).
- `(A)-[:LÀ_CÔNG_TY_CON_CỦA]->(B)`: Cạnh ngược của CÓ_CÔNG_TY_CON (A là công ty con của B).
- `(P1)-[:VỢ_CHỒNG|:CHA_MẸ|:ANH_CHỊ]-(P2)`: Quan hệ gia đình.

## 3. Mẫu Cypher trừu tượng

### Mẫu A: Tính sở hữu gián tiếp / kiểm soát cuối

Tìm ai kiểm soát thực thể `E` qua chuỗi công ty.

```cypher
MATCH path = (A:Entity)-[:LÀ_CỔ_ĐÔNG_CỦA|CÓ_CÔNG_TY_CON*1..3]->(E:Entity {symbol: 'Target'})
WHERE A.type = 'Person'
RETURN A.name, [r IN relationships(path) | r.ownership] AS ownership_chain
```

### Mẫu B: Phát hiện sở hữu chéo

Hai thực thể `E1` và `E2` cùng nắm cổ phần lẫn nhau.

```cypher
MATCH (E1:Entity)-[r1:LÀ_CỔ_ĐÔNG_CỦA]->(E2:Entity),
      (E2)-[r2:LÀ_CỔ_ĐÔNG_CỦA]->(E1)
RETURN E1, r1, E2, r2
```

### Mẫu C: Mạng gia đình và cổ đông cùng công ty

Người thân của lãnh đạo `P1` cũng là cổ đông công ty `C`.

```cypher
MATCH (P1:Entity)-[:LÃNH_ĐẠO_CAO_NHẤT]->(C:Entity)
MATCH (P1)-[:VỢ_CHỒNG|CHA_MẸ|ANH_CHỊ]-(P2:Entity)
MATCH (P2)-[r:LÀ_CỔ_ĐÔNG_CỦA]->(C)
RETURN P1, P2, r, C
```

### Mẫu D: Chuỗi công ty con hai tầng

Tìm “cháu” công ty (hai bậc `CÓ_CÔNG_TY_CON`).

```cypher
MATCH (Parent:Entity)-[:CÓ_CÔNG_TY_CON]->(Child:Entity)-[:CÓ_CÔNG_TY_CON]->(GrandChild:Entity)
RETURN Parent, Child, GrandChild
```

### Mẫu E: Một người giữ nhiều vai trò lãnh đạo

Cá nhân là Chủ tịch HĐQT tại hơn một doanh nghiệp.

```cypher
MATCH (P:Entity)-[:LÃNH_ĐẠO_CAO_NHẤT]->(C:Entity)
WITH P, count(C) AS total_roles, collect(C.name) AS companies
WHERE total_roles > 1
RETURN P.name, total_roles, companies
```

### Mẫu F: Vừa lãnh đạo công ty A, vừa cổ đông công ty B (khác A)

```cypher
MATCH (p:Entity)-[r1]->(c1:Entity)
WHERE p.id STARTS WITH 'P_'
  AND c1.id STARTS WITH 'C_'
  AND type(r1) IN ['LÃNH_ĐẠO_CAO_NHẤT', 'CHỦ_TỊCH_HĐQT', 'TỔNG_GIÁM_ĐỐC']
MATCH (p)-[r2:LÀ_CỔ_ĐÔNG_CỦA]->(c2:Entity)
WHERE c2.id STARTS WITH 'C_' AND c1.id <> c2.id
RETURN p.id AS source_id, p.name AS source_name, p.type AS source_group, p.symbol AS source_symbol,
       c2.id AS target_id, c2.name AS target_name, c2.type AS target_group, c2.symbol AS target_symbol,
       type(r2) AS edge_label, coalesce(r2.inferred, false) AS inferred, r2.shares AS sh, r2.ownership AS ow
LIMIT 80
```

## 4. Định dạng RETURN bắt buộc (cho dashboard)

Luôn trả alias sau để tương thích visualization:

`source_id, source_name, source_group, source_symbol, target_id, target_name, target_group, target_symbol, edge_label, inferred`

Ví dụ:

```cypher
MATCH (n:Entity)-[r]->(m:Entity)
...
RETURN n.id AS source_id, n.name AS source_name, n.type AS source_group, n.symbol AS source_symbol,
       m.id AS target_id, m.name AS target_name, m.type AS target_group, m.symbol AS target_symbol,
       type(r) AS edge_label, coalesce(r.inferred, false) AS inferred
```

## 5. Quan hệ ẩn (suy diễn)

Cạnh có `r.inferred = true` và `r.inferred_from` ∈ `R01`–`R04`. Ví dụ lọc Luật 3:

```cypher
MATCH (a:Entity)-[r:KIỂM_SOÁT_GIÁN_TIẾP]->(b:Entity)
WHERE r.inferred_from = 'R03'
RETURN a.name, b.name, r.indirect_ownership_pct, r.influence_level
LIMIT 20
```

Chi tiết luật và nhãn cạnh: `inference_rules.md`, `entities_schema.md`.
