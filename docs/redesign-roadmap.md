# KG Explorer Redesign Roadmap

## Executive Summary
Complete visual and technical overhaul of the KG Explorer to address layout flaws, graph readability, performance, and accessibility deficits. Target WCAG 2.2 AA compliance, 60fps graph rendering for 10k+ nodes, and sub-200ms interaction latency.

## Current State Audit
### Critical Issues
1. **Left Panel**: Cluttered hierarchy, 6+ unorganized sections, no collapsible groups, poor spacing
2. **Graph Rendering**:
   - Uses legacy vis-network (no WebGL, poor scaling beyond 1k nodes)
   - Node size (14px default) too small, requires zoom to read labels
   - Edge width (1.0px) and contrast (rgba(48,54,61,0.85)) illegible on dark bg
   - No level-of-detail (LOD) rendering, no dynamic label fading
3. **Accessibility**:
   - Text contrast ratios as low as 3.8:1 (below WCAG AA 4.5:1)
   - No ARIA labels for graph interactions, no keyboard navigation
   - Missing focus indicators on interactive elements
4. **DevOps**:
   - No frontend build pipeline, CDN-loaded dependencies
   - No hot-reload for frontend changes
   - No asset optimization or caching

## Strategic Pillars
| Pillar | Goals |
|--------|-------|
| Information Architecture | Simplify left panel to 3 collapsible sections, prioritize high-value content |
| Visual Design | High-contrast color system, consistent 8px spacing grid, WCAG 2.2 AA compliance |
| Graph Performance | Migrate to WebGL-rendered graph engine, implement LOD, dynamic label fading |
| Interaction | Keyboard-navigable graph, context-aware menus, touch-optimized gestures |
| DevOps | Vite-based frontend pipeline, hot-reload, multi-stage Docker builds |

## Phased Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] Migrate frontend to Vite + React + TypeScript
- [ ] Implement Tailwind CSS with custom design tokens
- [ ] Set up WCAG 2.2 AA compliant color palette
- [ ] Add ARIA labels, focus indicators, keyboard navigation

### Phase 2: Graph Overhaul (Week 3-4)
- [ ] Replace vis-network with Cytoscape.js + cytoscape-gl (WebGL)
- [ ] Implement LOD rendering:
  - < 0.5x zoom: Hide edge labels, reduce node size variance
  - 0.5-1.5x zoom: Show high-contrast edges (2px width), fade secondary labels
  - > 1.5x zoom: Full detail, show all labels
- [ ] Increase default node size to 20px, edge width to 2px
- [ ] Add anti-aliased edge rendering, neon glow for inferred edges

### Phase 3: Left Panel Redesign (Week 5)
- [ ] Collapse 6 sections into 3 toggleable groups:
  1. **Overview**: Stats + exchange distribution
  2. **Explore**: View mode + top entities
  3. **Tools**: Hidden rules + suggested prompts
- [ ] Add section search, persist collapse state in localStorage
- [ ] Implement responsive collapse for mobile (< 768px)

### Phase 4: Accessibility & Polish (Week 6)
- [ ] Audit all contrast ratios, fix non-compliant pairs
- [ ] Add screen reader announcements for graph updates
- [ ] Implement focus trapping for modals, skip navigation links
- [ ] Add animation optimizations (reduced motion media query support)

### Phase 5: Deployment & Metrics (Week 7)
- [ ] Multi-stage Docker builds for production
- [ ] Add performance monitoring (Core Web Vitals)
- [ ] Define success metrics, set up dashboard

## Success Metrics
| Metric | Target | Measurement |
|--------|--------|--------------|
| Graph render time (5k nodes) | < 1.5s | PerformanceObserver |
| Text contrast ratio | ≥ 4.5:1 (WCAG AA) | Automated a11y audit |
| Interaction latency | < 200ms | Performance API |
| Mobile responsive score | ≥ 95/100 | Lighthouse |
| Hot-reload time | < 500ms | DevTools |
