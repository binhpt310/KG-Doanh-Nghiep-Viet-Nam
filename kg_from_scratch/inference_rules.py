"""
inference_rules.py — Hidden Relations Inference Engine for Vietnamese listed companies KG.

Implements legal-threshold-based inference rules:
  R01 — Spousal Ownership Aggregation
  R02 — Indirect Ownership Chain
  R07 — Indirect Influence (upgraded with ownership thresholds)

Legal references:
  - TT 96/2020/TT-BTC (>=5% disclosure)
  - Nghị định 168/2025/NĐ-CP, Luật Doanh nghiệp 2025 (>=25% UBO)
  - Luật Chứng khoán 2019 (>=50% absolute control)
"""

import time

# ============================================================================
# SECTION 1 — Legal Thresholds
# ============================================================================

THRESHOLD_LARGE_SHAREHOLDER = 0.05    # 5% — Must disclose (TT 96/2020/TT-BTC)
THRESHOLD_UBO = 0.25                   # 25% — Ultimate Beneficial Owner (NĐ 168/2025/NĐ-CP)
THRESHOLD_ABSOLUTE_CONTROL = 0.50      # 50% — Absolute control (Luật Chứng khoán 2019)


# ============================================================================
# SECTION 2 — Helper: classify influence level from ownership percentage
# ============================================================================

def _classify_influence(pct: float) -> str:
    """Return influence level string based on ownership percentage."""
    if pct < THRESHOLD_LARGE_SHAREHOLDER * 100:
        return "NONE"   # < 5% — skip
    if pct < THRESHOLD_UBO * 100:
        return "LOW"    # 5% <= x < 25%
    if pct < THRESHOLD_ABSOLUTE_CONTROL * 100:
        return "MEDIUM" # 25% <= x < 50%
    return "HIGH"        # x >= 50%


# ============================================================================
# SECTION 3 — Rule R01: Spousal Ownership Aggregation
# ============================================================================
#
# If A-B are spouses, A owns x% of C, B owns y% of C
# → Family (A,B) controls (x+y)% of C
#
# Legal basis: Nghị định 168/2025/NĐ-CP — UBO includes spouse's ownership.
# ============================================================================

def run_r01_spousal_aggregation(driver, batch_size: int = 500) -> int:
    """
    R01 — Spousal Ownership Aggregation.

    Finds spouse pairs where both own shares in the same company,
    then creates a 'KIỂM_SOÁT_GIA_ĐÌNH' relation with combined ownership.

    Returns total new relations created.
    """
    total_created = 0

    while True:
        query = """
        MATCH (a:Entity)-[spouse_rel]-(b:Entity)
        WHERE type(spouse_rel) = 'VỢ_CHỒNG'
        MATCH (a)-[r1:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
        MATCH (b)-[r2:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
        WHERE r1.ownership IS NOT NULL AND r2.ownership IS NOT NULL
          AND a <> b
          AND NOT EXISTS { (a)-[:KIỂM_SOÁT_GIA_ĐÌNH]->(c) }
        RETURN a.id AS A, a.name AS A_name,
               b.id AS B, b.name AS B_name,
               c.id AS C, c.name AS C_name, c.symbol AS C_symbol,
               toFloat(r1.ownership) AS own_a,
               toFloat(r2.ownership) AS own_b
        LIMIT $batch
        """
        with driver.session() as session:
            result = session.run(query, batch=batch_size)
            records = list(result)

        if not records:
            break

        created_this_round = 0
        for rec in records:
            a_id = rec["A"]
            b_id = rec["B"]
            c_id = rec["C"]
            c_name = rec.get("C_name", c_id)
            c_symbol = rec.get("C_symbol", "")
            own_a = rec["own_a"]
            own_b = rec["own_b"]
            combined = own_a + own_b

            # Convert from decimal (0.15) to percentage (15.0) for display
            combined_pct = combined * 100

            influence = _classify_influence(combined_pct)
            if influence == "NONE":
                continue

            rel_label = "KIỂM_SOÁT_GIA_ĐÌNH"

            with driver.session() as session:
                session.run(f"""
                MATCH (a:Entity {{id: $src}})
                MATCH (c:Entity {{id: $tgt}})
                MERGE (a)-[r:`{rel_label}`]->(c)
                ON CREATE SET r.inferred = true,
                              r.inferred_from = 'R01',
                              r.combined_ownership_pct = $combined_pct,
                              r.ownership_a = $own_a_pct,
                              r.ownership_b = $own_b_pct,
                              r.spouse_id = $spouse_id,
                              r.spouse_name = $spouse_name,
                              r.influence_level = $influence,
                              r.label = $label,
                              r.path = $path
                """,
                src=a_id, tgt=c_id,
                combined_pct=combined_pct,
                own_a_pct=own_a * 100,
                own_b_pct=own_b * 100,
                spouse_id=b_id,
                spouse_name=rec.get("B_name", b_id),
                influence=influence,
                label=rel_label,
                path=f"{a_id}⇔{b_id}→{c_id}"
                )
            created_this_round += 1

        total_created += created_this_round
        if created_this_round == 0:
            break

    return total_created


