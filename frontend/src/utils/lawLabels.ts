/** Hiển thị luật suy luận (đồng bộ với `_LAW_DISPLAY_BY_RULE_ID` trong script.py). */
const LAW_DISPLAY_BY_RULE_ID: Record<string, string> = {
  R01: 'Luật 1 — Gộp sở hữu vợ chồng',
  R02: 'Luật 2 — Sở hữu gián tiếp qua công ty con',
  R03: 'Luật 3 — Ảnh hưởng gián tiếp theo ngưỡng 5/25/50',
  R04: 'Luật 4 — Liên kết qua cùng cổ đông lớn',
};

const R03_INFERRED_EDGE_TYPES = new Set([
  'CÓ_LỢI_ÍCH_GIÁN_TIẾP',
  'ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI',
  'KIỂM_SOÁT_GIÁN_TIẾP',
]);

/** Bản tiếng Việt cho giá trị lưu trong DB: LOW | MEDIUM | HIGH */
export function influenceLevelVi(level?: string | null): string {
  const u = (level || '').trim().toUpperCase();
  if (u === 'LOW') return 'Thấp';
  if (u === 'MEDIUM') return 'Trung bình';
  if (u === 'HIGH') return 'Cao';
  if (u === 'NONE') return 'dưới ngưỡng';
  return level || '—';
}

/** Một tên hiển thị cho cả ba loại cạnh R03 (Luật 3); các luật khác map ngắn gọn. */
export function relationLabelVi(
  relation?: string | null,
  rule?: string | null
): string {
  const r = (relation || '').trim();
  const rid = (rule || '').trim();
  if (rid === 'R03' && R03_INFERRED_EDGE_TYPES.has(r)) return 'Ảnh hưởng gián tiếp';
  if (r === 'KIỂM_SOÁT_GIA_ĐÌNH') return 'Kiểm soát gia đình';
  if (r === 'SỞ_HỮU_GIÁN_TIẾP') return 'Sở hữu gián tiếp';
  if (r === 'CÙNG_CỔ_ĐÔNG_LỚN') return 'Cùng cổ đông lớn';
  return r || '—';
}

export function lawDisplay(ruleId?: string | null): string {
  const rid = (ruleId || '').trim();
  if (LAW_DISPLAY_BY_RULE_ID[rid]) return LAW_DISPLAY_BY_RULE_ID[rid];
  return rid ? `Luật (${rid})` : 'Luật (không xác định)';
}
