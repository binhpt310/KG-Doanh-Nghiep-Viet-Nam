# Dashboard Redesign Plan

## Objective
Transform KG Explorer from a dense internal admin UI into a product-grade intelligence dashboard that feels deliberate, premium, and credible on first contact while preserving the current Flask + Neo4j workflow.

The target is not "prettier dark mode". The target is a graph-first product that:
- explains value within 5 seconds,
- makes the network visualization the hero,
- keeps chat and inference tooling powerful but secondary,
- works cleanly on desktop, tablet, and mobile,
- improves perceived performance as much as raw performance.

## Current Product Reality

### Running stack
- `kg-app` serves a single Flask template on port `5001`.
- `neo4j` serves the graph database on `7474` and `7687`.
- Cloudflare Tunnel forwards `https://stranger-strength-tuning-relating.trycloudflare.com` to `http://localhost:5001`.

### Current data shape
- `4,470` total nodes
- `5,068` total edges
- `1,044` companies
- `3,426` persons
- `24` inferred relationships

### Current design problems
- The product reads like a generated admin template: top bar, two rails, dark cards, generic pills.
- The graph is visually subordinated by permanent side panels.
- The left rail contains too many equally weighted sections.
- Mobile behavior is a layout collapse, not a mobile design.
- The current redesign docs are strong on technology and weak on art direction.

## Product Positioning
KG Explorer should present itself as:
- an intelligence console for Vietnamese listed-company relationships,
- a tool for discovering hidden influence, family control, and cross-holdings,
- a visual-first product with an AI copilot, not a chat app with a graph attached.

## Design Principles

### 1. Graph first
The network canvas is the product's differentiator. It should own the center of gravity on every large screen.

### 2. Fewer simultaneous decisions
The user should not face stats, prompts, rules, chat history, search, sessions, model choice, and graph interactions at the same time.

### 3. Editorial, not generic SaaS
The visual system should feel intentional through typography, spacing, contrast, and composition, not through more borders and pills.

### 4. Premium through restraint
Use fewer colors, fewer separators, and fewer component types. Let spacing, scale, and motion do more work.

### 5. Mobile is a separate layout
Do not vertically stack the desktop shell. Mobile should prioritize view switching and progressive disclosure.

## Information Architecture

### Primary modes
- `Explore`: browse companies, people, sectors, and top entities.
- `Inspect`: examine the currently selected node or cluster.
- `Ask`: use RAG chat, Cypher traces, and query history.

### Desktop shell
- Left rail: curated exploration and KPI overview.
- Center canvas: graph, hero framing, context overlays.
- Right drawer: contextual assistant and detail workspace.

### Mobile shell
- Top summary strip for status and brand.
- Graph occupies the main viewport.
- Left rail content becomes a horizontal scannable strip above the graph.
- Assistant becomes a bottom sheet.

## Visual Direction

### Brand personality
- Analytical
- Modern
- Trustworthy
- Slightly editorial
- High-signal, low-clutter

### Typography
- Primary: `Manrope`
- Secondary/system fallback: `Inter`
- Mono/data: `IBM Plex Mono`

### Color system
- Keep a dark foundation, but warm it slightly.
- Introduce depth with layered surfaces and ambient gradients instead of flat card stacks.
- Reserve bright blue for core actions and selected graph entities.
- Use green and amber as semantic accents, not co-equal brand colors.

### Surface strategy
- App background should feel atmospheric, not flat.
- Panels should feel like crafted instruments, not stock cards.
- Overlay surfaces should use blur carefully and only where it improves hierarchy.

## UX Plan

### Top bar
- Keep it compact.
- Emphasize brand, live status, and one primary action.
- Remove low-value visual clutter.

### Left rail
- Reorganize into three blocks:
  - `Snapshot`
  - `Explore`
  - `Inference`
- Make rules and prompts secondary, not permanent reading walls.

### Graph area
- Add a clear product story at the top of the graph area.
- Add quick actions that let users switch between companies, people, and chat.
- Improve node readability and edge contrast.
- Reduce the sense of an empty void through composition and subtle atmosphere.

### Right drawer
- Restyle as a premium assistant console.
- Keep model and session controls, but visually subordinate them.
- Ensure chat feels like a focused task area rather than another utilities panel.

### Node detail
- Keep it fast and information-dense.
- Improve hierarchy so names, roles, and major holdings scan immediately.

### Mobile
- Preserve left-rail content as a horizontal browse surface instead of hiding it.
- Use the assistant as a bottom-sheet workspace.
- Keep graph interactions central.

## Performance Plan

### Immediate
- Improve perceived performance with better loading states and staged layout hierarchy.
- Make graph-first rendering obvious while data sections hydrate progressively.
- Keep existing company-only and person-view query strategies.

### Near-term
- Increase node readability and refine vis-network options without causing layout thrash.
- Minimize unnecessary `fit()` calls after panel changes.
- Avoid rendering long legal/inference text blocks above the fold by default.

### Later
- Move to a dedicated frontend build pipeline.
- Replace `vis-network` with a WebGL-capable engine when implementation bandwidth justifies it.

## Accessibility Plan
- Maintain AA-level contrast for body text and controls.
- Keep visible focus states.
- Improve mobile touch target sizes.
- Reduce dense uppercase micro-labeling where readability suffers.
- Respect reduced-motion preferences in a later pass.

## Execution Phases

### Phase 1: Product-grade shell
- Rewrite the app shell to be graph-first.
- Introduce a new design token system.
- Add graph hero framing and a more premium top-level composition.
- Convert the right panel into a contextual drawer.
- Replace the mobile collapse with a real responsive structure.

### Phase 2: Interaction cleanup
- Tighten panel toggles, graph overlays, and assistant states.
- Improve node detail hierarchy.
- Make sections easier to scan and less visually noisy.

### Phase 3: Performance and technical modernization
- Audit graph interaction cost.
- Reduce blocking dependencies and CDN reliance.
- Evaluate React/Vite/Cytoscape migration once the product direction is stable.

## Success Criteria
- The first screen explains the product without narration.
- The graph looks intentional and central on desktop.
- Mobile retains access to explore content without burying the graph.
- Chat feels integrated, not bolted on.
- The UI no longer resembles a generated dashboard scaffold.
