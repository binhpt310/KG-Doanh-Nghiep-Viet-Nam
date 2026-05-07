import type { DataSet } from 'vis-data';
import type { Edge as VisEdge, Node as VisNode } from 'vis-network';

export type GraphMode = 'hubs' | 'persons' | 'all';

export interface ApiNode {
  id: string;
  label?: string;
  name?: string;
  group?: string;
}

export interface ApiEdge {
  from?: string;
  to?: string;
  source?: string;
  target?: string;
  label?: string;
  edge_label?: string;
  inferred?: boolean;
  dashes?: boolean;
  inferred_from?: string;
  influence_level?: string;
}

export interface GraphStoreState {
  allNodes: Record<string, ApiNode>;
  allEdges: ApiEdge[];
  degreeMap: Record<string, number>;
  maxDeg: number;
  expandedSet: Set<string>;
  expandArtifacts: Record<string, { nodeIds: Set<string>; edgeIds: Set<string> }>;
  initialNodeIds: Set<string>;
  mode: GraphMode;
  /** Present while a Network is mounted */
  visNodes?: DataSet<VisNode>;
  visEdges?: DataSet<VisEdge>;
}

export function createInitialStore(): GraphStoreState {
  return {
    allNodes: {},
    allEdges: [],
    degreeMap: {},
    maxDeg: 1,
    expandedSet: new Set(),
    expandArtifacts: {},
    initialNodeIds: new Set(),
    mode: 'hubs',
  };
}
