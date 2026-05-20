/**
 * API client — same-origin `/api/*` (Vite proxy in dev, Nginx in Docker).
 */
const DEFAULT_HEADERS: HeadersInit = {
  'ngrok-skip-browser-warning': 'skip',
};

export async function apiJson<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: {
      ...DEFAULT_HEADERS,
      ...(init?.headers || {}),
    },
  });
  if (!r.ok) {
    const t = await r.text().catch(() => '');
    if (r.status === 524) {
      throw new Error(
        'HTTP 524: Hết thời gian chờ proxy (thường ~100s). Thử tắt Reasoning trong panel chat, hoặc tăng timeout Cloudflare/nginx; kiểm tra LLM có phản hồi nhanh (LLM_DISABLE_THINKING=true).'
      );
    }
    throw new Error(`HTTP ${r.status}${t ? `: ${t.slice(0, 200)}` : ''}`);
  }
  return r.json() as Promise<T>;
}

export async function apiPostJson<T>(
  path: string,
  body: unknown,
  init?: RequestInit
): Promise<T> {
  return apiJson<T>(path, {
    ...init,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    body: JSON.stringify(body),
  });
}
