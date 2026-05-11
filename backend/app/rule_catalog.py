import unicodedata


HIDDEN_RULE_QUERIES = [
    {
        "rule_id": "R01",
        "name": "Gộp sở hữu vợ chồng",
        "labels": ["KIỂM_SOÁT_GIA_ĐÌNH"],
    },
    {
        "rule_id": "R02",
        "name": "Sở hữu gián tiếp qua công ty con",
        "labels": ["SỞ_HỮU_GIÁN_TIẾP"],
    },
    {
        "rule_id": "R03",
        "name": "Ảnh hưởng gián tiếp theo ngưỡng 5/25/50",
        "labels": [
            "CÓ_LỢI_ÍCH_GIÁN_TIẾP",
            "ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI",
            "KIỂM_SOÁT_GIÁN_TIẾP",
        ],
    },
    {
        "rule_id": "R04",
        "name": "Liên kết qua cùng cổ đông lớn",
        "labels": ["CÙNG_CỔ_ĐÔNG_LỚN"],
    },
]

LAW_DISPLAY_BY_RULE_ID = {
    "R01": "Luật 1 — Gộp sở hữu vợ chồng",
    "R02": "Luật 2 — Sở hữu gián tiếp qua công ty con",
    "R03": "Luật 3 — Ảnh hưởng gián tiếp theo ngưỡng 5/25/50",
    "R04": "Luật 4 — Liên kết qua cùng cổ đông lớn",
}

HIDDEN_REL_PRIORITY = {
    "KIỂM_SOÁT_GIÁN_TIẾP": 100,
    "ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI": 92,
    "CÓ_LỢI_ÍCH_GIÁN_TIẾP": 88,
    "SỞ_HỮU_GIÁN_TIẾP": 70,
    "KIỂM_SOÁT_GIA_ĐÌNH": 96,
    "CÙNG_CỔ_ĐÔNG_LỚN": 85,
}

