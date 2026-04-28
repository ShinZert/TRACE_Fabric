import dagre from "dagre";
import { TYPE_STYLES } from "./types";

// Run dagre over a React Flow node/edge set and return the nodes with
// computed positions. Layout is left-to-right.
export function layoutWithDagre(nodes, edges) {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 30, ranksep: 90, edgesep: 15 });

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
// understands aren't used here. `interactionWidth` widens the invisible hit
// area along each edge's path so converging arrows are easier to click
// individually, even where their final segments share a pixel.
const EDGE_DEFAULTS = {
  type: "fabric",
  style: { stroke: "#9ca3af", strokeWidth: 2 },
  markerEnd: { type: "arrowclosed", color: "#9ca3af" },
  interactionWidth: 36,
};

const SIDES = new Set(["top", "right", "bottom", "left"]);

export function traceToFlow(trace) {
  if (!trace) return { nodes: [], edges: [] };
  const nodes = (trace.elements || []).map((el) => ({
    id: el.id,
    type: "fabric",
    position: { x: 0, y: 0 },
    data: { label: el.name || "", ftype: el.type },
  }));
  const edges = (trace.flows || []).map((fl) => {
    const fromSide = SIDES.has(fl.from_side) ? fl.from_side : null;
    const toSide = SIDES.has(fl.to_side) ? fl.to_side : null;
    const explicit = !!(fromSide || toSide);
    return {
      id: fl.id,
      source: fl.from,
      target: fl.to,
      // Anchor to a per-side handle so React Flow's reconnect anchors line
      // up with the visible line endpoint. Auto defaults to LR (right →
      // left) which matches dagre's layout direction. Spreading edges
      // across other sides was tried but produced U-loops when targets
      // weren't actually above/below the source — the wider
      // interactionWidth covers the click-detection problem instead.
      sourceHandle: fromSide ? `side-${fromSide}` : "side-right",
      targetHandle: toSide ? `side-${toSide}` : "side-left",
      label: fl.name || "",
      data: { explicitSides: explicit, fromSide, toSide },
      ...EDGE_DEFAULTS,
    };
  });
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
    flows: edges.map((e) => {
      const flow = { id: e.id, from: e.source, to: e.target };
      if (e.label) flow.name = typeof e.label === "string" ? e.label : "";
      if (e.data?.explicitSides) {
        if (e.data.fromSide) flow.from_side = e.data.fromSide;
        if (e.data.toSide) flow.to_side = e.data.toSide;
      }
      return flow;
    }),
  };
}

export const flowEdgeDefaults = EDGE_DEFAULTS;
