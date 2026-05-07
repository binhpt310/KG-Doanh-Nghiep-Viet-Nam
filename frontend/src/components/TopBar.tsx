import { vi } from '../content/copy/vi';
import { BrandLogo } from './BrandLogo';

interface Props {
  theme: 'dark' | 'light';
  heroExpanded: boolean;
  onToggleHero: () => void;
  onToggleTheme: () => void;
  onCrawl: () => void;
  crawlBusy: boolean;
  heroMetrics: { entities: string; links: string; hidden: string };
}

export function TopBar({
  theme,
  heroExpanded,
  onToggleHero,
  onToggleTheme,
  onCrawl,
  crawlBusy,
  heroMetrics,
}: Props) {
  const metrics = (
    <div className="hero-metrics hero-metrics--inline">
      <div className="hero-stat hero-stat--inline">
        <span className="hero-stat-label">{vi.heroStatEntities}</span>
        <strong className="hero-stat-value">{heroMetrics.entities}</strong>
      </div>
      <div className="hero-stat hero-stat--inline">
        <span className="hero-stat-label">{vi.heroStatLinks}</span>
        <strong className="hero-stat-value">{heroMetrics.links}</strong>
      </div>
      <div className="hero-stat hero-stat--inline">
        <span className="hero-stat-label">{vi.heroStatHidden}</span>
        <strong className="hero-stat-value">{heroMetrics.hidden}</strong>
      </div>
    </div>
  );

  return (
    <>
      <header className="topbar">
        <div className="topbar-brand-wrap">
          <div className="topbar-brand">
            <div className="brand-mark" aria-hidden>
              <BrandLogo className="brand-logo-svg" />
            </div>
            <div className="brand-copy" title={vi.brandSub}>
              <span className="brand-name">{vi.brandName}</span>
              <span className="brand-sep" aria-hidden>
                —
              </span>
              <span className="brand-sub">{vi.brandSub}</span>
            </div>
          </div>
          <a className="topbar-credit" href="mailto:ptbinh@csc.hcmus.edu.vn">
            {vi.designCredit}
          </a>
        </div>

        <section className="topbar-hero-wrap" aria-label={vi.heroKicker}>
          <div
            className={`topbar-hero neu-panel ${heroExpanded ? 'is-open' : 'is-collapsed'}`}
          >
            <div className="hero-row">
              <div className="hero-row-left">
                <span className="rail-kicker">{vi.heroKicker}</span>
                <button
                  type="button"
                  className="hero-toggle neu-toggle"
                  onClick={onToggleHero}
                  aria-expanded={heroExpanded}
                >
                  {heroExpanded ? vi.heroToggleCollapse : vi.heroToggleExpand}
                </button>
              </div>
              {metrics}
            </div>
          </div>
        </section>

        <aside className="topbar-aside">
          <div className="topbar-actions">
            <button
              type="button"
              className="btn-crawl neu-btn-primary"
              disabled={crawlBusy}
              onClick={onCrawl}
            >
              {crawlBusy ? vi.crawlRunning : vi.crawlCta}
            </button>
            <button
              type="button"
              className="btn-icon neu-btn-round"
              title={vi.themeToggle}
              onClick={onToggleTheme}
            >
              {theme === 'dark' ? (
                <span className="theme-ico" aria-hidden>
                  ◐
                </span>
              ) : (
                <span className="theme-ico" aria-hidden>
                  ◑
                </span>
              )}
            </button>
          </div>
        </aside>
      </header>

      {heroExpanded ? (
        <div className="hero-expand-panel neu-panel" role="region" aria-label={vi.heroKicker}>
          <h1 className="hero-title">{vi.heroTitle}</h1>
          <p className="hero-summary">{vi.heroSummary}</p>
        </div>
      ) : null}
    </>
  );
}
