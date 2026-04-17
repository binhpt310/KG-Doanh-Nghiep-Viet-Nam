#!/usr/bin/env python3
"""
Script dùng 1 lần: Thêm quan hệ LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO vào Neo4j.
Với mỗi (family)-[fam_rel]->(leader) và (leader)-[lead_rel]->(company),
tạo (family)-[:LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO]->(company) với props:
  leaderRelationship, leaderName, leaderId, position, familyRelation
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Quan hệ gia đình (whitelist) - KHÔNG bao gồm chức vụ công ty
# Chức vụ loại trừ: CHỦ_TỊCH_HĐQT, THÀNH_VIÊN_HĐQT, TRƯỞNG_BAN_KIỂM_SOÁT,
# THÀNH_VIÊN_BAN_KIỂM_SOÁT, GIÁM_ĐỐC_*, PHÓ_*, TỔNG_GIÁM_ĐỐC, K_TOÁN_TRƯỞNG, ...
FAMILY_RELS = [
    "ANH", "ANHEM_TRAI", "ANH_CHỊ", "ANH_CHỒNG", "ANH_CÙNG_BỐ_KHÁC_MẸ",
    "ANH_RỂ", "ANH_VỢ", "BÀ_NGOẠI", "BÀ_NỘI", "BÁC_ANH_CỦA_BỐ", "BÁC_ANH_CỦA_MẸ",
    "BÁC_CHỊ_CỦA_BỐ", "BÁC_CHỊ_CỦA_MẸ", "BỐ", "BỐ_CHỒNG", "BỐ_VỢ", "CHA_MẸ",
    "CHÁU_GÁI_CON_CỦA_ANH", "CHÁU_GÁI_CON_CỦA_CHỊ", "CHÁU_GÁI_CON_CỦA_EM_GÁI",
    "CHÁU_GÁI_CON_CỦA_EM_TRAI", "CHÁU_NGOẠI_GÁI", "CHÁU_NGOẠI_TRAI", "CHÁU_NỘI_GÁI",
    "CHÁU_NỘI_TRAI", "CHÁU_TRAI_CON_CỦA_ANH", "CHÁU_TRAI_CON_CỦA_CHỊ",
    "CHÁU_TRAI_CON_CỦA_EM_GÁI", "CHÁU_TRAI_CON_CỦA_EM_TRAI", "CHÚ",
    "CHỊ", "CHỊEM_GÁI", "CHỊ_CHỒNG", "CHỊ_DÂU", "CHỊ_DÂU_CỦA_CHỒNG", "CHỊ_VỢ",
    "CON_DÂU", "CON_RỂ", "CÔ", "CẬU", "DÌ",
    "EM_DÂU", "EM_DÂU_CỦA_CHỒNG", "EM_GÁI_CHỒNG", "EM_GÁI_CÙNG_BỐ_KHÁC_MẸ",
    "EM_GÁI_VỢ", "EM_RỂ", "EM_TRAI_CHỒNG", "EM_TRAI_CÙNG_BỐ_KHÁC_MẸ", "EM_TRAI_VỢ",
    "MẸ", "MẸ_CHỒNG", "MẸ_VỢ", "NGƯỜI_THÂN", "NGƯỜI_THÂN_QUA_HÔN_NHÂN",
    "VỢ_CHỒNG", "ÔNG_NGOẠI", "ÔNG_NỘI"
]

# Quan hệ lãnh đạo
LEADER_RELS = ["LÃNH_ĐẠO_CAO_NHẤT", "CHỦ_TỊCH_HĐQT", "TỔNG_GIÁM_ĐỐC"]

# Map type(r) -> tên hiển thị ngắn
FAM_DISPLAY = {
    "CHA_MẸ": "cha/mẹ", "MẸ": "mẹ", "BỐ": "bố", "ANH_CHỊ": "anh/chị", "VỢ_CHỒNG": "vợ/chồng",
    "CHỊ": "chị", "ANH": "anh", "NGƯỜI_THÂN": "người thân", "ÔNG_NỘI": "ông nội",
    "ÔNG_NGOẠI": "ông ngoại", "BÀ_NỘI": "bà nội", "BÀ_NGOẠI": "bà ngoại",
    "BỐ_VỢ": "bố vợ", "MẸ_VỢ": "mẹ vợ", "BỐ_CHỒNG": "bố chồng", "MẸ_CHỒNG": "mẹ chồng",
}


def run(driver):
    def create_relation(tx, family_id, company_id, company_name, leader_id, leader_name, position, fam_rel):
        display_fam = FAM_DISPLAY.get(fam_rel, fam_rel.replace("_", " ").lower())
        comp = company_name or company_id
        leader_rel = f"[{display_fam}] của [{leader_name}] có chức vụ là [{position}] [{comp}]"
        q = """
        MATCH (a:Entity {id: $fam_id})
        MATCH (b:Entity {id: $comp_id})
        MERGE (a)-[r:LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO]->(b)
        ON CREATE SET r.leaderRelationship = $lr, r.leaderName = $ln, r.leaderId = $lid,
                      r.position = $pos, r.familyRelation = $frel, r.label = 'LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO'
        ON MATCH SET r.leaderRelationship = $lr, r.leaderName = $ln, r.leaderId = $lid,
                     r.position = $pos, r.familyRelation = $frel
        """
        tx.run(q, fam_id=family_id, comp_id=company_id, lr=leader_rel, ln=leader_name,
               lid=leader_id, pos=position, frel=fam_rel)

    with driver.session() as session:
        # Xóa hết LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO cũ rồi tạo lại với whitelist đúng
        session.run("MATCH ()-[r:LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO]->() DELETE r")
        q = """
        MATCH (leader:Entity)-[r1]->(company:Entity)
        WHERE company.id =~ 'C_[A-Z0-9]{2,6}'
        AND type(r1) IN $lead_rels
        MATCH (family:Entity)-[r2]->(leader)
        WHERE type(r2) IN $fam_rels
        RETURN DISTINCT family.id AS fam_id, company.id AS comp_id, company.name AS comp_name,
               leader.id AS leader_id, leader.name AS leader_name,
               r1.label AS position, type(r2) AS fam_rel
        """
        result = session.run(q, lead_rels=LEADER_RELS, fam_rels=FAMILY_RELS)
        rows = list(result)
        created = 0
        for rec in rows:
            session.execute_write(
                create_relation,
                rec["fam_id"], rec["comp_id"], rec["comp_name"], rec["leader_id"],
                rec["leader_name"], rec["position"], rec["fam_rel"]
            )
            created += 1
        return created


if __name__ == "__main__":
    uri = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    pw = os.getenv("NEO4J_PASSWORD", "password123")
    driver = GraphDatabase.driver(uri, auth=(user, pw))
    try:
        n = run(driver)
        print(f"Đã tạo/cập nhật {n} quan hệ LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO")
    finally:
        driver.close()
