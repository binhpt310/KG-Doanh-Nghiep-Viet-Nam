# Cypher Query Reference for Vietnamese KG

This document provides abstract patterns for querying the Vietnamese Business Knowledge Graph. Use these as templates for generating precise Cypher queries.

## 1. Node Labels & IDs
- All nodes are labeled `:Entity`.
- Additional labels: `:Person`, `:Company`.
- **IDs**: 
  - Companies: `C_[SYMBOL]` or similar (e.g., `C_VIC`, `C_TCB`).
  - Persons: `P_[UNIQUE_ID]` (e.g., `P_12345`).

## 2. Basic Relationship Types
- `(P)-[:LÃNH_ĐẠO_CAO_NHẤT]->(C)`: P is the top leader/Chairman of company C.
- `(A)-[:LÀ_CỔ_ĐÔNG_CỦA]->(B)`: A owns shares in B. (Props: `shares`, `ownership`).
- `(A)-[:CÓ_CÔNG_TY_CON]->(B)`: B is a subsidiary of A.
- `(P1)-[:VỢ_CHỒNG | :CHA_MẸ | :ANH_CHỊ]->(P2)`: Family relations.

## 3. Abstract Cypher Patterns

### Pattern A: Ultimate Ownership Calculation
Find who ultimately controls entity `E` through a chain of companies.
```cypher
MATCH path = (A:Entity)-[:LÀ_CỔ_ĐÔNG_CỦA|CÓ_CÔNG_TY_CON*1..3]->(E:Entity {symbol: 'Target'})
WHERE A.type = 'Person'
RETURN A.name, [r in relationships(path) | r.ownership] as ownership_chain
```

### Pattern B: Cross-Ownership Detection
Find if two entities `E1` and `E2` own shares in each other.
```cypher
MATCH (E1:Entity)-[r1:LÀ_CỔ_ĐÔNG_CỦA]->(E2:Entity),
      (E2)-[r2:LÀ_CỔ_ĐÔNG_CỦA]->(E1)
RETURN E1, r1, E2, r2
```

### Pattern C: Family Network & Indirect Control
Find family members of a leader (P1) who also hold shares in the same company (C).
```cypher
MATCH (P1:Entity)-[:LÃNH_ĐẠO_CAO_NHẤT]->(C:Entity)
MATCH (P1)-[:VỢ_CHỒNG|CHA_MẸ|ANH_CHỊ]-(P2:Entity)
MATCH (P2)-[r:LÀ_CỔ_ĐÔNG_CỦA]->(C)
RETURN P1, P2, r, C
```

### Pattern D: Multi-hop Subsidiary Discovery
Find "grand-children" companies (Chain of 2 levels).
```cypher
MATCH (Parent:Entity)-[:CÓ_CÔNG_TY_CON]->(Child:Entity)-[:CÓ_CÔNG_TY_CON]->(GrandChild:Entity)
RETURN Parent, Child, GrandChild
```

### Pattern E: Person with Multiple Leadership Roles
Find individuals holding "Chairman" positions in more than one entity.
```cypher
MATCH (P:Entity)-[:LÃNH_ĐẠO_CAO_NHẤT]->(C:Entity)
WITH P, count(C) as total_roles, collect(C.name) as companies
WHERE total_roles > 1
RETURN P.name, total_roles, companies
```

## 4. Mandatory Return Format (for Dashboard)
Always return the following aliases for graph visualization compatibility:
`source_id, source_name, source_group, source_symbol, target_id, target_name, target_group, target_symbol, edge_label, inferred`

Example:
```cypher
MATCH (n:Entity)-[r]->(m:Entity)
...
RETURN n.id AS source_id, n.name AS source_name, n.type AS source_group, n.symbol AS source_symbol,
       m.id AS target_id, m.name AS target_name, m.type AS target_group, m.symbol AS target_symbol,
       type(r) AS edge_label, coalesce(r.inferred, false) AS inferred
```
