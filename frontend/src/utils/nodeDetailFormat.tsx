/**
 * Render node property values — shareholder tables match backend line format.
 */
export function parseShareholderLine(line: string): {
  name: string;
  sharesRaw: string;
  pct: string;
} | null {
  const m = String(line || '')
    .trim()
    .match(/^(.+?):\s*([\d,]+)\s*cổ phiếu(?:\s*\(([\d.]+)%\s*vốn\))?\s*$/i);
  if (!m) return null;
  return {
    name: m[1].trim(),
    sharesRaw: String(m[2]).replace(/,/g, ''),
    pct: m[3] != null ? m[3] : '',
  };
}

export function ShareholderTable({
  fieldKey,
  val,
}: {
  fieldKey: string;
  val: unknown;
}) {
  if (
    fieldKey !== 'Top cổ đông (số cổ phiếu)' &&
    fieldKey !== 'Số cổ phiếu nắm giữ (theo công ty)'
  ) {
    return null;
  }
  const lines = String(val)
    .split(/\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const rows = lines
    .map(parseShareholderLine)
    .filter(
      (r): r is NonNullable<ReturnType<typeof parseShareholderLine>> =>
        r != null
    );
  if (!rows.length) return null;

  const col1 =
    fieldKey === 'Số cổ phiếu nắm giữ (theo công ty)' ? 'Công ty' : 'Tên cổ đông';

  return (
    <div className="ndp-table-wrap">
      <table className="ndp-share-table">
        <thead>
          <tr>
            <th>{col1}</th>
            <th>Số cổ phiếu</th>
            <th>% vốn</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const shNum = parseInt(r.sharesRaw, 10);
            const shDisp = Number.isNaN(shNum)
              ? r.sharesRaw
              : shNum.toLocaleString('vi-VN');
            return (
              <tr key={r.name + r.sharesRaw}>
                <td>{r.name}</td>
                <td className="num">{shDisp}</td>
                <td className="num">{r.pct === '' ? '—' : `${r.pct}%`}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function FieldValue({
  k,
  val,
}: {
  k: string;
  val: unknown;
}) {
  const tbl = <ShareholderTable fieldKey={k} val={val} />;
  if (tbl) return tbl;

  const s = String(val);
  if (s.length < 100) return <>{s}</>;

  let split = s.replace(/\)\s+(?=[A-Za-zÀ-ỹ])/g, ')\n');
  if (!split.includes('\n')) split = s.replace(/\s+(?=\d+\.\s)/g, '\n');
  if (!split.includes('\n')) return <>{s}</>;

  const lines = split
    .split('\n')
    .map((x) => x.trim())
    .filter(Boolean);
  if (lines.length <= 1) return <>{s}</>;

  return (
    <>
      {lines.map((line) => (
        <div key={line.slice(0, 40)} className="ndp-line">
          {line}
        </div>
      ))}
    </>
  );
}
