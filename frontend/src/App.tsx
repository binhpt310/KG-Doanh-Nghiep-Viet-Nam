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

/** Mirrors `/api/stats` JSON shape used across dashboard chips */
interface StatsPayload {
  total_nodes: number;
  total_edges: number;
  companies: number;
  persons: number;
  inferred_relationships: number;
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

  const [cmdMode, setCmdMode] = useState<'companies' | 'persons' | 'query'>(
    'companies'
  );
  const [filterMode, setFilterMode] = useState<'companies' | 'persons'>(
    'companies'
  );

  const [heroExpanded, setHeroExpanded] = useState(false);

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

  const [crawlBusy, setCrawlBusy] = useState(false);
  const [crawlPct, setCrawlPct] = useState(0);
  const crawlTimer = useRef<number | null>(null);

  const graphHostRef = useRef<HTMLDivElement>(null);
  const graphAreaRef = useRef<HTMLElement>(null);

  const onKpiUpdate = useCallback((_n: number, _e: number) => {}, []);

  const onGraphModeLabels = useCallback(
    (mode: 'companies' | 'persons' | 'query') => {
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

  useEffect(() => {
    graph.loadHubsOnly().catch(console.error);
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
      void fetchNodeDetail(ce.detail);
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
  }, [fetchNodeDetail, graph]);

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
    return { mode: vi.modeLabelCompanies, alert: vi.alertCompanies };
  }, [cmdMode]);

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
        heroExpanded={heroExpanded}
        onToggleHero={() => setHeroExpanded((v) => !v)}
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
                <div className="leg-item">
                  <span className="leg-dot institution" /> {vi.legendInstitution}
                </div>
                <div className="leg-item">
                  <span className="leg-dash" /> {vi.legendHiddenEdge}
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
