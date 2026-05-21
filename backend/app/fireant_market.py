"""
FireAnt REST — giá / KLGD cho câu hỏi thị trường (runtime query, không crawl batch).

Swagger: https://restv2.fireant.vn/swagger/docs/v1
  - GET /symbols/movers?topType=Actives
  - GET /symbols/{symbol}/historical-quotes?startDate=&endDate=
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from datetime import date
from typing import Any

import requests


def _normalize_query(text: str) -> str:
    t = unicodedata.normalize("NFD", str(text or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t.lower()).strip()

FIREANT_BASE_URL = os.getenv("FIREANT_BASE_URL", "https://restv2.fireant.vn").rstrip("/")
FIREANT_TOKEN = os.getenv("FIREANT_TOKEN", "").strip()
FIREANT_REQUEST_DELAY = float(os.getenv("FIREANT_REQUEST_DELAY", "0.12"))
FIREANT_MARKET_TIMEOUT = float(os.getenv("FIREANT_MARKET_TIMEOUT", "25"))
FIREANT_MARKET_MAX_SYMBOLS = int(os.getenv("FIREANT_MARKET_MAX_SYMBOLS", "35"))
FIREANT_MOVERS_COUNT = int(os.getenv("FIREANT_MOVERS_COUNT", "40"))

_HEADERS = {"Content-Type": "application/json"}
if FIREANT_TOKEN:
    _HEADERS["Authorization"] = f"Bearer {FIREANT_TOKEN}"

_DATE_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})")


def fireant_configured() -> bool:
    return bool(FIREANT_TOKEN)


def _iso_day_start(d: date) -> str:
    return f"{d.isoformat()}T00:00:00"


def _iso_day_end(d: date) -> str:
    return f"{d.isoformat()}T23:59:59"


def parse_query_trade_date(query_text: str, default_today: bool = True) -> date | None:
    """Lấy ngày giao dịch từ câu hỏi (dd/mm/yyyy) hoặc 'hôm nay'."""
    raw = str(query_text or "")
    m = _DATE_RE.search(raw)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    q = raw.lower()
    if "hom nay" in q or "ngay hom nay" in q:
        return date.today()
    return date.today() if default_today else None


def fireant_api_get(endpoint: str, params: dict[str, Any] | None = None) -> Any:
    if not FIREANT_TOKEN:
        return None
    url = f"{FIREANT_BASE_URL}/{endpoint.lstrip('/')}"
    try:
        resp = requests.get(
            url,
            headers=_HEADERS,
            params=params or {},
            timeout=FIREANT_MARKET_TIMEOUT,
        )
    except requests.RequestException as ex:
        print(f"[FireAnt] request error {endpoint}: {ex}")
        return None
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 401:
        print("[FireAnt] 401 Unauthorized — kiểm tra FIREANT_TOKEN")
    elif resp.status_code != 404:
        print(f"[FireAnt] HTTP {resp.status_code} for {endpoint}")
    return None


def _safe_list(data: Any) -> list:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "results", "items", "list"):
            val = data.get(key)
            if isinstance(val, list):
                return val
    return []


def fetch_top_actives(
    count: int | None = None,
    exchange: str = "",
    instrument_type: str = "stock",
) -> list[str]:
    """TOP cổ phiếu sôi động (Actives) — thường tương ứng thanh khoản cao."""
    params: dict[str, Any] = {
        "topType": "Actives",
        "count": count or FIREANT_MOVERS_COUNT,
        "type": instrument_type,
    }
    if exchange:
        params["exchange"] = exchange
    data = fireant_api_get("symbols/movers", params)
    symbols: list[str] = []
    for item in _safe_list(data):
        if isinstance(item, str) and item.strip():
            symbols.append(item.strip().upper())
        elif isinstance(item, dict):
            sym = item.get("symbol") or item.get("Symbol")
            if sym:
                symbols.append(str(sym).strip().upper())
    return symbols


def fetch_symbol_snapshot(symbol: str) -> dict[str, Any]:
    data = fireant_api_get(f"symbols/{symbol.upper()}")
    return data if isinstance(data, dict) else {}


def fetch_historical_quote_day(symbol: str, trade_date: date) -> dict[str, Any] | None:
    params = {
        "startDate": _iso_day_start(trade_date),
        "endDate": _iso_day_end(trade_date),
        "offset": 0,
        "limit": 5,
    }
    rows = _safe_list(fireant_api_get(f"symbols/{symbol.upper()}/historical-quotes", params))
    if not rows:
        return None
    row = rows[0] if isinstance(rows[0], dict) else None
    return row


def rank_symbols_by_volume(
    symbols: list[str],
    trade_date: date,
    top_n: int = 15,
) -> list[dict[str, Any]]:
    """Xếp hạng KLGD (totalVolume) theo historical-quotes từng mã."""
    ranked: list[dict[str, Any]] = []
    seen: set[str] = set()
    limit = min(len(symbols), FIREANT_MARKET_MAX_SYMBOLS)

    for sym in symbols[:limit]:
        s = sym.upper()
        if s in seen:
            continue
        seen.add(s)
        row = fetch_historical_quote_day(s, trade_date)
        if row:
            vol = row.get("totalVolume") or row.get("dealVolume") or 0
            try:
                vol_f = float(vol)
            except (TypeError, ValueError):
                vol_f = 0.0
            if vol_f > 0:
                ranked.append(
                    {
                        "symbol": s,
                        "totalVolume": vol_f,
                        "priceClose": row.get("priceClose"),
                        "priceChange": row.get("priceChange"),
                        "totalValue": row.get("totalValue"),
                    }
                )
        if FIREANT_REQUEST_DELAY > 0:
            time.sleep(FIREANT_REQUEST_DELAY)

    ranked.sort(key=lambda x: x["totalVolume"], reverse=True)
    return ranked[:top_n]


def _format_volume(n: float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f} triệu CP"
    if n >= 1_000:
        return f"{n / 1_000:.1f} nghìn CP"
    return f"{int(n)} CP"


def build_volume_context_lines(
    query_text: str,
    trade_date: date,
    top_n: int = 15,
) -> tuple[list[str], list[str]]:
    """
    Trả về (dòng context cho LLM, danh sách lỗi).
    """
    errors: list[str] = []
    lines: list[str] = []

    actives = fetch_top_actives()
    if not actives:
        errors.append("Không lấy được danh sách TOP Actives từ FireAnt.")
        return lines, errors

    ranked = rank_symbols_by_volume(actives, trade_date, top_n=top_n)
    if not ranked:
        errors.append(
            f"Không có bản ghi historical-quotes cho ngày {trade_date.isoformat()} "
            f"(có thể phiên chưa đóng, ngày nghỉ, hoặc token không đủ quyền)."
        )
        lines.append(
            f"--- FireAnt TOP Actives (chưa có KLGD theo ngày {trade_date.isoformat()}) ---"
        )
        for i, sym in enumerate(actives[:top_n], 1):
            lines.append(f"{i}. {sym}")
        return lines, errors

    lines.append(
        f"--- Top khối lượng giao dịch (FireAnt historical-quotes, ngày {trade_date.isoformat()}) ---"
    )
    for i, row in enumerate(ranked, 1):
        sym = row["symbol"]
        vol = _format_volume(row["totalVolume"])
        close = row.get("priceClose")
        extra = f", giá đóng cửa {close}" if close is not None else ""
        lines.append(f"{i}. {sym}: {vol}{extra}")
    return lines, errors


def format_fireant_markdown(lines: list[str], errors: list[str]) -> str:
    if not lines and not errors:
        return ""
    parts = ["", "## Dữ liệu thị trường (FireAnt API)", ""]
    if errors:
        parts.append("> " + " ".join(errors))
        parts.append("")
    if lines:
        parts.extend(lines)
    return "\n".join(parts)


def collect_fireant_market_data(query_text: str, steps: list[str]) -> tuple[list[str], str]:
    """
    Gọi FireAnt khi câu hỏi cần KLGD/giá; trả context + markdown phụ.
    """
    if not fireant_configured():
        steps.append("⚠️ FireAnt: chưa có FIREANT_TOKEN — bỏ qua API giá/KLGD.")
        return [], ""

    q_norm = _normalize_query(query_text)

    needs_volume = "khoi luong" in q_norm or "thanh khoan" in q_norm
    needs_price = "gia co phieu" in q_norm or "gia " in q_norm

    if not needs_volume and not needs_price:
        return [], ""

    trade_date = parse_query_trade_date(query_text)
    if not trade_date:
        steps.append("⚠️ FireAnt: không parse được ngày giao dịch.")
        return [], ""

    steps.append(f"📊 FireAnt: lấy dữ liệu thị trường cho ngày {trade_date.isoformat()}...")

    lines: list[str] = []
    errors: list[str] = []

    if needs_volume:
        vol_lines, vol_errs = build_volume_context_lines(query_text, trade_date)
        lines.extend(vol_lines)
        errors.extend(vol_errs)

    # Giá một mã cụ thể (A-Z 2-5 ký tự)
    sym_m = re.search(r"\b([A-Z]{2,5})\b", query_text or "")
    if needs_price and sym_m:
        sym = sym_m.group(1).upper()
        snap = fetch_symbol_snapshot(sym)
        if snap:
            name = snap.get("companyName") or snap.get("name") or sym
            price = snap.get("currentPrice") or snap.get("price")
            lines.append(f"--- Giá FireAnt ({sym}) ---")
            lines.append(f"{name} ({sym}): giá hiện tại {price}")
        else:
            row = fetch_historical_quote_day(sym, trade_date)
            if row and row.get("priceClose") is not None:
                lines.append(
                    f"{sym} ngày {trade_date.isoformat()}: đóng cửa {row.get('priceClose')}, "
                    f"KLGD {_format_volume(float(row.get('totalVolume') or 0))}"
                )

    if lines:
        steps.append(f"✅ FireAnt: đã nạp {len(lines)} dòng dữ liệu thị trường.")
    elif errors:
        steps.append("⚠️ FireAnt: " + errors[0][:120])

    return lines, format_fireant_markdown(lines, errors)
