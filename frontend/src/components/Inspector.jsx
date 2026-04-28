import { TYPE_STYLES } from "../lib/types";

// Read/edit panel for the currently selected node OR edge. Empty state when
// nothing is selected. Mutations are delegated up to the editor.
export function Inspector({
  node,
  edge,
  issues = [],
  onUpdateNode,
  onDeleteNode,
  onUpdateEdge,
  onDeleteEdge,
}) {
  if (edge) {
    const fromSide = edge.data?.explicitSides ? edge.data?.fromSide || "" : "";
    const toSide = edge.data?.explicitSides ? edge.data?.toSide || "" : "";

    const setSide = (which, value) => {
      const explicitFrom = which === "from" ? value : fromSide;
      const explicitTo = which === "to" ? value : toSide;
      const explicit = !!(explicitFrom || explicitTo);
      onUpdateEdge(edge.id, {
        sourceHandle: `side-${explicitFrom || "right"}`,
        targetHandle: `side-${explicitTo || "left"}`,
        data: {
          ...edge.data,
          explicitSides: explicit,
          fromSide: explicitFrom || null,
          toSide: explicitTo || null,
        },
      });
    };

    return (
      <div className="inspector">
        <label>Edge ID</label>
        <div className="inspector-readonly">{edge.id}</div>

        <label>From → To</label>
        <div className="inspector-readonly">
          {edge.source} → {edge.target}
        </div>

        <label>Label (optional condition)</label>
        <input
          type="text"
          value={edge.label || ""}
          onChange={(e) => onUpdateEdge(edge.id, { label: e.target.value })}
          placeholder="e.g., Accept, Modify, Yes, No"
        />

        <label>From side</label>
        <select
          value={fromSide}
          onChange={(e) => setSide("from", e.target.value)}
        >
          <option value="">Auto</option>
          <option value="top">Top</option>
          <option value="right">Right</option>
          <option value="bottom">Bottom</option>
          <option value="left">Left</option>
        </select>

        <label>To side</label>
        <select
          value={toSide}
          onChange={(e) => setSide("to", e.target.value)}
        >
          <option value="">Auto</option>
          <option value="top">Top</option>
          <option value="right">Right</option>
          <option value="bottom">Bottom</option>
          <option value="left">Left</option>
        </select>

        <button
          className="btn btn-danger inspector-delete"
          onClick={() => onDeleteEdge(edge.id)}
        >
          Delete edge
        </button>
      </div>
    );
  }

  if (!node) {
    return null;
  }

  return (
    <div className="inspector">
      {issues.length > 0 && (
        <div className="inspector-issues" role="alert">
          <div className="inspector-issues-title">
            {issues.length === 1 ? "Issue" : `${issues.length} issues`}
          </div>
          <ul className="inspector-issues-list">
            {issues.map((it, idx) => (
              <li key={idx} className={`inspector-issue inspector-issue-${it.severity}`}>
                {it.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <label>ID</label>
      <div className="inspector-readonly">{node.id}</div>

      <label>Type</label>
      <select
        value={node.data.ftype}
        onChange={(e) => onUpdateNode(node.id, { ftype: e.target.value })}
      >
        {Object.entries(TYPE_STYLES).map(([k, s]) => (
          <option key={k} value={k}>{s.label}</option>
        ))}
      </select>

      <label>Label</label>
      <input
        type="text"
        value={node.data.label}
        onChange={(e) => onUpdateNode(node.id, { label: e.target.value })}
        placeholder="(empty)"
      />

      <button
        className="btn btn-danger inspector-delete"
        onClick={() => onDeleteNode(node.id)}
      >
        Delete node
      </button>
    </div>
  );
}