# ============================================================================
# SECTION 4 — Rule R02: Indirect Ownership Chain
# ============================================================================
#
# A owns x% of B, B owns y% of C → A indirectly owns (x*y)% of C
#
# Legal basis: Luật Chứng khoán 2019 — indirect ownership calculation.
# ============================================================================

def run_r02_indirect_ownership(driver, batch_size: int = 500) -> int:
    """
    R02 — Indirect Ownership Chain.

    For each A→B (ownership x%) and B→C (ownership y%),
    creates A→C with indirect ownership = x * y.

    Returns total new relations created.
    """
    total_created = 0

    while True:
        query = """
        MATCH (a:Entity)-[r1:LÀ_CỔ_ĐÔNG_CỦA]->(b:Entity)
        MATCH (b:Entity)-[r2:CÓ_CÔNG_TY_CON]->(c:Entity)
        WHERE r1.ownership IS NOT NULL
          AND a <> c
          AND NOT EXISTS { (a)-[:SỞ_HỮU_GIÁN_TIẾP]->(c) }
          AND NOT EXISTS { (a)-[:LÀ_CỔ_ĐÔNG_CỦA]->(c) }
        RETURN a.id AS A, a.name AS A_name,
               b.id AS B, b.name AS B_name,
               c.id AS C, c.name AS C_name, c.symbol AS C_symbol,
               toFloat(r1.ownership) AS own_ab,
               toFloat(r2.ownership) AS own_bc
        LIMIT $batch
        """
        with driver.session() as session:
            result = session.run(query, batch=batch_size)
            records = list(result)

        if not records:
            break

        created_this_round = 0
        for rec in records:
            a_id = rec["A"]
            c_id = rec["C"]
            c_name = rec.get("C_name", c_id)
            c_symbol = rec.get("C_symbol", "")
            own_ab = rec["own_ab"]  # already a fraction (e.g. 0.30 = 30%)
            own_bc = rec["own_bc"]  # already a fraction

            # indirect_ownership = own_ab * own_bc (both are fractions)
            # e.g. 0.30 * 0.51 = 0.153 → 15.3%
            indirect_pct = own_ab * own_bc * 100

            influence = _classify_influence(indirect_pct)
            if influence == "NONE":
                continue

            rel_label = "SỞ_HỮU_GIÁN_TIẾP"

            with driver.session() as session:
                session.run(f"""
                MATCH (a:Entity {{id: $src}})
                MATCH (c:Entity {{id: $tgt}})
                MERGE (a)-[r:`{rel_label}`]->(c)
                ON CREATE SET r.inferred = true,
                              r.inferred_from = 'R02',
                              r.indirect_ownership_pct = $indirect_pct,
                              r.r1_ownership = $r1_pct,
                              r.r2_ownership = $r2_pct,
                              r.influence_level = $influence,
                              r.label = $label,
                              r.path = $path
                """,
                src=a_id, tgt=c_id,
                indirect_pct=round(indirect_pct, 4),
                r1_pct=round(own_ab * 100, 4),
                r2_pct=round(own_bc * 100, 4),
                influence=influence,
                label=rel_label,
                path=f"{a_id}→{rec['B']}→{c_id}"
                )
            created_this_round += 1

        total_created += created_this_round
        if created_this_round == 0:
            break

    return total_created


