import { TYPE_STYLES } from "../lib/types";

// Read/edit panel for the currently selected node OR edge. Empty state when
// nothing is selected. Mutations are delegated up to the editor.
export function Inspector({
  node,
  edge,
  onUpdateNode,
  onDeleteNode,
  onUpdateEdge,
  onDeleteEdge,
}) {
  if (edge) {
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
