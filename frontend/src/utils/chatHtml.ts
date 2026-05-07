import DOMPurify from 'dompurify';
import { marked } from 'marked';

/**
 * Renders markdown to HTML, sanitizes, then marks http(s) links to open in a new tab.
 * No global DOMPurify hooks — safe for other callers in the app.
 */
export function markdownToSafeChatHtml(markdown: string): string {
  const raw = marked.parse(markdown, { async: false }) as string;
  const clean = DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
  const doc = new DOMParser().parseFromString(`<div class="chat-html-root">${clean}</div>`, 'text/html');
  const root = doc.body.querySelector('.chat-html-root');
  if (!root) return clean;
  root.querySelectorAll('a[href]').forEach((el) => {
    const href = el.getAttribute('href') || '';
    if (/^https?:\/\//i.test(href)) {
      el.setAttribute('target', '_blank');
      el.setAttribute('rel', 'noopener noreferrer');
    }
  });
  return DOMPurify.sanitize(root.innerHTML, {
    USE_PROFILES: { html: true },
    ADD_ATTR: ['target', 'rel'],
  });
}
