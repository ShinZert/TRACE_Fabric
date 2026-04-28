import { TYPE_STYLES } from "./types";

// Mirrors the semantic checks in services/schema_validator.py. Runs entirely
// in the browser so the editor can flag problems instantly, without waiting
// for /api/sync. The backend remains authoritative — this is a UX layer.
//
// Fabric has no dedicated start-event type. The entry point is identified
// structurally as the single element with no incoming flows.

const TERMINAL_TYPES = new Set(["finalOutcome"]);

const SEVERITY = { error: "error", warning: "warning" };

function displayName(el) {
  const label = (el?.name || "").trim();
  if (label) return label;
  return TYPE_STYLES[el?.type]?.label || el?.type || "this step";
}

function buildMessage(code, ctx) {
  switch (code) {
    case "no_entry":
      return "There's no starting point — every step has something leading into it (a cycle).";
    case "multiple_entries":
      return `More than one starting point. '${ctx.label}' has nothing leading into it — connect it from another step.`;
    case "no_terminal":
      return "The diagram has no final outcome. Add a Final outcome to mark where the workflow ends.";
    case "dead_end":
      return `'${ctx.label}' has no outgoing arrow. Add a flow to the next step.`;
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

  // Empty canvas (e.g. landing page before any LLM generation) is not a
  // validation target — there is nothing for the user to fix yet.
  if (elements.length === 0) {
    return { issues, byNodeId, summary: { errorCount: 0, warningCount: 0 } };
  }

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

  // Whole-trace terminal check
  const terminals = elements.filter((e) => TERMINAL_TYPES.has(e.type));
  if (terminals.length === 0) {
    push({
      code: "no_terminal",
      severity: SEVERITY.error,
      message: buildMessage("no_terminal"),
    });
  }

  // Entry-point check: exactly one element with no incoming flows.
  const entryNodes = elements.filter((el) => (incoming.get(el.id) || 0) === 0);
  if (elements.length > 0 && entryNodes.length === 0) {
    push({
      code: "no_entry",
      severity: SEVERITY.error,
      message: buildMessage("no_entry"),
    });
  } else if (entryNodes.length > 1) {
    for (const el of entryNodes) {
      push({
        code: "multiple_entries",
        severity: SEVERITY.warning,
        nodeId: el.id,
        message: buildMessage("multiple_entries", { label: displayName(el) }),
      });
    }
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

  // Per-node connectivity for non-terminals + terminal-direction check
  for (const el of elements) {
    const label = displayName(el);
    if (!TERMINAL_TYPES.has(el.type) && (outgoing.get(el.id) || 0) === 0) {
      push({
        code: "dead_end",
        severity: SEVERITY.warning,
        nodeId: el.id,
        message: buildMessage("dead_end", { label }),
      });
    }
    if (TERMINAL_TYPES.has(el.type) && (outgoing.get(el.id) || 0) > 0) {
      push({
        code: "terminal_has_outgoing",
        severity: SEVERITY.warning,
        nodeId: el.id,
        message: buildMessage("terminal_has_outgoing", { label }),
      });
    }
  }

  // Unknown flow references — the editor prunes edges when a node is
  // deleted, but include for parity with the backend and to catch any
  // pathological state that slips through.
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
