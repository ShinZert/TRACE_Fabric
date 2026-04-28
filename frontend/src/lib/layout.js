import dagre from "dagre";
import { TYPE_STYLES } from "./types";

// Run dagre over a React Flow node/edge set and return the nodes with
// computed positions. Layout is left-to-right.
export function layoutWithDagre(nodes, edges) {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 35, ranksep: 90, edgesep: 18 });

  nodes.forEach((n) => {
    const s = TYPE_STYLES[n.data.ftype] || { w: 140, h: 60 };
    g.setNode(n.id, { width: s.w, height: s.h });
  });
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return {
      ...n,
      position: { x: pos.x - pos.width / 2, y: pos.y - pos.height / 2 },
    };
  });
}

// ----- Trace ↔ React Flow conversion --------------------------------------

// The custom FabricEdge component renders its own label styling via
// EdgeLabelRenderer — the labelBg* props that the default React Flow edge
// understands aren't used here.
const EDGE_DEFAULTS = {
  type: "fabric",
  style: { stroke: "#9ca3af", strokeWidth: 2 },
  markerEnd: { type: "arrowclosed", color: "#9ca3af" },
};

export function traceToFlow(trace) {
  if (!trace) return { nodes: [], edges: [] };
  const nodes = (trace.elements || []).map((el) => ({
    id: el.id,
    type: "fabric",
    position: { x: 0, y: 0 },
    data: { label: el.name || "", ftype: el.type },
  }));
  const edges = (trace.flows || []).map((fl) => ({
    id: fl.id,
    source: fl.from,
    target: fl.to,
    label: fl.name || "",
    ...EDGE_DEFAULTS,
  }));
  return { nodes, edges };
}

export function flowToTrace(processName, nodes, edges) {
  return {
    process_name: processName || "Process",
    elements: nodes.map((n) => ({
      id: n.id,
      type: n.data.ftype,
      name: n.data.label || "",
    })),
    flows: edges.map((e) => ({
      id: e.id,
      from: e.source,
      to: e.target,
      ...(e.label ? { name: typeof e.label === "string" ? e.label : "" } : {}),
    })),
  };
}

export const flowEdgeDefaults = EDGE_DEFAULTS;
