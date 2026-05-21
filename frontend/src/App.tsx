import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from 'react';
import './App.css';
import { apiJson, apiPostJson } from './api/client';
import { AssistantPanel } from './components/AssistantPanel';
import { LeftRail, type RuleRow } from './components/LeftRail';
import { NodeDetailPanel } from './components/NodeDetailPanel';
import { TopBar } from './components/TopBar';
import { vi } from './content/copy/vi';
import { useKgGraph } from './graph/useKgGraph';
import type { ApiEdge, ApiNode } from './graph/types';
import { lawDisplay, influenceLevelVi, relationLabelVi } from './utils/lawLabels';

/** Mirrors `/api/stats` JSON shape used across dashboard chips */
interface StatsPayload {
  total_nodes: number;
  total_edges: number;
  companies: number;
  persons: number;
  inferred_relationships: number;
  inferred_hidden_edges_raw?: number;
}

/** Row shape from GET /api/inferred-relations */
interface InferredRelationRow {
  source: string;
  source_name?: string | null;
  source_type?: string | null;
  target: string;
  target_name?: string | null;
  target_type?: string | null;
  relation?: string | null;
  ownership?: number | null;
  level?: string | null;
  rule?: string | null;
}

interface HiddenRelationContextPayload {
  summary?: string;
  explanation_lines?: string[];
  graph?: {
    nodes: ApiNode[];
    edges: ApiEdge[];
  };
}

function entityGroupFromRow(
  id: string,
  typ?: string | null
): 'Company' | 'Person' | 'Institution' | 'DEFAULT' {
  const t = (typ || '').trim();
  if (t === 'Company' || t === 'Person' || t === 'Institution') return t;
  if (id.startsWith('P_')) return 'Person';
  if (id.startsWith('C_')) return 'Company';
  return 'DEFAULT';
}

function buildGraphFromInferredRows(rows: InferredRelationRow[]): {
  nodes: ApiNode[];
  edges: ApiEdge[];
} {
  const nodeMap = new Map<string, ApiNode>();
  const edges: ApiEdge[] = [];
  for (const row of rows) {
    const sid = row.source;
    const tid = row.target;
    if (!sid || !tid) continue;
    const sl = row.source_name || sid;
    const tl = row.target_name || tid;
    const sg = entityGroupFromRow(sid, row.source_type);
    const tg = entityGroupFromRow(tid, row.target_type);
    if (!nodeMap.has(sid)) {
      nodeMap.set(sid, { id: sid, label: sl, name: sl, group: sg });
    }
    if (!nodeMap.has(tid)) {
      nodeMap.set(tid, { id: tid, label: tl, name: tl, group: tg });
    }
    edges.push({
      from: sid,
      to: tid,
      label: relationLabelVi(row.relation, row.rule) || '',
      inferred: true,
      dashes: true,
      inferred_from: row.rule || '',
      influence_level: row.level || undefined,
    });
  }
  return { nodes: Array.from(nodeMap.values()), edges };
}

function hiddenRowKey(row: InferredRelationRow) {
  return `${row.source}|${row.target}|${row.relation || ''}|${row.rule || ''}`;
}

const LS_LEFT = 'kg_panel_left_w';
const LS_RIGHT = 'kg_panel_right_w';

function readWidth(key: string, fallback: number, min: number, max: number) {
  try {
    const v = parseInt(localStorage.getItem(key) || '', 10);
    if (!Number.isNaN(v) && v >= min && v <= max) return v;
  } catch {
    /* ignore */
  }
  return fallback;
}