RULES_API_PAYLOAD = [
    {
        "id": "R01",
        "name": "Luật 1 — Gộp sở hữu vợ chồng",
        "logic": "A -[VỢ_CHỒNG]- B, A/B cùng -[LÀ_CỔ_ĐÔNG_CỦA]-> C",
        "inferred": "A -[KIỂM_SOÁT_GIA_ĐÌNH]-> C",
        "explanation": "Nếu hai vợ chồng cùng nắm cổ phần tại một doanh nghiệp, hệ thống cộng tỷ lệ sở hữu để nhận diện mức kiểm soát gia đình thay vì nhìn từng cá nhân riêng lẻ.",
        "example": "Ông A nắm 18% và bà B nắm 12% tại Công ty C. Hệ thống suy ra gia đình A-B có 30% ảnh hưởng tại C.",
        "legal_refs": [
            {
                "title": "Thông tư 96/2020/TT-BTC - Hướng dẫn công bố thông tin trên thị trường chứng khoán",
                "url": "https://vanban.chinhphu.vn/default.aspx?docid=201902&pageid=27160",
                "citation": "Điều 31 (công bố thông tin khi sở hữu từ 5% trở lên số cổ phiếu có quyền biểu quyết; cổ đông lớn và nhóm liên quan).",
            },
            {
                "title": "Nghị định 168/2025/NĐ-CP - Về đăng ký doanh nghiệp",
                "url": "https://vanban.chinhphu.vn/?docid=214334&pageid=27160",
                "citation": "Điều 17 (xác định chủ sở hữu hưởng lợi; ngưỡng 25% vốn/cổ phần có quyền biểu quyết); Điều 18 (kê khai và thông báo thay đổi thông tin CSHL).",
            },
            {
                "title": "Luật số 76/2025/QH15 - Luật sửa đổi, bổ sung một số điều của Luật Doanh nghiệp",
                "url": "https://vanban.chinhphu.vn/?classid=1&docid=214562&pageid=27160&typegroupid=3",
                "citation": "Các điều khoản sửa đổi, bổ sung phần khai báo người có liên quan của cổ đông (đối chiếu mục lục văn bản QH15 theo từng điều đã sửa).",
            },
        ],
    },
    {
        "id": "R02",
        "name": "Luật 2 — Sở hữu gián tiếp qua công ty con",
        "logic": "A -[LÀ_CỔ_ĐÔNG_CỦA:x]-> B, B/C có quan hệ công ty con với tỷ lệ y",
        "inferred": "A -[SỞ_HỮU_GIÁN_TIẾP:(x*y)]-> C",
        "explanation": "Khi A sở hữu B và B kiểm soát hoặc sở hữu công ty con C, hệ thống nhân chuỗi tỷ lệ để tính phần sở hữu gián tiếp của A tại C.",
        "example": "A nắm 40% ở B, còn B nắm 60% ở C. Hệ thống suy ra A sở hữu gián tiếp 24% ở C.",
        "legal_refs": [
            {
                "title": "Luật số 54/2019/QH14 - Luật Chứng khoán",
                "url": "https://vanban.chinhphu.vn/default.aspx?docid=198541&pageid=27160",
                "citation": "Chương về công bố thông tin — tham chiếu các điều về cổ đông lớn, người có liên quan và nghĩa vụ minh bạch (ví dụ khu vực Điều 33 và các điều cùng chương trong bản chính thứ).",
            },
            {
                "title": "Thông tư 96/2020/TT-BTC - Hướng dẫn công bố thông tin trên thị trường chứng khoán",
                "url": "https://vanban.chinhphu.vn/default.aspx?docid=201902&pageid=27160",
                "citation": "Điều 31 (công bố khi chạm ngưỡng 5% và thay đổi theo từng ngưỡng 1%); các khoản hướng dẫn mẫu báo cáo tại Phụ lục VII.",
            },
        ],
    },
    {
        "id": "R03",
        "name": "Luật 3 — Ảnh hưởng gián tiếp theo ngưỡng 5/25/50",
        "logic": "A -[r1]-> B, B/C có quan hệ công ty con với tỷ lệ sở hữu; tính tỷ lệ gián tiếp rồi phân loại mức ảnh hưởng",
        "inferred": "A -[CÓ_LỢI_ÍCH_GIÁN_TIẾP | ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI | KIỂM_SOÁT_GIÁN_TIẾP]-> C",
        "explanation": "Sau khi tính được tỷ lệ sở hữu gián tiếp, hệ thống gán nhãn theo ngưỡng pháp lý: từ 5% là lợi ích gián tiếp, từ 25% là ảnh hưởng đáng kể, từ 50% là kiểm soát.",
        "example": "A nắm 30% ở B, B nắm 51% ở C. Tỷ lệ gián tiếp của A ở C là 15.3%, nên hệ thống gán nhãn CÓ_LỢI_ÍCH_GIÁN_TIẾP.",
        "legal_refs": [
            {
                "title": "Thông tư 96/2020/TT-BTC - Hướng dẫn công bố thông tin trên thị trường chứng khoán",
                "url": "https://vanban.chinhphu.vn/default.aspx?docid=201902&pageid=27160",
                "citation": "Điều 31 (ngưỡng cổ đông lớn 5% và công bố thay đổi); liên hệ các khoản về nhóm người có liên quan trong cùng Thông tư.",
            },
            {
                "title": "Nghị định 168/2025/NĐ-CP - Về đăng ký doanh nghiệp",
                "url": "https://vanban.chinhphu.vn/?docid=214334&pageid=27160",
                "citation": "Điều 17 (tiêu chí CSHL, gồm sở hữu gián tiếp từ 25%); Điều 18 (nghĩa vụ kê khai/thông báo).",
            },
            {
                "title": "Luật số 54/2019/QH14 - Luật Chứng khoán",
                "url": "https://vanban.chinhphu.vn/default.aspx?docid=198541&pageid=27160",
                "citation": "Các điều về công bố thông tin và quan hệ sở hữu có điều kiện (tham chiếu chương công bố thông tin; đối chiếu Điều 33 và điều khoản lân cận trong bản luật).",
            },
        ],
    },
    {
        "id": "R04",
        "name": "Luật 4 — Liên kết qua cùng cổ đông lớn",
        "logic": "Một cá nhân là cổ đông >= 5% tại hai doanh nghiệp niêm yết khác nhau",
        "inferred": "Công ty X -[CÙNG_CỔ_ĐÔNG_LỚN]-> Công ty Y",
        "explanation": "Nếu cùng một cá nhân là cổ đông lớn ở hai công ty, hệ thống tạo liên kết để giúp phát hiện mạng lưới ảnh hưởng chéo giữa các doanh nghiệp.",
        "example": "Ông A nắm 8% ở X và 6% ở Y. Hệ thống suy ra X và Y có liên hệ qua cùng cổ đông lớn là ông A.",
        "legal_refs": [
            {
                "title": "Thông tư 96/2020/TT-BTC - Hướng dẫn công bố thông tin trên thị trường chứng khoán",
                "url": "https://vanban.chinhphu.vn/default.aspx?docid=201902&pageid=27160",
                "citation": "Điều 31 khoản 1 (trở thành cổ đông lớn từ 5%); các khoản hướng dẫn báo cáo/biểu mẫu liên quan cổ đông lớn.",
            },
            {
                "title": "Luật số 54/2019/QH14 - Luật Chứng khoán",
                "url": "https://vanban.chinhphu.vn/default.aspx?docid=198541&pageid=27160",
                "citation": "Khu vực công bố thông tin về cổ đông lớn và người có liên quan (tham chiếu Điều 33 và các điều cùng chương trong bản chính thứ).",
            },
        ],
    },
]


