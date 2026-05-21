import type { RefObject } from 'react';
import { useCallback, useEffect, useMemo } from 'react';
import { DataSet } from 'vis-data';
import { Network } from 'vis-network';
import type { Edge as VisEdge, Node as VisNode } from 'vis-network';
import { apiJson } from '../api/client';
import type { ApiEdge, ApiNode, GraphStoreState } from './types';
import { createInitialStore } from './types';
import {
  dedupeGraphPayload,
  computeDegrees,
  edgePairKey,
  edgeToVis,
  getVisOptions,
  nodeToVis,
} from './visHelpers';

export interface GraphController {
  loadHubsOnly: () => Promise<void>;
  loadPersonGraph: () => Promise<void>;
  drawQueryGraph: (nodes: ApiNode[], edges: ApiEdge[]) => void;
  loadInferredGraph: (nodes: ApiNode[], edges: ApiEdge[]) => void;
  expandOrToggleNeighbors: (nodeId: string) => Promise<void>;
  isNodeExpanded: (nodeId: string) => boolean;
  fitView: () => void;
  destroy: () => void;
  updateTheme: () => void;
  selectNodes: (ids: string[]) => void;
  focusNode: (id: string, scale?: number) => void;
}

interface Options {
  theme: 'dark' | 'light';
  onKpiUpdate: (nodeCount: number, edgeCount: number) => void;
  onGraphModeLabels: (
    mode: 'companies' | 'persons' | 'query' | 'inferred'
  ) => void;
  /** Trigger React re-render after internal graph store mutates (e.g. expand/collapse). */
  onGraphMutation?: () => void;
}

