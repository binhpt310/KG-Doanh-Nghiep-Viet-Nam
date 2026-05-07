import { useState } from 'react';
import { vi } from '../content/copy/vi';

export interface RuleRow {
  id?: string;
  name: string;
  logic: string;
  inferred: string;
  explanation?: string;
  example?: string;
  legal_refs?: { title: string; url: string }[];
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
  onCompanies: () => void;
  onPersons: () => void;
  onPickEntity: (id: string) => void;
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
  filterMode,
  onCompanies,
  onPersons,
  onPickEntity,
  collapsed: _collapsed,
  onToggleCollapsed,
}: Props) {
  const fmt = (n: number) => n.toLocaleString('vi-VN');
  const [openRuleIdx, setOpenRuleIdx] = useState<number | null>(0);

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
              <div className="stat-line">
                <span>{vi.edgesInDb}</span>
                <span>{stats ? fmt(stats.total_edges) : '—'}</span>
              </div>
              <div className="stat-line">
                <span>{vi.inferredEdgesLabel}</span>
                <span className="warm">
                  {stats ? fmt(stats.inferred_relationships) : '—'}
                </span>
              </div>
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
                className={filterMode === 'companies' ? 'seg-btn on' : 'seg-btn'}
                onClick={onCompanies}
              >
                <span className="dot co" /> {vi.modeCompanies}
              </button>
              <button
                type="button"
                className={filterMode === 'persons' ? 'seg-btn on p' : 'seg-btn'}
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
                      <span className="rule-acc-num">{idx + 1}</span>
                      <span className="rule-acc-title">{r.name}</span>
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
                          <span className="rule-inf-inline">→ {r.inferred}</span>
                        </div>
                        {r.explanation ? (
                          <p className="rule-exp">{r.explanation}</p>
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