# ============================================================================
# SECTION 5 — Rule R07: Indirect Influence (Upgraded)
# ============================================================================
#
# A --[r1: ownership x%]--> B --[CÓ_CÔNG_TY_CON: ownership y%]--> C
# Calculate: indirect_ownership = (x/100) * (y/100) * 100
#   < 5%: SKIP
#   5% ≤ x < 25%: "CÓ_LỢI_ÍCH_GIÁN_TIẾP" (LOW)
#   25% ≤ x < 50%: "ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI" (MEDIUM)
#   x ≥ 50%: "KIỂM_SOÁT_GIÁN_TIẾP" (HIGH)
# ============================================================================

# Map influence level to relation label
_R07_LABEL_MAP = {
    "LOW": "CÓ_LỢI_ÍCH_GIÁN_TIẾP",
    "MEDIUM": "ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI",
    "HIGH": "KIỂM_SOÁT_GIÁN_TIẾP",
}


def run_r07_indirect_influence(driver, batch_size: int = 500) -> int:
    """
    R07 — Indirect Influence (Upgraded with legal thresholds).

    Finds 2-hop paths where A has a relation to B, and B owns C as subsidiary.
    Calculates indirect ownership and creates typed influence relations.

    Returns total new relations created.
    """
    total_created = 0

    while True:
        query = """
        MATCH (a:Entity)-[r1]->(b:Entity)-[r2:CÓ_CÔNG_TY_CON]->(c:Entity)
        WHERE a <> c
          AND type(r1) <> 'CÓ_CÔNG_TY_CON'
          AND r2.ownership IS NOT NULL
          AND r2.ownership > 0
          AND NOT EXISTS { (a)-[:CÓ_LỢI_ÍCH_GIÁN_TIẾP]->(c) }
          AND NOT EXISTS { (a)-[:ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI]->(c) }
          AND NOT EXISTS { (a)-[:KIỂM_SOÁT_GIÁN_TIẾP]->(c) }
          AND NOT EXISTS { (a)-[:ẢNH_HƯỞNG_GIÁN_TIẾP]->(c) }
        RETURN a.id AS A, a.name AS A_name,
               b.id AS B, b.name AS B_name,
               c.id AS C, c.name AS C_name, c.symbol AS C_symbol,
               r1.label AS r1_label,
               coalesce(toFloat(r1.ownership), 1.0) AS r1_ownership,
               toFloat(r2.ownership) AS r2_ownership
        LIMIT $batch
        """
        with driver.session() as session:
            result = session.run(query, batch=batch_size)
            records = list(result)

        if not records:
            break

        created_this_round = 0
        for rec in records:
            a_id = rec["A"]
            c_id = rec["C"]
            c_name = rec.get("C_name", c_id)
            c_symbol = rec.get("C_symbol", "")
            r1_label = rec.get("r1_label", "")
            r1_ownership = rec["r1_ownership"]  # fraction or 1.0 if no ownership
            r2_ownership = rec["r2_ownership"]  # fraction

            # If r1_ownership is already a fraction (e.g. 0.30), use it directly
            # If it's > 1, it might be a percentage (e.g. 30), so convert
            if r1_ownership > 1.0:
                r1_frac = r1_ownership / 100.0
            else:
                r1_frac = r1_ownership

            if r2_ownership > 1.0:
                r2_frac = r2_ownership / 100.0
            else:
                r2_frac = r2_ownership

            # indirect_ownership = r1_frac * r2_frac * 100
            indirect_pct = r1_frac * r2_frac * 100

            influence = _classify_influence(indirect_pct)
            if influence == "NONE":
                continue

            rel_label = _R07_LABEL_MAP[influence]

            with driver.session() as session:
                session.run(f"""
                MATCH (a:Entity {{id: $src}})
                MATCH (c:Entity {{id: $tgt}})
                MERGE (a)-[r:`{rel_label}`]->(c)
                ON CREATE SET r.inferred = true,
                              r.inferred_from = 'R07',
                              r.indirect_ownership_pct = $indirect_pct,
                              r.influence_level = $influence,
                              r.r1_ownership = $r1_pct,
                              r.r2_ownership = $r2_pct,
                              r.r1_label = $r1_label,
                              r.path = $path,
                              r.label = $label
                """,
                src=a_id, tgt=c_id,
                indirect_pct=round(indirect_pct, 4),
                influence=influence,
                r1_pct=round(r1_frac * 100, 4),
                r2_pct=round(r2_frac * 100, 4),
                r1_label=r1_label,
                path=f"{a_id}→{rec['B']}→{c_id}",
                label=rel_label
                )
            created_this_round += 1

        total_created += created_this_round
        if created_this_round == 0:
            break

    return total_created