export function useKgGraph(
  containerRef: RefObject<HTMLDivElement | null>,
  { theme, onKpiUpdate, onGraphModeLabels, onGraphMutation }: Options
): GraphController {
  const st = useMemo(() => createInitialStore() as GraphStoreState, []);
  const networkRef = { current: null as Network | null };

  const bump = useCallback(() => {
    onGraphMutation?.();
  }, [onGraphMutation]);

  const destroyNetwork = useCallback(() => {
    if (networkRef.current) {
      networkRef.current.destroy();
      networkRef.current = null;
    }
    st.visNodes = undefined;
    st.visEdges = undefined;
  }, [st]);

  useEffect(
    () => () => {
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }
    },
    []
  );

  const fitView = useCallback(() => {
    networkRef.current?.fit({
      animation: { duration: 500, easingFunction: 'easeInOutQuad' },
    });
  }, []);

  const updateTheme = useCallback(() => {
    const net = networkRef.current;
    if (!net) return;
    const mode = st.mode === 'persons' ? 'persons' : 'hubs';
    const opts = getVisOptions(mode, theme);
    net.setOptions({ nodes: opts.nodes, edges: opts.edges });
  }, [st.mode, theme]);

  const wireInteractions = useCallback(() => {
    const net = networkRef.current;
    if (!net) return;

    net.off('click');
    net.on('click', (p) => {
      if (p.nodes.length > 0) {
        window.dispatchEvent(
          new CustomEvent<string>('kg-node-click', { detail: p.nodes[0] })
        );
      } else if (!p.edges.length) {
        window.dispatchEvent(new Event('kg-node-close'));
      }
    });

    net.off('zoom');
    net.on('zoom', () => {
      const s = net.getScale();
      net.setOptions({
        edges: {
          font: { size: s < 0.4 ? 0 : s < 0.7 ? 12 : s < 1.2 ? 14 : 15 },
        },
      });
    });
  }, []);

  const expandOrToggleNeighbors = useCallback(
    async (nodeId: string) => {
      const net = networkRef.current;
      const nodesDs = st.visNodes;
      const edgesDs = st.visEdges;
      if (!net || !nodesDs || !edgesDs) return;

      if (st.expandedSet.has(nodeId)) {
        st.expandedSet.delete(nodeId);
        const art = st.expandArtifacts[nodeId];
        if (art?.edgeIds?.size) {
          edgesDs.remove(Array.from(art.edgeIds));
        }
        if (art?.nodeIds?.size) {
          art.nodeIds.forEach((nid) => {
            if (nid === nodeId) return;
            if (st.initialNodeIds.has(nid)) return;
            const rest = edgesDs.get({
              filter: (e: VisEdge) => e.from === nid || e.to === nid,
            });
            if (!rest.length) {
              try {
                nodesDs.remove(nid);
              } catch {
                /* already removed */
              }
            }
          });
        }
        delete st.expandArtifacts[nodeId];
        net.selectNodes([]);
        setTimeout(() => fitView(), 200);
        onKpiUpdate(nodesDs.length, edgesDs.length);
        bump();
        return;
      }

      const neighLimit = st.mode === 'persons' ? 200 : 120;
      let scopeParam = '';
      if (nodeId.startsWith('P_') && st.mode === 'persons') {
        scopeParam = '&scope=family';
      } else if (
        nodeId.startsWith('C_') ||
        nodeId.startsWith('C_INST_') ||
        (nodeId.startsWith('P_') && st.mode !== 'persons')
      ) {
        scopeParam = '&scope=company';
      } else if (nodeId.startsWith('P_')) {
        scopeParam = '&scope=company';
      }
      const raw = await apiJson<{ nodes: ApiNode[]; edges: ApiEdge[] }>(
        `/api/node/${encodeURIComponent(nodeId)}/neighbors?limit=${neighLimit}${scopeParam}`
      );

      st.expandedSet.add(nodeId);
      const newEdges = raw.edges || [];
      const newNodes = raw.nodes || [];
      const art = {
        nodeIds: new Set<string>(),
        edgeIds: new Set<string>(),
      };

      newNodes.forEach((n) => {
        if (!st.allNodes[n.id]) st.allNodes[n.id] = n;
      });
      newEdges.forEach((e) => {
        const s = e.from || e.source;
        const t = e.to || e.target;
        if (s) st.degreeMap[s] = (st.degreeMap[s] || 0) + 1;
        if (t) st.degreeMap[t] = (st.degreeMap[t] || 0) + 1;
      });
      st.maxDeg = Math.max(1, ...Object.values(st.degreeMap));

      net.setOptions({
        physics: { enabled: true, stabilization: { enabled: false } },
      });

      const beforeEdgeIds = new Set(edgesDs.getIds());
      const baseCount = nodesDs.length;
      const expandTotal = baseCount + newNodes.length;
      const visMode = st.mode === 'persons' ? 'persons' : 'hubs';

      const toAdd: VisNode[] = [];
      let addIdx = 0;
      newNodes.forEach((n) => {
        if (!nodesDs.get(n.id)) {
          art.nodeIds.add(n.id);
          const visNode = nodeToVis(
            n,
            st.degreeMap[n.id] || 1,
            baseCount + addIdx,
            Math.max(expandTotal, 2),
            visMode,
            st
          );
          addIdx += 1;
          toAdd.push(visNode);
        }
      });
      if (toAdd.length) nodesDs.add(toAdd);

      newEdges.forEach((e) => {
        const from = e.from || e.source || '';
        const to = e.to || e.target || '';
        if (!from || !to) return;
        const pk = edgePairKey(from, to);
        if (edgesDs.get(pk)) return;
        const ev = edgeToVis(e);
        try {
          edgesDs.add(ev);
          const eid = String(ev.id);
          if (!beforeEdgeIds.has(eid)) art.edgeIds.add(eid);
        } catch {
          /* duplicate */
        }
      });
      st.expandArtifacts[nodeId] = art;

      const scale = net.getScale();
      net.setOptions({
        edges: { font: { size: scale < 0.8 ? 0 : 12 } },
      });

      setTimeout(() => {
        net.setOptions({ physics: { enabled: false } });
        fitView();
      }, 2500);

      net.selectNodes([nodeId]);
      net.focus(nodeId, {
        scale: 1.15,
        animation: { duration: 500, easingFunction: 'easeInOutQuad' },
      });

      onKpiUpdate(nodesDs.length, edgesDs.length);
      bump();
    },
    [bump, fitView, onKpiUpdate, st]
  );

  const mountDedupedGraph = useCallback(
    (
      nodes: ApiNode[],
      edges: ApiEdge[],
      modeLabel: 'query' | 'inferred'
    ) => {
      const container = containerRef.current;
      if (!container) return;

      const normalized = dedupeGraphPayload(nodes || [], edges || []);
      st.mode = 'all';
      st.allNodes = {};
      normalized.nodes.forEach((n) => {
        st.allNodes[n.id] = n;
      });
      st.allEdges = normalized.edges;
      const dm = computeDegrees(normalized.edges);
      st.degreeMap = dm;
      st.maxDeg = Math.max(
        1,
        ...(Object.values(dm).length ? Object.values(dm) : [1])
      );

      const mx = st.maxDeg;
      const opts = getVisOptions('hubs', theme);
      if (normalized.nodes.length > 300) {
        opts.physics.barnesHut!.gravitationalConstant = -10000;
        opts.physics.stabilization!.iterations = 150;
      }

      const gNodes = normalized.nodes;
      const vnodes: VisNode[] = gNodes.map((n, i) => {
        const g = ['Company', 'Person', 'Institution'].includes(n.group || '')
          ? (n.group as string)
          : 'DEFAULT';
        const d = dm[n.id] || 0;
        let sz = 10 + (d / mx) * 26;
        sz = Math.min(40, Math.max(8, sz));
        const radius = Math.max(800, gNodes.length * 5);
        const goldenAngle = Math.PI * (3 - Math.sqrt(5));
        const angle = i * goldenAngle;
        const r = radius * Math.sqrt(i / Math.max(gNodes.length, 1));
        return {
          id: n.id,
          label: n.label || n.name || String(n.id),
          group: g,
          size: sz,
          title: `${n.label || n.name || String(n.id)}\nLiên kết: ${d}`,
          x: r * Math.cos(angle),
          y: r * Math.sin(angle),
          fixed: false,
        };
      });
      const vedges = normalized.edges.map(edgeToVis);

      const visNodes = new DataSet<VisNode>(vnodes);
      const visEdges = new DataSet<VisEdge>(vedges);

      destroyNetwork();
      container.innerHTML = '';
      networkRef.current = new Network(
        container,
        { nodes: visNodes, edges: visEdges },
        opts
      );
      st.visNodes = visNodes;
      st.visEdges = visEdges;

      networkRef.current.once('stabilizationIterationsDone', () => {
        networkRef.current?.setOptions({ physics: { enabled: false } });
        fitView();
      });

      wireInteractions();
      onGraphModeLabels(modeLabel);
      onKpiUpdate(vnodes.length, vedges.length);
      bump();
    },
    [
      bump,
      containerRef,
      destroyNetwork,
      fitView,
      onGraphModeLabels,
      onKpiUpdate,
      st,
      theme,
      wireInteractions,
    ]
  );

  const drawQueryGraph = useCallback(
    (nodes: ApiNode[], edges: ApiEdge[]) => {
      mountDedupedGraph(nodes, edges, 'query');
    },
    [mountDedupedGraph]
  );

  const loadInferredGraph = useCallback(
    (nodes: ApiNode[], edges: ApiEdge[]) => {
      mountDedupedGraph(nodes, edges, 'inferred');
    },
    [mountDedupedGraph]
  );

  const loadHubsOnly = useCallback(async () => {
    const container = containerRef.current;
    if (!container) return;

    container.innerHTML =
      '<div class="graph-loader"><div class="loader-ring"></div><div class="loader-text">Đang tải…</div><div class="loader-sub"></div></div>';

    const data = await apiJson<{
      nodes: ApiNode[];
      edges: ApiEdge[];
    }>('/api/graph?mode=companies&page=1&limit=50000');

    const normalized = dedupeGraphPayload(data.nodes || [], data.edges || []);
    st.allNodes = {};
    st.allEdges = normalized.edges;
    st.expandedSet = new Set();
    st.expandArtifacts = {};
    st.initialNodeIds = new Set();
    st.mode = 'hubs';

    normalized.nodes.forEach((n) => {
      st.allNodes[n.id] = n;
      st.initialNodeIds.add(n.id);
    });
    st.degreeMap = computeDegrees(st.allEdges);
    st.maxDeg = Math.max(
      1,
      ...(Object.values(st.degreeMap).length ? Object.values(st.degreeMap) : [1])
    );

    const opts = getVisOptions('hubs', theme);
    if (normalized.nodes.length > 500) {
      opts.physics.barnesHut!.gravitationalConstant = -5000;
      opts.physics.stabilization!.iterations = 400;
    }
    const nodeList = Object.values(st.allNodes);
    const vnodes = nodeList.map((n, i) => {
      const base = nodeToVis(
        n,
        st.degreeMap[n.id] || 0,
        i,
        nodeList.length,
        'hubs',
        st
      );
      const radius = Math.max(2400, nodeList.length * 14);
      const goldenAngle = Math.PI * (3 - Math.sqrt(5));
      const angle = i * goldenAngle;
      const r = radius * Math.sqrt(i / Math.max(nodeList.length, 1));
      return {
        ...base,
        x: r * Math.cos(angle),
        y: r * Math.sin(angle),
        fixed: false,
      };
    });

    const companyEdges = st.allEdges
      .filter((e) => {
        const lbl = (e.label || e.edge_label || '').toUpperCase();
        return lbl.includes('CÔNG_TY_CON') || lbl.includes('CỔ_ĐÔNG');
      })
      .slice(0, 800);

    const visNodes = new DataSet<VisNode>(vnodes);
    const visEdges = new DataSet<VisEdge>(companyEdges.map(edgeToVis));

    destroyNetwork();
    container.innerHTML = '';
    networkRef.current = new Network(
      container,
      { nodes: visNodes, edges: visEdges },
      opts
    );
    st.visNodes = visNodes;
    st.visEdges = visEdges;

    networkRef.current.on('stabilizationProgress', (params) => {
      const pct = Math.round((params.iterations / params.total) * 100);
      const el = container.querySelector('.loader-sub');
      if (el) el.textContent = `Phân tán: ${pct}%…`;
    });

    networkRef.current.once('stabilizationIterationsDone', () => {
      container.querySelector('.graph-loader')?.remove();
      networkRef.current?.setOptions({ physics: { enabled: false } });
      fitView();
    });

    wireInteractions();
    onGraphModeLabels('companies');
    onKpiUpdate(vnodes.length, companyEdges.length);
    bump();
  }, [
    bump,
    containerRef,
    destroyNetwork,
    fitView,
    onGraphModeLabels,
    onKpiUpdate,
    st,
    theme,
    wireInteractions,
  ]);

  const loadPersonGraph = useCallback(async () => {
    const container = containerRef.current;
    if (!container) return;

    container.innerHTML =
      '<div class="graph-loader"><div class="loader-ring"></div><div class="loader-text">Đang tải…</div></div>';

    const data = await apiJson<{
      nodes: ApiNode[];
      edges: ApiEdge[];
    }>('/api/graph?mode=persons&view=leaders&page=1&limit=25000');

    const normalized = dedupeGraphPayload(data.nodes || [], data.edges || []);
    st.mode = 'persons';
    st.expandedSet = new Set();
    st.expandArtifacts = {};
    st.initialNodeIds = new Set();
    st.allNodes = {};
    st.allEdges = normalized.edges;

    normalized.nodes.forEach((n) => {
      st.allNodes[n.id] = n;
      st.initialNodeIds.add(n.id);
    });
    st.degreeMap = computeDegrees(st.allEdges);
    st.maxDeg = Math.max(
      1,
      ...(Object.values(st.degreeMap).length ? Object.values(st.degreeMap) : [1])
    );

    const opts = getVisOptions('persons', theme);
    const nodeCount = normalized.nodes.length;
    if (nodeCount > 800) {
      opts.physics.barnesHut!.gravitationalConstant = -20000;
      opts.physics.barnesHut!.centralGravity = 0.01;
      opts.physics.stabilization!.iterations = 300;
    }

    const nodeList = normalized.nodes;
    const vnodes = nodeList.map((n, i) =>
      nodeToVis(n, st.degreeMap[n.id] || 0, i, nodeList.length, 'persons', st)
    );
    const vedges = normalized.edges.map(edgeToVis);

    const visNodes = new DataSet<VisNode>(vnodes);
    const visEdges = new DataSet<VisEdge>(vedges);

    destroyNetwork();
    container.innerHTML = '';
    networkRef.current = new Network(
      container,
      { nodes: visNodes, edges: visEdges },
      opts
    );
    st.visNodes = visNodes;
    st.visEdges = visEdges;

    networkRef.current.on('stabilizationProgress', (params) => {
      const pct = Math.round((params.iterations / params.total) * 100);
      const el = container.querySelector('.loader-text');
      if (el) el.textContent = `Phân tán đồ thị… ${pct}%`;
    });

    networkRef.current.once('stabilizationIterationsDone', () => {
      container.querySelector('.graph-loader')?.remove();
      networkRef.current?.setOptions({ physics: { enabled: false } });
      fitView();
    });

    wireInteractions();
    onGraphModeLabels('persons');
    onKpiUpdate(vnodes.length, vedges.length);
    bump();
  }, [
    bump,
    containerRef,
    destroyNetwork,
    fitView,
    onGraphModeLabels,
    onKpiUpdate,
    st,
    theme,
    wireInteractions,
  ]);

  return useMemo(
    () => ({
      loadHubsOnly,
      loadPersonGraph,
      drawQueryGraph,
      loadInferredGraph,
      expandOrToggleNeighbors,
      isNodeExpanded: (id: string) => st.expandedSet.has(id),
      fitView,
      destroy: destroyNetwork,
      updateTheme,
      selectNodes: (ids: string[]) => networkRef.current?.selectNodes(ids),
      focusNode: (id: string, scale = 1.5) =>
        networkRef.current?.focus(id, {
          scale,
          animation: { duration: 600, easingFunction: 'easeInOutQuad' },
        }),
    }),
    [
      destroyNetwork,
      drawQueryGraph,
      expandOrToggleNeighbors,
      fitView,
      loadHubsOnly,
      loadInferredGraph,
      loadPersonGraph,
      st,
      updateTheme,
    ]
  );
}
