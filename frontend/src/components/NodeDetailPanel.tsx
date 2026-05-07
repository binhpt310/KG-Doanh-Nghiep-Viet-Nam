import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import type { RefObject } from 'react';
import { vi } from '../content/copy/vi';
import { FieldValue } from '../utils/nodeDetailFormat';

interface Props {
  open: boolean;
  title: string;
  badge: 'company' | 'person' | 'institution';
  props: Record<string, unknown> | null;
  expandLabel: string;
  onExpand: () => void;
  onClose: () => void;
  /** Scrollable graph stage — used to clamp drag and place the panel at the top on open */
  boundsRef: RefObject<HTMLElement | null>;
}

export function NodeDetailPanel({
  open,
  title,
  badge,
  props,
  expandLabel,
  onExpand,
  onClose,
  boundsRef,
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ l: 16, t: 12 });
  const [wide, setWide] = useState(false);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    origL: number;
    origT: number;
  } | null>(null);

  const clampPos = useCallback(
    (l: number, t: number) => {
      const area = boundsRef.current;
      const panel = panelRef.current;
      if (!area || !panel) return { l, t };
      const ar = area.getBoundingClientRect();
      const pw = panel.offsetWidth;
      const ph = panel.offsetHeight;
      const maxL = Math.max(8, ar.width - pw - 8);
      const maxT = Math.max(8, ar.height - ph - 8);
      return {
        l: Math.min(maxL, Math.max(8, l)),
        t: Math.min(maxT, Math.max(8, t)),
      };
    },
    [boundsRef]
  );

  useLayoutEffect(() => {
    if (!open || !boundsRef.current || !panelRef.current) return;
    const ar = boundsRef.current.getBoundingClientRect();
    const w = panelRef.current.offsetWidth || 400;
    const l = Math.max(8, ar.width - w - 16);
    setPos(clampPos(l, 12));
  }, [open, title, boundsRef, clampPos]);

  useLayoutEffect(() => {
    if (!open || !boundsRef.current || !panelRef.current) return;
    setPos((p) => clampPos(p.l, p.t));
  }, [wide, open, boundsRef, clampPos]);

  useEffect(() => {
    if (!open) setWide(false);
  }, [open]);

  useEffect(() => {
    const onWin = () => {
      if (!open) return;
      setPos((p) => clampPos(p.l, p.t));
    };
    window.addEventListener('resize', onWin);
    return () => window.removeEventListener('resize', onWin);
  }, [open, clampPos]);

  const onDragPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      origL: pos.l,
      origT: pos.t,
    };
  };

  const onDragPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d || e.pointerId !== d.pointerId) return;
    const nl = d.origL + (e.clientX - d.startX);
    const nt = d.origT + (e.clientY - d.startY);
    setPos(clampPos(nl, nt));
  };

  const onDragPointerUp = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d || e.pointerId !== d.pointerId) return;
    dragRef.current = null;
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };

  if (!open) return null;

  const skip = new Set(['name', 'displayName', 'id', 'Chủ tịch HĐQT']);
  const entries = Object.entries(props ?? {}).filter(
    ([k, v]) => !skip.has(k) && v != null && v !== ''
  );

  return (
    <div
      ref={panelRef}
      className={`node-detail-panel ${wide ? 'node-detail-panel--wide' : ''}`}
      style={{ left: pos.l, top: pos.t, right: 'auto', bottom: 'auto' }}
    >
      <div
        className="ndp-top"
        onPointerDown={onDragPointerDown}
        onPointerMove={onDragPointerMove}
        onPointerUp={onDragPointerUp}
        onPointerCancel={onDragPointerUp}
      >
        <span className={`ndp-badge ${badge}`}>
          {badge === 'person'
            ? vi.badgePerson
            : badge === 'institution'
              ? vi.badgeInstitution
              : vi.badgeCompany}
        </span>
        <span className="ndp-drag-hint" aria-hidden>
          ⋮⋮
        </span>
        <button
          type="button"
          className="ndp-x"
          onClick={onClose}
          onPointerDown={(e) => e.stopPropagation()}
        >
          ×
        </button>
      </div>
      <div className="ndp-title">{title}</div>
      {props && props['Chủ tịch HĐQT'] != null && String(props['Chủ tịch HĐQT']) !== '' ? (
        <div className="ndp-field accent">
          <span className="k">Chủ tịch HĐQT</span>
          <span className="v">{String(props['Chủ tịch HĐQT'])}</span>
        </div>
      ) : null}
      <div className="ndp-fields">
        {entries.map(([k, val]) => (
          <div key={k} className="ndp-field">
            <span className="k">{k}</span>
            <span className="v">
              <FieldValue k={k} val={val} />
            </span>
          </div>
        ))}
      </div>
      <div className="ndp-actions">
        <button
          type="button"
          className="ndp-widen"
          onClick={() => setWide((w) => !w)}
        >
          {wide ? vi.nodeDetailNarrow : vi.nodeDetailWiden}
        </button>
        <button type="button" className="ndp-expand" onClick={onExpand}>
          {expandLabel}
        </button>
      </div>
    </div>
  );
}