def normalize_vn_text(text):
    """Normalize Vietnamese text to support accent-insensitive rule lookup."""
    if not text:
        return ""
    text = str(text).replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().strip().split())


def law_display(rule_id):
    rule_id = (rule_id or "").strip()
    if not rule_id:
        return "Luật (không xác định)"
    return LAW_DISPLAY_BY_RULE_ID.get(rule_id, f"Luật ({rule_id})")


# Neo4j relationship types for R03 — one type per band of indirect % (5/25/50); see inference_rules._R03_LABEL_MAP.
R03_INFERRED_EDGE_TYPES = frozenset(
    {
        "CÓ_LỢI_ÍCH_GIÁN_TIẾP",
        "ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI",
        "KIỂM_SOÁT_GIÁN_TIẾP",
    }
)


def influence_level_display_vi(level):
    """Vietnamese labels for persisted values LOW | MEDIUM | HIGH (UI / human-readable text)."""
    u = (level or "").strip().upper()
    if u == "LOW":
        return "Thấp"
    if u == "MEDIUM":
        return "Trung bình"
    if u == "HIGH":
        return "Cao"
    if u == "NONE":
        return "dưới ngưỡng"
    return level or "không xác định"


def inferred_edge_label_display_vi(relation_label, rule_id):
    """
    One user-facing name for all R03 Neo4j edge types (bands map to LOW/MEDIUM/HIGH separately).
    Other inferred types get short Vietnamese names; unknown labels returned as-is.
    """
    rid = (rule_id or "").strip()
    rel = (relation_label or "").strip()
    if rid == "R03" and rel in R03_INFERRED_EDGE_TYPES:
        return "Ảnh hưởng gián tiếp"
    if rel == "KIỂM_SOÁT_GIA_ĐÌNH":
        return "Kiểm soát gia đình"
    if rel == "SỞ_HỮU_GIÁN_TIẾP":
        return "Sở hữu gián tiếp"
    if rel == "CÙNG_CỔ_ĐÔNG_LỚN":
        return "Cùng cổ đông lớn"
    return rel


def hidden_relation_priority(relation):
    if not relation:
        return 0
    return int(HIDDEN_REL_PRIORITY.get(str(relation).strip(), 35))
