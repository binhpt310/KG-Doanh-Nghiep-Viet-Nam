import { DataSet } from 'vis-data';
import type { Edge as VisEdge, Node as VisNode } from 'vis-network';
import type { ApiEdge, ApiNode, GraphMode, GraphStoreState } from './types';

/**
 * vis-network options — mirrors legacy index.html, theme from React state (not document alone).
 */
export function getVisOptions(
  mode: 'hubs' | 'persons',
  theme: 'dark' | 'light'
) {
  const isDark = theme === 'dark';
  const tx = isDark ? '#EEF5FF' : '#132238';
  const edgeC = isDark ? 'rgba(160,190,230,0.55)' : 'rgba(55,78,110,0.55)';
  const isPersonMode = mode === 'persons';

  return {
    nodes: {
      shape: 'dot' as const,
      size: 18,
      font: {
        size: isPersonMode ? 17 : 19,
        face: "'Manrope', 'Inter', Arial, sans-serif",
        color: tx,
        strokeWidth: isPersonMode ? 4 : 5,
        strokeColor: isDark ? '#08111F' : '#FFFFFF',
        background: isDark ? 'rgba(8,17,31,0.92)' : 'rgba(255,255,255,0.94)',
        align: 'center' as const,
      },
      scaling: {
        min: 11,
        max: 46,
        label: { enabled: true, min: 14, max: 34 },
      },
      borderWidth: 2.5,
      borderWidthSelected: 5,
      shadow: {
        enabled: true,
        color: isDark ? 'rgba(7, 18, 31, 0.42)' : 'rgba(54,74,101,0.16)',
        size: 10,
        x: 0,
        y: 4,
      },
    },
    edges: {
      width: 2.4,
      color: { color: edgeC, highlight: '#7EC8FF', hover: '#5FD6A0' },
      arrows: { to: { enabled: true, scaleFactor: 0.58 } },
      smooth: { enabled: true, type: 'continuous', roundness: 0.2 },
      font: {
        size: 13,
        face: "'IBM Plex Mono', 'Inter', Arial, sans-serif",
        color: tx,
        align: 'middle',
        strokeWidth: isDark ? 3 : 4,
        strokeColor: isDark ? '#050d18' : '#ffffff',
      },
      hoverWidth: 3.2,
      selectionWidth: 3.6,
      dashes: false,
    },
    groups: {
      Company: { color: { background: '#78BEFF', border: '#4A97E8' }, size: 20 },
      Person: { color: { background: '#59D68C', border: '#2FA56B' }, size: 14 },
      Institution: { color: { background: '#F2BB69', border: '#D48D2C' }, size: 17 },
      DEFAULT: { color: { background: '#73849B', border: '#4E6179' }, size: 11 },
    },
    physics: {
      enabled: true,
      solver: 'barnesHut',
      barnesHut: {
        gravitationalConstant: isPersonMode ? -12000 : -5000,
        centralGravity: isPersonMode ? 0.03 : 0.03,
        springLength: isPersonMode ? 220 : 460,
        springConstant: 0.03,
        damping: 0.12,
      },
      maxVelocity: 100,
      minVelocity: 0.5,
      stabilization: {
        enabled: true,
        iterations: isPersonMode ? 400 : 380,
        fit: true,
        updateInterval: 20,
      },
    },
    interaction: {
      hover: true,
      tooltipDelay: 150,
      hideEdgesOnDrag: true,
      hideNodesOnDrag: false,
      multiselect: false,
      zoomSpeed: 0.8,
    },
    layout: { improvedLayout: false },
  };
}

export function seedPosition(index: number, total: number, radius: number) {
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  const angle = index * goldenAngle;
  const r = radius * Math.sqrt(index / Math.max(total, 1));
  return { x: r * Math.cos(angle), y: r * Math.sin(angle) };
}

export function nodeToVis(
  n: ApiNode,
  degree: number,
  index: number,
  total: number,
  mode: GraphMode,
  store: GraphStoreState
): VisNode {
  const group = ['Company', 'Person', 'Institution'].includes(n.group || '')
    ? (n.group as string)
    : 'DEFAULT';
  const maxDeg = store.maxDeg || 1;
  const normDeg =
    degree > 0 ? Math.log(1 + degree) / Math.log(1 + maxDeg) : 0;
  let size = 10 + normDeg * 28;
  if (mode === 'persons') size = 8 + normDeg * 16;
  size = Math.min(42, Math.max(7, size));

  const obj: VisNode = {
    id: n.id,
    label: n.label || n.name || String(n.id),
    group,
    size,
    title: `${n.label || n.name || String(n.id)}\nLiên kết: ${degree || 0}`,
  };

  if (total > 1) {
    const radius = Math.max(2000, total * 6);
    const pos = seedPosition(index || 0, total, radius);
    obj.x = pos.x;
    obj.y = pos.y;
    obj.fixed = false;
  }

  return obj;
}

const RULE_COLORS: Record<string, string> = {
  R01: '#FF00FF',
  R02: '#00FFFF',
  R03_LOW: '#00FF00',
  R03_MEDIUM: '#FFFF00',
  R03_HIGH: '#FF0000',
  R04: '#B388FF',
};