# ============================================================================
# SECTION 6 — Master: Run All Inference Rules
# ============================================================================

def run_all_inference_rules(driver, batch_size: int = 500) -> dict:
    """
    Run all inference rules in sequence.
    Each rule loops internally until no new relations are found.

    Args:
        driver: Neo4j GraphDatabase driver instance.
        batch_size: Number of records to process per batch (default 500).

    Returns:
        dict with counts per rule and total.
    """
    start_time = time.time()
    results = {}

    print(f"\n{'='*60}")
    print("🔍 HIDDEN RELATIONS INFERENCE ENGINE — Starting all rules")
    print(f"{'='*60}")

    # R01 — Spousal Ownership Aggregation
    print("\n📌 R01: Spousal Ownership Aggregation...")
    try:
        r01_count = run_r01_spousal_aggregation(driver, batch_size)
        results["R01_spousal_aggregation"] = r01_count
        print(f"   ✅ R01: Created {r01_count} family control relations")
    except Exception as e:
        results["R01_spousal_aggregation"] = 0
        print(f"   ⚠️ R01 error: {e}")

    # R02 — Indirect Ownership Chain
    print("\n📌 R02: Indirect Ownership Chain...")
    try:
        r02_count = run_r02_indirect_ownership(driver, batch_size)
        results["R02_indirect_ownership"] = r02_count
        print(f"   ✅ R02: Created {r02_count} indirect ownership relations")
    except Exception as e:
        results["R02_indirect_ownership"] = 0
        print(f"   ⚠️ R02 error: {e}")

    # R07 — Indirect Influence (Upgraded)
    print("\n📌 R07: Indirect Influence (threshold-based)...")
    try:
        r07_count = run_r07_indirect_influence(driver, batch_size)
        results["R07_indirect_influence"] = r07_count
        print(f"   ✅ R07: Created {r07_count} indirect influence relations")
    except Exception as e:
        results["R07_indirect_influence"] = 0
        print(f"   ⚠️ R07 error: {e}")

    elapsed = time.time() - start_time
    results["total"] = sum(v for k, v in results.items() if k.startswith("R"))
    results["elapsed_seconds"] = round(elapsed, 2)

    print(f"\n{'='*60}")
    print(f"✅ INFERENCE COMPLETE — Total: {results['total']} new relations in {results['elapsed_seconds']}s")
    print(f"{'='*60}")

    return results
