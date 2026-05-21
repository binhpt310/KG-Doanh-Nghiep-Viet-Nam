"""
Integration tests for UI suggested prompts (vi.ts suggestedPrompts).

Run:
  cd backend && python -m pytest tests/test_suggested_prompts.py -m integration -v

Requires Neo4j with synced KG (see pipeline preprocess + push).
Optional: KG_QUERY_API=http://localhost:5002/api/query for full answer checks.
"""
from __future__ import annotations

import os
import sys

import pytest

# Allow importing backend modules when cwd is backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytestmark = pytest.mark.integration

SUGGESTED_PROMPTS = [
    "Có cá nhân nào vừa là Chủ tịch HĐQT của một công ty vừa là cổ đông của công ty khác không?",
    "Những người thân của Chủ tịch tập đoàn Vingroup (VIC) có làm cổ đông của doanh nghiệp khác không?",
    "Có công ty con nào của ngân hàng MBB lại tiếp tục có công ty con của riêng nó tạo thành chuỗi 2 cấp bậc không?",
    "Cho biết những công ty nào là công ty con của VNM nhưng lại bị sở hữu bởi một cổ đông Tổ chức khác?",
    "Ai là cá nhân vừa nắm giữ chức vụ tại FPT, vừa là cổ đông của một công ty ngân hàng?",
    "Hồ Hùng Anh và những người thân trong gia đình ông đang sở hữu tổng cộng những công ty nào?",
    "Mô tả tất cả các sợi dây liên kết gián tiếp giữa Vingroup (VIC) và Vinhomes (VHM) qua các công ty con và cổ đông.",
    "Tìm các công ty con do Masan (MSN) sở hữu nhưng MSN không nắm 100% cổ phần mà bị pha loãng bởi cá nhân khác?",
]

CASES = [
    {
        "query": SUGGESTED_PROMPTS[0],
        "intent": "chairman_and_shareholder_other",
        "cypher_must_contain": ["leaderTypes", "LÀ_CỔ_ĐÔNG"],
        "min_rows": 1,
        "answer_must_not_contain": ["không tìm thấy", "không có dữ liệu graph"],
    },
    {
        "query": SUGGESTED_PROMPTS[1],
        "intent": "vic_family_shareholder_other",
        "cypher_must_contain": ["LÀ_NGƯỜI_THÂN", "LÀ_CỔ_ĐÔNG"],
        "min_rows": 0,
        "answer_must_not_contain": [],
    },
    {
        "query": SUGGESTED_PROMPTS[2],
        "intent": "subsidiary_chain_2",
        "cypher_must_contain": ["CÓ_CÔNG_TY_CON"],
        "min_rows": 0,
        "answer_must_not_contain": [],
    },
    {
        "query": SUGGESTED_PROMPTS[3],
        "intent": "vnm_subsidiary_institutional_holder",
        "cypher_must_contain": ["C_INST", "LÀ_CỔ_ĐÔNG"],
        "min_rows": 0,
        "answer_must_not_contain": [],
    },
    {
        "query": SUGGESTED_PROMPTS[4],
        "intent": "fpt_leader_bank_shareholder",
        "cypher_must_contain": ["fptId", "LÀ_CỔ_ĐÔNG"],
        "min_rows": 0,
        "answer_must_not_contain": [],
    },
    {
        "query": SUGGESTED_PROMPTS[5],
        "intent": "ho_hung_anh_family_holdings",
        "cypher_must_contain": ["LÀ_CỔ_ĐÔNG"],
        "min_rows": 0,
        "answer_must_not_contain": [],
    },
    {
        "query": SUGGESTED_PROMPTS[6],
        "intent": "vic_vhm_indirect_links",
        "cypher_must_contain": ["vicId", "vhmId"],
        "min_rows": 0,
        "answer_must_not_contain": [],
    },
    {
        "query": SUGGESTED_PROMPTS[7],
        "intent": "msn_subsidiary_diluted",
        "cypher_must_contain": ["CÓ_CÔNG_TY_CON", "LÀ_CỔ_ĐÔNG"],
        "min_rows": 0,
        "answer_must_not_contain": [],
    },
]


@pytest.fixture(scope="module")
def neo4j_driver():
    try:
        from neo4j import GraphDatabase
    except ImportError:
        pytest.skip("neo4j package not installed")

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password123")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
    except Exception as exc:
        pytest.skip(f"Neo4j unavailable: {exc}")
    yield driver
    driver.close()


@pytest.fixture(scope="module")
def script_module(neo4j_driver):
    import script as s

    return s


@pytest.mark.parametrize("case", CASES, ids=[c["intent"] for c in CASES])
def test_intent_detection(case, script_module):
    intent = script_module._detect_suggested_query_intent(case["query"])
    assert intent == case["intent"]


@pytest.mark.parametrize("case", CASES, ids=[c["intent"] for c in CASES])
def test_intent_cypher_runs(case, script_module, neo4j_driver):
    icypher, iparams = script_module._intent_cypher(case["intent"], case["query"])
    assert icypher
    for frag in case["cypher_must_contain"]:
        assert frag in icypher, f"missing {frag} in cypher for {case['intent']}"

    with neo4j_driver.session() as session:
        rows = list(session.run(icypher, **(iparams or {})))
    assert len(rows) >= case["min_rows"], (
        f"{case['intent']}: expected >= {case['min_rows']} rows, got {len(rows)}"
    )


@pytest.mark.parametrize("case", [CASES[0]], ids=["api_chairman_shareholder"])
def test_api_query_answer_quality(case):
    """Full stack: POST /api/query (requires kg-app running)."""
    try:
        import requests
    except ImportError:
        pytest.skip("requests not installed")

    api_url = os.getenv("KG_QUERY_API", "http://localhost:5002/api/query")
    payload = {
        "query": case["query"],
        "history": [],
        "model": os.getenv("MODEL_NAME", "qwen36-35b-a3b-fp8"),
        "reasoning": False,
    }
    try:
        resp = requests.post(api_url, json=payload, timeout=120)
    except Exception as exc:
        pytest.skip(f"API unavailable: {exc}")

    if resp.status_code != 200:
        pytest.skip(f"API returned {resp.status_code}")

    data = resp.json()
    answer = (data.get("answer") or "").lower()
    cypher = (data.get("cypher") or "").upper()

    for frag in case["cypher_must_contain"]:
        assert frag.upper() in cypher or frag in (data.get("cypher") or "")

    if case["min_rows"] > 0:
        for bad in case["answer_must_not_contain"]:
            assert bad not in answer, f"answer should not contain '{bad}'"


VOLUME_QUERIES = [
    "ngày hôm nay 21/5/2026 công ty chứng khoán nào có khối lượng giao dịch cao nhất?",
    "công ty chứng khoán nào có khối lượng giao dịch cao nhất ngày hôm nay 21/5/2026?",
    "công ty nào có khối lượng giao dịch chứng khoán cao nhất ngày hôm nay 21/5/2026?",
]


def test_live_market_query_detection(script_module):
    for q in VOLUME_QUERIES:
        assert script_module._is_live_market_query(q), q


def test_volume_queries_in_project_scope(script_module):
    for q in VOLUME_QUERIES:
        assert script_module._is_project_domain_query(q), q
        assert script_module._looks_like_named_entity_query(q), q


def test_volume_queries_not_out_of_scope_reply(script_module):
    oos = script_module._OUT_OF_SCOPE_REPLY
    for q in VOLUME_QUERIES:
        assert script_module._is_project_domain_query(q) or script_module._looks_like_named_entity_query(q)
        assert oos not in (script_module._build_live_news_query(q) or "")