export function edgeToVis(e: ApiEdge): VisEdge {
  let ruleId = e.inferred_from || '';
  if (ruleId === 'R03') {
    const level = (e.influence_level || '').toUpperCase();
    ruleId = `R03_${level}`;
  }
  const neonColor = RULE_COLORS[ruleId];

  const from = e.from || e.source || '';
  const to = e.to || e.target || '';
  const obj: VisEdge = {
    id: edgePairKey(from, to),
    from,
    to,
    label: e.label || e.edge_label || '',
    dashes: !!(e.inferred || e.dashes),
  };

  if (e.inferred || e.dashes) {
    obj.color = {
      color: neonColor || '#F0B429',
      highlight: neonColor || '#FFD36E',
      hover: neonColor || '#FFD36E',
    };
    obj.width = 3;
    obj.dashes = true;
    if (neonColor) {
      obj.shadow = { enabled: true, color: neonColor, size: 10, x: 0, y: 0 };
    }
  }
  return obj;
}

function edgeIdentity(e: ApiEdge): string {
  return `${e.from || e.source || ''}→${e.to || e.target || ''}:${e.label || e.edge_label || ''}`;
}

/** Khóa không phân hướng — một cặp nút chỉ một cạnh trên UI. */
export function edgePairKey(from: string, to: string): string {
  return from < to ? `${from}|${to}` : `${to}|${from}`;
}

const EDGE_TYPE_PRIORITY: Record<string, number> = {
  LÃNH_ĐẠO_CAO_NHẤT: 100,
  CHỦ_TỊCH_HĐQT: 95,
  TỔNG_GIÁM_ĐỐC: 90,
  PHÓ_TỔNG_GIÁM_ĐỐC: 85,
  LÀ_CỔ_ĐÔNG_CỦA: 70,
  LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO: 60,
  VỢ_CHỒNG: 55,
  ANH_CHỊ: 54,
  CÓ_CÔNG_TY_CON: 50,
  LÀ_CÔNG_TY_CON_CỦA: 45,
};

function edgeEndpoints(e: ApiEdge): [string, string] | null {
  const from = e.from || e.source || '';
  const to = e.to || e.target || '';
  if (!from || !to || from === to) return null;
  return [from, to];
}

function edgePriority(e: ApiEdge): number {
  const label = String(e.label || e.edge_label || '').trim();
  if (EDGE_TYPE_PRIORITY[label] != null) return EDGE_TYPE_PRIORITY[label];
  if (e.inferred || e.dashes) return 25;
  return 40;
}

/** Ưu tiên hướng Cá nhân → Công ty khi có cạnh 2 chiều. */
function normalizeEdgeDirection(e: ApiEdge): ApiEdge {
  const from = e.from || e.source || '';
  const to = e.to || e.target || '';
  if (from.startsWith('P_') && to.startsWith('C_')) {
    return { ...e, from, to, source: from, target: to };
  }
  if (from.startsWith('C_') && to.startsWith('P_')) {
    return { ...e, from: to, to: from, source: to, target: from };
  }
  return { ...e, from, to, source: from, target: to };
}

function compareEdgeKeep(a: ApiEdge, b: ApiEdge): number {
  const pa = edgePriority(a);
  const pb = edgePriority(b);
  if (pa !== pb) return pa - pb;
  const ia = a.inferred || a.dashes ? 1 : 0;
  const ib = b.inferred || b.dashes ? 1 : 0;
  return ia - ib;
}

/** Gộp mọi quan hệ giữa cùng 2 nút (2 chiều hoặc nhiều nhãn) thành một cạnh. */
export function collapseEdgePairs(edges: ApiEdge[]): ApiEdge[] {
  const byPair: Record<string, ApiEdge> = {};
  (edges || []).forEach((e) => {
    const ep = edgeEndpoints(e);
    if (!ep) return;
    const [from, to] = ep;
    const pk = edgePairKey(from, to);
    const cand = normalizeEdgeDirection(e);
    const cur = byPair[pk];
    if (!cur || compareEdgeKeep(cand, cur) > 0) {
      byPair[pk] = cand;
    }
  });
  return Object.values(byPair);
}

export function dedupeGraphPayload(nodes: ApiNode[], edges: ApiEdge[]) {
  const nodeSeen: Record<string, boolean> = {};
  const edgeSeen: Record<string, boolean> = {};
  const cleanNodes: ApiNode[] = [];
  const cleanEdges: ApiEdge[] = [];

  (nodes || []).forEach((n) => {
    if (!n?.id || nodeSeen[n.id]) return;
    nodeSeen[n.id] = true;
    cleanNodes.push(n);
  });

  (edges || []).forEach((e) => {
    const id = edgeIdentity(e);
    if (!id || edgeSeen[id]) return;
    edgeSeen[id] = true;
    cleanEdges.push(e);
  });

  return { nodes: cleanNodes, edges: collapseEdgePairs(cleanEdges) };
}

export function computeDegrees(edges: ApiEdge[]): Record<string, number> {
  const dm: Record<string, number> = {};
  edges.forEach((e) => {
    const s = e.from || e.source;
    const t = e.to || e.target;
    if (s) dm[s] = (dm[s] || 0) + 1;
    if (t) dm[t] = (dm[t] || 0) + 1;
  });
  return dm;
}

export function makeVisDataSets(nodes: VisNode[], edges: VisEdge[]) {
  return {
    nodes: new DataSet<VisNode>(nodes),
    edges: new DataSet<VisEdge>(edges),
  };
}
