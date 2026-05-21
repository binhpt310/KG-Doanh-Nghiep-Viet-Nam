"""Unit tests for FireAnt market API helper."""
from __future__ import annotations

import os
import sys
from datetime import date
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import fireant_market as fm


def test_parse_query_trade_date_explicit():
    d = fm.parse_query_trade_date("KLGD cao nhất ngày 21/5/2026", default_today=False)
    assert d == date(2026, 5, 21)


def test_parse_query_trade_date_hom_nay():
    d = fm.parse_query_trade_date("hôm nay thị trường thế nào")
    assert d == date.today()


def test_rank_symbols_by_volume_sorts_desc():
    trade_date = date(2026, 5, 21)

    def fake_hist(sym, td):
        vols = {"VIC": 1000, "VNM": 5000, "FPT": 2000}
        return {"symbol": sym, "totalVolume": vols.get(sym, 0), "priceClose": 10}

    with patch.object(fm, "fetch_historical_quote_day", side_effect=fake_hist):
        with patch.object(fm, "FIREANT_REQUEST_DELAY", 0):
            ranked = fm.rank_symbols_by_volume(["VIC", "VNM", "FPT"], trade_date, top_n=3)

    assert [r["symbol"] for r in ranked] == ["VNM", "FPT", "VIC"]


def test_extract_mbb_for_ngan_hang_quan_doi_leader_query():
    import script as s

    s.ENTITY_MAP = s._load_entity_map()
    eid, disp = s.extract_target_entity("Ngân hàng Quân Đội có ai là lãnh đạo cao nhất?")
    assert eid == "C_MBB", (eid, disp)
    assert "MBB" in disp or "Quân Đội" in disp


def test_collect_without_token_returns_empty():
    with patch.object(fm, "FIREANT_TOKEN", ""):
        steps = []
        lines, md = fm.collect_fireant_market_data(
            "công ty nào có khối lượng giao dịch cao nhất ngày hôm nay?",
            steps,
        )
    assert lines == []
    assert md == ""
    assert any("FIREANT_TOKEN" in s for s in steps)