export default function App() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    try {
      const s = localStorage.getItem('theme');
      if (s === 'light' || s === 'dark') return s;
    } catch {
      /* ignore */
    }
    return window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const [, bumpGraph] = useReducer((x: number) => x + 1, 0);

  const [stats, setStats] = useState<StatsPayload | null>(null);

  const [lastSync, setLastSync] = useState('—');
  const [exchange, setExchange] = useState<{
    breakdown: { exchange: string; count: number }[];
    total: number;
  } | null>(null);
  const [rules, setRules] = useState<RuleRow[] | null>(null);
  const [topCriteria, setTopCriteria] = useState('degree');
  const [topEntities, setTopEntities] = useState<
    { id: string; name: string; value: number | string }[] | null
  >(null);

  const [cmdMode, setCmdMode] = useState<
    'companies' | 'persons' | 'query' | 'inferred'
  >('companies');
  const [filterMode, setFilterMode] = useState<'companies' | 'persons'>(
    'companies'
  );

  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);

  const [leftW, setLeftW] = useState(() =>
    readWidth(LS_LEFT, 340, 260, 560)
  );
  const [rightW, setRightW] = useState(() =>
    readWidth(LS_RIGHT, 380, 300, 560)
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [nodeProps, setNodeProps] = useState<Record<string, unknown> | null>(
    null
  );

  const [qOpen, setQOpen] = useState(false);
  const [qCollapsed, setQCollapsed] = useState(false);
  const [qSteps, setQSteps] = useState<string[]>([]);
  const [qCypher, setQCypher] = useState('');

  const [hiddenPopupOpen, setHiddenPopupOpen] = useState(false);
  const [hiddenRows, setHiddenRows] = useState<InferredRelationRow[]>([]);
  const [hiddenExpandKey, setHiddenExpandKey] = useState<string | null>(null);
  const [hiddenContextByKey, setHiddenContextByKey] = useState<
    Record<
      string,
      {
        loading?: boolean;
        summary?: string;
        explanationLines?: string[];
        graph?: { nodes: ApiNode[]; edges: ApiEdge[] };
        error?: string;
      }
    >
  >({});

  const [crawlBusy, setCrawlBusy] = useState(false);
  const [crawlPct, setCrawlPct] = useState(0);
  const crawlTimer = useRef<number | null>(null);

  const graphHostRef = useRef<HTMLDivElement>(null);
  const graphAreaRef = useRef<HTMLElement>(null);

  const onKpiUpdate = useCallback((nodeCount: number, edgeCount: number) => {
    void nodeCount;
    void edgeCount;
  }, []);

  const onGraphModeLabels = useCallback(
    (mode: 'companies' | 'persons' | 'query' | 'inferred') => {
      setCmdMode(mode);
      if (mode === 'companies') setFilterMode('companies');
      if (mode === 'persons') setFilterMode('persons');
    },
    []
  );

  const graph = useKgGraph(graphHostRef, {
    theme,
    onKpiUpdate,
    onGraphModeLabels,
    onGraphMutation: bumpGraph,
  });

  useEffect(() => {
    graph.updateTheme();
  }, [graph, theme]);

  /** Only auto-load the company hub graph once; `graph` identity changes on theme/hook churn. */
  const initialHubLoadDone = useRef(false);
  useEffect(() => {
    if (initialHubLoadDone.current) return;
    initialHubLoadDone.current = true;
    void graph.loadHubsOnly().catch(console.error);
  }, [graph]);

  useEffect(() => {
    apiJson<StatsPayload>('/api/stats')
      .then(setStats)
      .catch(() => setStats(null));
    apiJson<{ breakdown: { exchange: string; count: number }[]; total: number }>(
      '/api/stats/exchange'
    )
      .then(setExchange)
      .catch(() => setExchange(null));
    apiJson<RuleRow[]>('/api/rules')
      .then(setRules)
      .catch(() => setRules(null));
  }, []);

  useEffect(() => {
    apiJson<{ id: string; name: string; value: number }[]>(
      `/api/stats/top?criteria=${encodeURIComponent(topCriteria)}`
    )
      .then((rows) => {
        setTopEntities(
          rows.map((r) => ({
            id: r.id,
            name: r.name || r.id,
            value: r.value,
          }))
        );
      })
      .catch(() => setTopEntities([]));
  }, [topCriteria]);

  useEffect(() => {
    apiJson<{ running?: boolean; last_success?: { completed_at?: string } }>(
      '/api/crawl/progress'
    )
      .then((d) => {
        const dt = d.last_success?.completed_at;
        setLastSync(dt ? new Date(dt).toLocaleString('vi-VN') : '—');
      })
      .catch(() => {});
  }, []);

  const fetchNodeDetail = useCallback(async (id: string) => {
    try {
      const d = await apiJson<{ props?: Record<string, unknown> }>(
        `/api/node/${encodeURIComponent(id)}`
      );
      setSelectedId(id);
      setNodeProps(d.props || null);
    } catch {
      setSelectedId(id);
      setNodeProps(null);
    }
  }, []);

  useEffect(() => {
    const onClick = (e: Event) => {
      const ce = e as CustomEvent<string>;
      const id = ce.detail;
      void fetchNodeDetail(id);
      if (filterMode === 'persons' && id.startsWith('P_')) {
        void graph.expandOrToggleNeighbors(id);
      }
    };
    const onClose = () => {
      setSelectedId(null);
      setNodeProps(null);
    };
    const onSearchPick = (e: Event) => {
      const ce = e as CustomEvent<string>;
      void fetchNodeDetail(ce.detail);
      graph.selectNodes([ce.detail]);
      graph.focusNode(ce.detail);
    };
    const onQueryUi = (e: Event) => {
      const ce = e as CustomEvent<{ steps?: string[]; cypher?: string }>;
      setQSteps(ce.detail.steps || []);
      setQCypher(ce.detail.cypher || '');
      setQOpen(!!((ce.detail.steps?.length || 0) || ce.detail.cypher));
      setQCollapsed(false);
    };
    window.addEventListener('kg-search-pick', onSearchPick);
    window.addEventListener('kg-node-click', onClick);
    window.addEventListener('kg-node-close', onClose);
    window.addEventListener('kg-query-ui', onQueryUi);
    return () => {
      window.removeEventListener('kg-search-pick', onSearchPick);
      window.removeEventListener('kg-node-click', onClick);
      window.removeEventListener('kg-node-close', onClose);
      window.removeEventListener('kg-query-ui', onQueryUi);
    };
  }, [fetchNodeDetail, graph, filterMode]);

  const badgeType = useMemo(() => {
    if (!nodeProps) return 'company' as const;
    const t = String(nodeProps.type || '');
    if (t === 'Person' || selectedId?.startsWith('P_')) return 'person';
    if (t === 'Institution') return 'institution';
    return 'company';
  }, [nodeProps, selectedId]);

  const heroMetrics = useMemo(() => {
    const fmt = (x: number | null | undefined) =>
      x != null ? x.toLocaleString('vi-VN') : '—';
    return {
      entities: fmt(stats?.total_nodes),
      links: fmt(stats?.total_edges),
      hidden: fmt(stats?.inferred_relationships),
    };
  }, [stats]);

  const cmdLabels = useMemo(() => {
    if (cmdMode === 'persons')
      return { mode: vi.modeLabelPersons, alert: vi.alertPersons };
    if (cmdMode === 'query')
      return { mode: vi.modeLabelQuery, alert: vi.alertQuery };
    if (cmdMode === 'inferred')
      return { mode: vi.modeLabelInferred, alert: vi.alertInferred };
    return { mode: vi.modeLabelCompanies, alert: vi.alertCompanies };
  }, [cmdMode]);

  const ruleById = useMemo(() => {
    const m = new Map<string, RuleRow>();
    for (const r of rules || []) {
      if (r.id) m.set(r.id, r);
    }
    return m;
  }, [rules]);

  const loadHiddenRowContext = useCallback(
    async (row: InferredRelationRow) => {
      const rk = hiddenRowKey(row);
      const cached = hiddenContextByKey[rk];
      if (cached?.graph && cached?.explanationLines?.length) return cached;
      if (cached?.loading) return cached;

      setHiddenContextByKey((prev) => ({
        ...prev,
        [rk]: {
          ...prev[rk],
          loading: true,
          error: undefined,
        },
      }));

      try {
        const params = new URLSearchParams({
          source: row.source,
          target: row.target,
        });
        if (row.rule) params.set('rule', row.rule);
        if (row.relation) params.set('relation', row.relation);

        const data = await apiJson<HiddenRelationContextPayload>(
          `/api/inferred-relations/context?${params.toString()}`
        );
        const next = {
          loading: false,
          summary: data.summary || '',
          explanationLines: data.explanation_lines || [],
          graph: data.graph || buildGraphFromInferredRows([row]),
          error: undefined,
        };
        setHiddenContextByKey((prev) => ({ ...prev, [rk]: next }));
        return next;
      } catch (error) {
        const fallback = {
          loading: false,
          summary: '',
          explanationLines: [],
          graph: buildGraphFromInferredRows([row]),
          error:
            error instanceof Error ? error.message : vi.hiddenRelationsLoadError,
        };
        setHiddenContextByKey((prev) => ({ ...prev, [rk]: fallback }));
        return fallback;
      }
    },
    [hiddenContextByKey]
  );

  const handleToggleHiddenRow = useCallback(
    (row: InferredRelationRow) => {
      const rk = hiddenRowKey(row);
      setHiddenExpandKey((cur) => {
        const next = cur === rk ? null : rk;
        if (next) void loadHiddenRowContext(row);
        return next;
      });
    },
    [loadHiddenRowContext]
  );

  const handleFocusHiddenRelation = useCallback(
    async (row: InferredRelationRow) => {
      const rk = hiddenRowKey(row);
      setHiddenExpandKey(rk);
      const ctx = await loadHiddenRowContext(row);
      const fallback = buildGraphFromInferredRows([row]);
      const nodes = ctx?.graph?.nodes?.length ? ctx.graph.nodes : fallback.nodes;
      const edges = ctx?.graph?.edges?.length ? ctx.graph.edges : fallback.edges;
      if (nodes.length && edges.length) {
        graph.loadInferredGraph(nodes, edges);
      }
    },
    [graph, loadHiddenRowContext]
  );

  const handleOpenHiddenRelations = useCallback(async () => {
    try {
      const data = await apiJson<{
        relations: InferredRelationRow[];
        graph?: { nodes: ApiNode[]; edges: ApiEdge[] };
      }>('/api/inferred-relations?limit=5000');
      const rels = data.relations || [];
      setHiddenRows(rels);
      setHiddenExpandKey(null);
      setHiddenContextByKey({});
      let nodes = data.graph?.nodes ?? [];
      let edges = data.graph?.edges ?? [];
      if (!nodes.length || !edges.length) {
        const built = buildGraphFromInferredRows(rels);
        nodes = built.nodes;
        edges = built.edges;
      }
      if (nodes.length && edges.length) {
        graph.loadInferredGraph(nodes, edges);
      }
      setHiddenPopupOpen(true);
    } catch (e) {
      console.error(e);
      setHiddenRows([]);
      setHiddenPopupOpen(true);
    }
  }, [graph]);

  const startCrawl = async () => {
    if (crawlBusy) return;
    setCrawlBusy(true);
    setCrawlPct(10);
    try {
      await apiPostJson('/api/crawl/start', {});
      crawlTimer.current = window.setInterval(async () => {
        try {
          const d = await apiJson<{
            running: boolean;
            message?: string;
            error?: string;
          }>('/api/crawl/progress');
          setCrawlPct((p) => Math.min(92, p + 3));
          if (!d.running) {
            if (crawlTimer.current) window.clearInterval(crawlTimer.current);
            setCrawlPct(100);
            setCrawlBusy(false);
            await graph.loadHubsOnly();
            const s = await apiJson<StatsPayload>('/api/stats');
            setStats(s);
            apiJson<{
              running: boolean;
              last_success?: { completed_at?: string };
            }>('/api/crawl/progress').then((cp) => {
              const dt = cp.last_success?.completed_at;
              setLastSync(dt ? new Date(dt).toLocaleString('vi-VN') : '—');
            });
            setTimeout(() => setCrawlPct(0), 900);
          }
        } catch {
          /* ignore */
        }
      }, 2000);
    } catch {
      setCrawlBusy(false);
      setCrawlPct(0);
    }
  };

  /* Panel resize: state drives listeners so the handle gets an active style while dragging */
  const [resizeEdge, setResizeEdge] = useState<'left' | 'right' | null>(null);

  useEffect(() => {
    if (!resizeEdge) return;
    const onMove = (e: MouseEvent) => {
      if (resizeEdge === 'left') {
        const nw = Math.min(560, Math.max(260, e.clientX));
        setLeftW(nw);
        localStorage.setItem(LS_LEFT, String(nw));
      } else {
        const nw = Math.min(
          560,
          Math.max(300, window.innerWidth - e.clientX)
        );
        setRightW(nw);
        localStorage.setItem(LS_RIGHT, String(nw));
      }
      graph.fitView();
    };
    const onUp = () => {
      setResizeEdge(null);
      document.body.classList.remove('resizing');
    };
    document.body.classList.add('resizing');
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      document.body.classList.remove('resizing');
    };
  }, [resizeEdge, graph]);

  const expandLabel =
    selectedId && graph.isNodeExpanded(selectedId)
      ? vi.nodeDetailCollapse
      : vi.nodeDetailExpand;

  return (
    <div id="app">
      <TopBar
        theme={theme}
        onToggleTheme={() =>
          setTheme((t) => (t === 'dark' ? 'light' : 'dark'))
        }
        onCrawl={startCrawl}
        crawlBusy={crawlBusy}
        heroMetrics={heroMetrics}
      />

      <div className="crawl-bar" style={{ display: crawlPct ? 'block' : 'none' }}>
        <div className="crawl-fill" style={{ width: `${crawlPct}%` }} />
      </div>

      <div className="workspace">
        <section
          className={`left-panel ${leftCollapsed ? 'collapsed' : ''}`}
          style={{
            width: leftCollapsed ? 56 : leftW,
            ['--panel-left' as string]: `${leftW}px`,
          }}
        >
          <LeftRail
            stats={stats}
            lastSync={lastSync}
            exchange={exchange}
            rules={rules}
            topEntities={topEntities}
            topCriteria={topCriteria}
            onCriteriaChange={setTopCriteria}
            filterMode={filterMode}
            exploreSegmentVisual={
              cmdMode === 'query' || cmdMode === 'inferred'
                ? null
                : filterMode
            }
            onCompanies={() => {
              setFilterMode('companies');
              void graph.loadHubsOnly();
            }}
            onPersons={() => {
              setFilterMode('persons');
              void graph.loadPersonGraph();
            }}
            onPickEntity={(id) => {
              window.dispatchEvent(
                new CustomEvent('kg-search-pick', { detail: id })
              );
            }}
            onInferredRelationsClick={handleOpenHiddenRelations}
            inferredRelationsDisabled={
              !stats || (stats.inferred_relationships ?? 0) <= 0
            }
            collapsed={leftCollapsed}
            onToggleCollapsed={() => setLeftCollapsed((c) => !c)}
          />
        </section>

        <div
          className={`resize-handle ${resizeEdge === 'left' ? 'active' : ''}`}
          role="separator"
          aria-orientation="vertical"
          onMouseDown={() => setResizeEdge('left')}
        />

        <main ref={graphAreaRef} className="graph-area">
          {qOpen ? (
            <div className="q-overlay">
              <div
                className="q-panel"
                role="dialog"
                aria-label={vi.cypherBlock}
                aria-modal="true"
              >
                <header className="q-panel-toolbar">
                  <div className="q-panel-title-block">
                    <span className="q-panel-badge">{vi.cypherBlock}</span>
                  </div>
                  <button
                    type="button"
                    className="q-toolbar-toggle"
                    onClick={() => setQCollapsed((c) => !c)}
                    aria-expanded={!qCollapsed}
                  >
                    {qCollapsed ? vi.qresultExpand : vi.qresultCollapse}
                  </button>
                </header>
                {!qCollapsed ? (
                  <div className="q-panel-body">
                    <section
                      className="q-section q-section--code"
                      aria-labelledby="q-code-h"
                    >
                      <h3 id="q-code-h" className="q-section-head">
                        {vi.queryCodeHeading}
                      </h3>
                      <pre className="q-cypher-pre">
                        <code>{qCypher}</code>
                      </pre>
                    </section>
                    <section
                      className="q-section q-section--log"
                      aria-labelledby="q-log-h"
                    >
                      <h3 id="q-log-h" className="q-section-head">
                        {vi.queryLogHeading}
                      </h3>
                      <div className="process-steps">
                        {qSteps.map((s) => (
                          <div key={s.slice(0, 48)} className="process-step">
                            {s}
                          </div>
                        ))}
                      </div>
                    </section>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}

          {hiddenPopupOpen ? (
            <div className="hidden-overlay" role="presentation">
              <div
                className="hidden-panel"
                role="dialog"
                aria-modal="true"
                aria-label={vi.hiddenRelationsPopupTitle}
              >
                <header className="hidden-panel-toolbar">
                  <div>
                    <h2 className="hidden-panel-title">
                      {vi.hiddenRelationsPopupTitle}
                    </h2>
                    <p className="hidden-panel-hint">
                      {vi.hiddenRelationsPopupHint}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="hidden-panel-close"
                    onClick={() => setHiddenPopupOpen(false)}
                  >
                    {vi.hiddenRelationsClose}
                  </button>
                </header>
                <div className="hidden-panel-body">
                  {!hiddenRows.length ? (
                    <div className="muted">{vi.hiddenRelationsEmpty}</div>
                  ) : (
                    hiddenRows.map((row) => {
                      const rk = hiddenRowKey(row);
                      const open = hiddenExpandKey === rk;
                      const rowCtx = hiddenContextByKey[rk];
                      const ruleMeta = row.rule
                        ? ruleById.get(String(row.rule))
                        : undefined;
                      const fallbackWhyParts: string[] = [];
                      if (row.rule) {
                        fallbackWhyParts.push(`Kích hoạt: ${lawDisplay(row.rule)}.`);
                      }
                      if (row.level) {
                        fallbackWhyParts.push(
                          `Mức ảnh hưởng: ${influenceLevelVi(row.level)}.`
                        );
                      }
                      if (ruleMeta?.explanation) {
                        fallbackWhyParts.push(ruleMeta.explanation);
                      }
                      return (
                        <div key={rk} className="hidden-row">
                          <div className="hidden-row-head">
                            <button
                              type="button"
                              className="hidden-row-toggle"
                              aria-expanded={open}
                              onClick={() => handleToggleHiddenRow(row)}
                            >
                              <div className="hidden-row-main">
                                <strong>{row.source_name || row.source}</strong>
                                {' → '}
                                <strong>{row.target_name || row.target}</strong>
                                {row.relation ? (
                                  <>
                                    {' '}
                                    <kbd>{relationLabelVi(row.relation, row.rule)}</kbd>
                                  </>
                                ) : null}
                              </div>
                            </button>
                            <div className="hidden-row-actions">
                              <button
                                type="button"
                                className="hidden-row-expand-btn"
                                onClick={() => void handleFocusHiddenRelation(row)}
                              >
                                {vi.hiddenRelationsExpandGraph}
                              </button>
                            </div>
                          </div>
                          {open ? (
                            <div className="hidden-row-body">
                              {rowCtx?.loading ? (
                                <p className="muted">
                                  {vi.hiddenRelationsLoading}
                                </p>
                              ) : null}
                              {rowCtx?.summary ? (
                                <p className="hidden-row-summary">
                                  <strong>{vi.hiddenRelationsWhy}:</strong>{' '}
                                  {rowCtx.summary}
                                </p>
                              ) : null}
                              {rowCtx?.explanationLines?.length ? (
                                <ul className="hidden-row-list">
                                  {rowCtx.explanationLines.map((line) => (
                                    <li key={line}>{line}</li>
                                  ))}
                                </ul>
                              ) : fallbackWhyParts.length ? (
                                <ul className="hidden-row-list">
                                  {fallbackWhyParts.map((line) => (
                                    <li key={line}>{line}</li>
                                  ))}
                                </ul>
                              ) : null}
                              {rowCtx?.error ? (
                                <p className="muted">{rowCtx.error}</p>
                              ) : null}
                              {row.level ? (
                                <p>
                                  <strong>{vi.ruleInferredLabel}</strong> mức ảnh
                                  hưởng: {influenceLevelVi(row.level)}
                                  {row.ownership != null
                                    ? `; sở hữu gián tiếp ~ ${String(row.ownership)}`
                                    : null}
                                </p>
                              ) : null}
                              {ruleMeta?.name ? (
                                <p>
                                  <strong>{vi.hiddenRelationsRule}:</strong>{' '}
                                  {ruleMeta.name}
                                </p>
                              ) : null}
                              {ruleMeta?.legal_refs?.length ? (
                                <div>
                                  <strong>{vi.hiddenRelationsLegal}</strong>
                                  <ul>
                                    {ruleMeta.legal_refs.map((lr) => (
                                      <li key={lr.url}>
                                        <a
                                          href={lr.url}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                        >
                                          {lr.title}
                                        </a>
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          ) : null}

          <div className="graph-canvas-wrap">
            <div ref={graphHostRef} className="graph-canvas" />
          </div>

          <div className="graph-dock">
            <div className="graph-dock-row">
              <div className="command-strip">
                <div className="cmd-chip">
                  <span className="cmd-chip-label">{vi.commandMode}</span>
                  <strong>{cmdLabels.mode}</strong>
                </div>
                <div className="cmd-chip">
                  <span className="cmd-chip-label">{vi.commandAlert}</span>
                  <strong>{cmdLabels.alert}</strong>
                </div>
              </div>
              <div className="graph-legend">
                <div className="leg-item">
                  <span className="leg-dot company" /> {vi.legendCompany}
                </div>
                <div className="leg-item">
                  <span className="leg-dot person" /> {vi.legendPerson}
                </div>
              </div>
            </div>
            <div className="graph-hint">{vi.graphHint}</div>
          </div>

          <NodeDetailPanel
            key={selectedId || 'closed'}
            open={!!selectedId}
            boundsRef={graphAreaRef}
            title={
              String(
                nodeProps?.name ||
                  nodeProps?.displayName ||
                  selectedId ||
                  ''
              )
            }
            badge={badgeType}
            props={nodeProps}
            expandLabel={expandLabel}
            onExpand={() => selectedId && void graph.expandOrToggleNeighbors(selectedId)}
            onClose={() => {
              setSelectedId(null);
              setNodeProps(null);
            }}
          />
        </main>

        <div
          className={`resize-handle ${resizeEdge === 'right' ? 'active' : ''}`}
          role="separator"
          aria-orientation="vertical"
          onMouseDown={() => setResizeEdge('right')}
        />

        <section
          className={`right-panel ${rightCollapsed ? 'collapsed' : ''}`}
          style={{
            width: rightCollapsed ? 56 : rightW,
            ['--panel-right' as string]: `${rightW}px`,
          }}
        >
          <AssistantPanel
            graph={graph}
            collapsed={rightCollapsed}
            onToggleCollapsed={() => setRightCollapsed((c) => !c)}
            onOpenAssistant={() => setRightCollapsed(false)}
          />
        </section>
      </div>
    </div>
  );
}
