import { TYPE_STYLES } from "./types";

// Mirrors the semantic checks in services/schema_validator.py. Runs entirely
// in the browser so the editor can flag problems instantly, without waiting
// for /api/sync. The backend remains authoritative — this is a UX layer.

const END_TYPES = new Set(["endEvent", "finalOutcome"]);

const SEVERITY = { error: "error", warning: "warning" };

function displayName(el) {
  const label = (el?.name || "").trim();
  if (label) return label;
  return TYPE_STYLES[el?.type]?.label || el?.type || "this step";
}

function buildMessage(code, ctx) {
  switch (code) {
    case "no_start":
      return "The diagram is missing a start event.";
    case "multiple_starts":
      return "More than one start event — keep just one.";
    case "no_terminal":
      return "The diagram has no end. Add an End or Final outcome.";
    case "orphan":
      return `Nothing leads into '${ctx.label}'. Connect another step to it.`;
    case "dead_end":
      return `'${ctx.label}' has no outgoing arrow. Add a flow to the next step.`;
    case "start_has_incoming":
      return "The start event shouldn't have arrows leading into it.";
    case "terminal_has_outgoing":
      return `'${ctx.label}' is an end node — remove its outgoing arrow.`;
    case "duplicate_id":
      return `Two elements share the id '${ctx.id}'.`;
    case "unknown_ref":
      return "An arrow points to a step that doesn't exist.";
    default:
      return "Unknown issue.";
  }
}

export function validateTrace(trace) {
  const issues = [];
  const byNodeId = new Map();
  const elements = trace?.elements || [];
  const flows = trace?.flows || [];

  const elementIds = new Set(elements.map((e) => e.id));
  const incoming = new Map();
  const outgoing = new Map();
  for (const el of elements) {
    incoming.set(el.id, 0);
    outgoing.set(el.id, 0);
  }
  for (const f of flows) {
    if (outgoing.has(f.from)) outgoing.set(f.from, outgoing.get(f.from) + 1);
    if (incoming.has(f.to)) incoming.set(f.to, incoming.get(f.to) + 1);
  }

  const push = (issue) => {
    issues.push(issue);
    if (issue.nodeId) {
      const list = byNodeId.get(issue.nodeId) || [];
      list.push(issue);
      byNodeId.set(issue.nodeId, list);
    }
  };

  // Whole-trace checks
  const startEvents = elements.filter((e) => e.type === "startEvent");
  if (startEvents.length === 0) {
    push({ code: "no_start", severity: SEVERITY.error, message: buildMessage("no_start") });
  } else if (startEvents.length > 1) {
    // Flag every start event so each gets a visual cue
    for (const el of startEvents) {
      push({
        code: "multiple_starts",
        severity: SEVERITY.error,
        nodeId: el.id,
        message: buildMessage("multiple_starts"),
      });
    }
  }

  const terminals = elements.filter((e) => END_TYPES.has(e.type));
  if (terminals.length === 0) {
    push({ code: "no_terminal", severity: SEVERITY.error, message: buildMessage("no_terminal") });
  }

  // Duplicate ids
  const seen = new Set();
  for (const el of elements) {
    if (seen.has(el.id)) {
      push({
        code: "duplicate_id",
        severity: SEVERITY.error,
        nodeId: el.id,
        message: buildMessage("duplicate_id", { id: el.id }),
      });
    }
    seen.add(el.id);
  }

  // Per-node connectivity
  for (const el of elements) {
    const label = displayName(el);
    if (el.type !== "startEvent" && (incoming.get(el.id) || 0) === 0) {
      push({
        code: "orphan",
        severity: SEVERITY.warning,
        nodeId: el.id,
        message: buildMessage("orphan", { label }),
      });
    }
    if (!END_TYPES.has(el.type) && (outgoing.get(el.id) || 0) === 0) {
      push({
        code: "dead_end",
        severity: SEVERITY.warning,
        nodeId: el.id,
        message: buildMessage("dead_end", { label }),
      });
    }
    if (el.type === "startEvent" && (incoming.get(el.id) || 0) > 0) {
      push({
        code: "start_has_incoming",
        severity: SEVERITY.warning,
        nodeId: el.id,
        message: buildMessage("start_has_incoming"),
      });
    }
    if (END_TYPES.has(el.type) && (outgoing.get(el.id) || 0) > 0) {
      push({
        code: "terminal_has_outgoing",
        severity: SEVERITY.warning,
        nodeId: el.id,
        message: buildMessage("terminal_has_outgoing", { label }),
      });
    }
  }

  // Unknown flow references — in practice React Flow drops dangling edges
  // before they reach state, but include for parity with the backend.
  for (const f of flows) {
    if (!elementIds.has(f.from) || !elementIds.has(f.to)) {
      push({
        code: "unknown_ref",
        severity: SEVERITY.error,
        edgeId: f.id,
        message: buildMessage("unknown_ref"),
      });
    }
  }

  let errorCount = 0;
  let warningCount = 0;
  for (const i of issues) {
    if (i.severity === SEVERITY.error) errorCount++;
    else warningCount++;
  }

  return { issues, byNodeId, summary: { errorCount, warningCount } };
}
