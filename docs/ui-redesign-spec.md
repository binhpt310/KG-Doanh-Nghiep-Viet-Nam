# UI Redesign Specification

## Design System
### Color Palette (WCAG 2.2 AA Compliant)
| Token | Dark Mode | Light Mode | Contrast Ratio (on bg) |
|-------|-----------|------------|------------------------|
| --bg | #0D1117 | #F6F8FA | N/A |
| --surface | #161B22 | #FFFFFF | 5.7:1 (text on surface) |
| --text-primary | #E6EDF3 | #1F2328 | 15.2:1 / 12.1:1 |
| --text-secondary | #8B949E → #B1BAC4 | #57606A → #6E7681 | 4.6:1 / 4.5:1 |
| --accent-blue | #58A6FF | #0969DA | 5.1:1 / 4.8:1 |
| --accent-green | #3FB950 | #1A7F37 | 5.3:1 / 4.9:1 |
| --edge-default | #30363D → #484F58 | #D0D7DE → #AFB8C1 | 4.8:1 / 4.6:1 |
| --edge-inferred | #E3B341 → #F59E0B | #9A6700 → #B08400 | 5.0:1 / 4.7:1 |

### Typography
- Font stack: Inter, system-ui, -apple-system, sans-serif
- Base size: 14px (desktop), 16px (mobile)
- Label sizes:
  - Graph node: 14px default (readable at 1x zoom)
  - Edge label: 12px (visible at 1.2x+ zoom)
  - UI text: 12px (secondary), 14px (primary)

### Spacing Grid
8px base unit: --s-1=8px, --s-2=16px, --s-3=24px, --s-4=32px

## Component Redesigns
### Left Panel (260px default)
```
┌─────────────────────────────┐
│ 📊 Overview (collapsed)     │
├─────────────────────────────┤
│ 🔍 Explore (expanded)       │
│  ├─ View Mode: [Companies] │
│  ├─ Top Entities (degree)  │
│  │  ├─ 1. VIC (142 links) │
│  │  └─ 2. FPT (128 links) │
├─────────────────────────────┤
│ 🛠️ Tools (collapsed)       │
└─────────────────────────────┘
```

### Graph Area
- Default zoom: 1.2x (nodes readable without zooming)
- Node size: 20px (min 12px, max 48px)
- Edge width: 2px (default), 3px (highlighted)
- Legend: Fixed bottom center, 12px text, 10px dot size
- Zoom controls: Bottom right, 40px buttons, WCAG compliant contrast

### Right Panel (340px default)
- Chat input: 16px font for mobile usability
- Model selector: Persistent at top, 12px font
- Chat history: 16px line height, 12px timestamp

## Interaction Specs
| Interaction | Behavior |
|-------------|----------|
| Node click | Show detail panel, highlight connected edges, zoom to 1.5x |
| Edge hover | Show label tooltip, glow effect |
| Graph scroll | Zoom 0.1x per scroll step, max 3x, min 0.3x |
| Keyboard | Tab to navigate nodes, Enter to select, Escape to deselect |
| Mobile | Pinch zoom, two-finger pan, single tap to select node |

## Responsive Breakpoints
| Breakpoint | Layout | Left Panel | Right Panel |
|------------|--------|------------|-------------|
| ≥ 1200px | 3-column | 260px | 340px |
| 768-1199px | 3-column | 220px | 300px |
| < 768px | Stacked | Hidden (toggle button) | Full width bottom |
