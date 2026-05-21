import { useCallback, useState } from 'react';
import { apiJson } from '../api/client';
import { vi } from '../content/copy/vi';

interface EdgeTypeRow {
  type: string;
  count: number;
  inferred: boolean;
}

export interface RuleRow {
  id?: string;
  name: string;
  logic: string;
  inferred: string;
  explanation?: string;
  example?: string;
  legal_refs?: { title: string; url: string; citation?: string }[];
}

interface ExchangeRow {
  exchange: string;
  count: number;
}

interface TopEntity {
  id: string;
  name: string;
  value: number | string;
}

interface Props {
  stats: {
    companies: number;
    persons: number;
    total_edges: number;
    inferred_relationships: number;
    total_nodes: number;
  } | null;
  lastSync: string;
  exchange: { breakdown: ExchangeRow[]; total: number } | null;
  rules: RuleRow[] | null;
  topEntities: TopEntity[] | null;
  topCriteria: string;
  onCriteriaChange: (v: string) => void;
  filterMode: 'companies' | 'persons';
  /** Which segment shows "active" styling; null when graph is query/inferred so neither looks selected */
  exploreSegmentVisual: 'companies' | 'persons' | null;
  onCompanies: () => void;
  onPersons: () => void;
  onPickEntity: (id: string) => void;
  onInferredRelationsClick?: () => void;
  inferredRelationsDisabled?: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function LeftRail({
  stats,
  lastSync,
  exchange,
  rules,
  topEntities,
  topCriteria,
  onCriteriaChange,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  filterMode: _filterMode,
  exploreSegmentVisual,
  onCompanies,
  onPersons,
  onPickEntity,
  onInferredRelationsClick,
  inferredRelationsDisabled,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  collapsed: _collapsed,
  onToggleCollapsed,
}: Props) {
  const fmt = (n: number) => n.toLocaleString('vi-VN');
  const [openRuleIdx, setOpenRuleIdx] = useState<number | null>(0);
  const [edgeTypesOpen, setEdgeTypesOpen] = useState(false);
  const [edgeTypes, setEdgeTypes] = useState<EdgeTypeRow[] | null>(null);
  const [edgeTypesLoading, setEdgeTypesLoading] = useState(false);

  const toggleEdgeTypes = useCallback(async () => {
    if (edgeTypesOpen) {
      setEdgeTypesOpen(false);
      return;
    }
    setEdgeTypesOpen(true);
    setEdgeTypesLoading(true);
    try {
      const data = await apiJson<{ types: EdgeTypeRow[] }>('/api/stats/edge-types');
      setEdgeTypes(data.types || []);
    } catch {
      setEdgeTypes([]);
    } finally {
      setEdgeTypesLoading(false);
    }
  }, [edgeTypesOpen]);

  const toggleRule = (idx: number) => {
    setOpenRuleIdx((cur) => (cur === idx ? null : idx));
  };

  return (
    <div className="left-rail">
      <button
        type="button"
        className="panel-edge-toggle"
        title={vi.sidebarToggle}
        onClick={onToggleCollapsed}
      >
        <span className="panel-edge-glyph" aria-hidden>
          ‹
        </span>
      </button>

      <div className="left-panel-inner">
        <section className="rail-intro">
          <span className="rail-kicker">{vi.railSnapshot}</span>
          <p className="rail-copy">{vi.railSnapshotHint}</p>
        </section>

        <div className="card">
          <div className="card-hd">
            <span>{vi.overviewTitle}</span>
            <span className="meta">{vi.overviewSync}: {lastSync}</span>
          </div>
          <div className="card-bd">
            <div className="stat-grid">
              <div className="stat-lg">
                <div className="lbl">{vi.listedCompanies}</div>
                <div className="val co">
                  {stats ? fmt(stats.companies) : '—'}
                </div>
              </div>
              <div className="stat-lg">
                <div className="lbl">{vi.persons}</div>
                <div className="val pe">
                  {stats ? fmt(stats.persons) : '—'}
                </div>
              </div>
            </div>
            <div className="stat-lines">
              <button
                type="button"
                className="stat-line stat-line--action"
                onClick={() => void toggleEdgeTypes()}
                title={vi.edgeTypesPanelHint}
                aria-expanded={edgeTypesOpen}
              >
                <span>{vi.edgesInDb}</span>
                <span>{stats ? fmt(stats.total_edges) : '—'}</span>
              </button>
              {edgeTypesOpen ? (
                <div className="edge-types-panel" role="region" aria-label={vi.edgeTypesPanelTitle}>
                  <div className="edge-types-panel-hd">
                    <span>{vi.edgeTypesPanelTitle}</span>
                    <button
                      type="button"
                      className="edge-types-close"
                      onClick={() => setEdgeTypesOpen(false)}
                    >
                      {vi.edgeTypesClose}
                    </button>
                  </div>
                  <div className="edge-types-list">
                    {edgeTypesLoading ? (
                      <div className="muted">{vi.edgeTypesLoading}</div>
                    ) : edgeTypes?.length ? (
                      edgeTypes.map((row) => (
                        <div
                          key={`${row.type}-${row.inferred}`}
                          className={`edge-types-row${row.inferred ? ' inferred' : ''}`}
                        >
                          <span className="edge-types-name" title={row.type}>
                            {row.type}
                          </span>
                          <span className="edge-types-count">{fmt(row.count)}</span>
                        </div>
                      ))
                    ) : (
                      <div className="muted">{vi.loadFailed}</div>
                    )}
                  </div>
                </div>
              ) : null}
              {onInferredRelationsClick ? (
                <button
                  type="button"
                  className="stat-line stat-line--action"
                  onClick={onInferredRelationsClick}
                  disabled={inferredRelationsDisabled}
                  title={vi.inferredEdgesLabel}
                >
                  <span>{vi.inferredEdgesLabel}</span>
                  <span className="warm">
                    {stats ? fmt(stats.inferred_relationships) : '—'}
                  </span>
                </button>
              ) : (
                <div className="stat-line">
                  <span>{vi.inferredEdgesLabel}</span>
                  <span className="warm">
                    {stats ? fmt(stats.inferred_relationships) : '—'}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-hd">
            <span>{vi.marketFootprint}</span>
            <span className="meta">
              {exchange?.total != null
                ? `${fmt(exchange.total)} ${vi.companiesUnit}`
                : '—'}
            </span>
          </div>
          <div className="card-bd exchange-body">
            {!exchange?.breakdown?.length ? (
              <div className="muted">{vi.loading}</div>
            ) : (
              exchange.breakdown.slice(0, 6).map((row) => {
                const pct = exchange.total
                  ? (row.count / exchange.total) * 100
                  : 0;
                const ex = (row.exchange || 'Khác').toUpperCase();
                return (
                  <div key={ex} className="ex-row">
                    <span className="ex-lbl">{ex}</span>
                    <div className="ex-track">
                      <div className="ex-fill" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="ex-n">{fmt(row.count)}</span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        <section className="rail-intro">
          <span className="rail-kicker">{vi.railExplore}</span>
          <p className="rail-copy">{vi.railExploreHint}</p>
        </section>

        <div className="card">
          <div className="card-hd">{vi.exploreMode}</div>
          <div className="card-bd">
            <div className="seg">
              <button
                type="button"
                className={
                  exploreSegmentVisual === 'companies'
                    ? 'seg-btn on'
                    : 'seg-btn'
                }
                onClick={onCompanies}
              >
                <span className="dot co" /> {vi.modeCompanies}
              </button>
              <button
                type="button"
                className={
                  exploreSegmentVisual === 'persons'
                    ? 'seg-btn on p'
                    : 'seg-btn'
                }
                onClick={onPersons}
              >
                <span className="dot pe" /> {vi.modePersons}
              </button>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-hd split">
            <span>{vi.quickEntry}</span>
            <select
              className="select-mini"
              value={topCriteria}
              onChange={(e) => onCriteriaChange(e.target.value)}
            >
              <option value="degree">{vi.criteriaDegree}</option>
              <option value="shareholders">{vi.criteriaShareholders}</option>
              <option value="subsidiaries">{vi.criteriaSubsidiaries}</option>
              <option value="leadership">{vi.criteriaLeadership}</option>
              <option value="market_cap">{vi.criteriaMarketCap}</option>
            </select>
          </div>
          <div className="card-bd top-list">
            {!topEntities ? (
              <div className="muted">{vi.loading}</div>
            ) : topEntities.length === 0 ? (
              <div className="muted">—</div>
            ) : (
              topEntities.map((item, idx) => (
                <button
                  type="button"
                  key={item.id}
                  className="top-item"
                  onClick={() => onPickEntity(item.id)}
                >
                  <span className="rk">{idx + 1}</span>
                  <span className="nm">{item.name}</span>
                  <span className="dg">{String(item.value)}</span>
                </button>
              ))
            )}
          </div>
        </div>

        <section className="rail-intro">
          <span className="rail-kicker">{vi.railInference}</span>
          <p className="rail-copy">{vi.railInferenceHint}</p>
        </section>

        <div className="card rules-card">
          <div className="card-hd">{vi.inferenceRulesTitle}</div>
          <div className="card-bd rules-body">
            {!rules?.length ? (
              <div className="muted">{vi.loading}</div>
            ) : (
              rules.map((r, idx) => {
                const open = openRuleIdx === idx;
                return (
                  <div key={r.id || r.name} className="rule-acc">
                    <button
                      type="button"
                      className="rule-acc-head"
                      aria-expanded={open}
                      onClick={() => toggleRule(idx)}
                    >
                      <span className="rule-acc-title">{r.name}</span>
                      {r.legal_refs?.length ? (
                        <a
                          className="rule-acc-law"
                          href={r.legal_refs[0].url}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={r.legal_refs[0].title}
                          onClick={(ev) => ev.stopPropagation()}
                        >
                          {vi.ruleLegalRefsTitle}
                        </a>
                      ) : (
                        <span className="rule-acc-law-spacer" aria-hidden />
                      )}
                      <span className="rule-acc-chev" aria-hidden>
                        {open ? '▾' : '▸'}
                      </span>
                    </button>
                    {open ? (
                      <div className="rule-acc-body">
                        <div className="rule-acc-row">
                          <span className="rule-acc-k">{vi.ruleLogicLabel}</span>
                          <div className="rule-meta">
                            <span className="mono">{r.logic}</span>
                          </div>
                        </div>
                        <div className="rule-acc-row rule-acc-inf">
                          <span className="rule-acc-k">{vi.ruleInferredLabel}</span>
                          <div className="rule-meta rule-meta--wrap">
                            <span className="rule-inf-inline">→ {r.inferred}</span>
                          </div>
                        </div>
                        {r.explanation ? (
                          <p className="rule-exp">{r.explanation}</p>
                        ) : null}
                        {r.example ? (
                          <p className="rule-exp rule-exp--muted">
                            <strong>{vi.suggestedInvestigation}:</strong> {r.example}
                          </p>
                        ) : null}
                        {r.legal_refs?.length ? (
                          <div className="rule-legal-list">
                            <span className="rule-acc-k">{vi.hiddenRelationsLegal}</span>
                            <ul>
                              {r.legal_refs.map((lr) => (
                                <li key={lr.url}>
                                  <a
                                    href={lr.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    {lr.title}
                                  </a>
                                  {lr.citation ? (
                                    <div className="rule-legal-cite">
                                      {lr.citation}
                                    </div>
                                  ) : null}
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
    </div>
  );
}
