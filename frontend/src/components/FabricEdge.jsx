import { useContext, useEffect, useRef } from "react";
import { BaseEdge, EdgeLabelRenderer, getBezierPath } from "@xyflow/react";
import { EditorContext } from "./editorContext";

// Custom edge that supports inline label editing via double-click. Uses
// React Flow's EdgeLabelRenderer to overlay an HTML element at the edge
// midpoint so we can render either a styled span or a focused input.
export function FabricEdge({
  id,
  sourceX,
  sourceY,
  sourcePosition,
  targetX,
  targetY,
  targetPosition,
  label,
  style,
  markerEnd,
  selected,
}) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition,
    targetX, targetY, targetPosition,
  });

  const ctx = useContext(EditorContext) || {};
  const { editingEdgeId, finishEdgeEdit } = ctx;
  const isEditing = editingEdgeId === id;
  const inputRef = useRef(null);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  const selectedStyle = selected
    ? { ...style, stroke: "#0a84ff", strokeWidth: 3 }
    : style;

  return (
    <>
      <BaseEdge id={id} path={edgePath} style={selectedStyle} markerEnd={markerEnd} />
      {(label || isEditing) && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: "all",
              fontSize: 11,
              fontFamily: "inherit",
            }}
          >
            {isEditing ? (
              <input
                ref={inputRef}
                className="nodrag nopan"
                defaultValue={label || ""}
                placeholder="(label)"
                onBlur={(e) => finishEdgeEdit?.(id, e.currentTarget.value, false)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    finishEdgeEdit?.(id, e.currentTarget.value, false);
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    finishEdgeEdit?.(id, null, true);
                  }
                }}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => e.stopPropagation()}
                style={{
                  background: "#ffffff",
                  border: "1px solid #0a84ff",
                  borderRadius: 4,
                  padding: "2px 8px",
                  fontSize: 11,
                  fontFamily: "inherit",
                  outline: "none",
                  minWidth: 70,
                  textAlign: "center",
                }}
              />
            ) : (
              <span
                style={{
                  background: "#fafafa",
                  padding: "2px 6px",
                  borderRadius: 3,
                  color: selected ? "#0a4cb8" : "#374151",
                  border: selected ? "1px solid #0a84ff" : "1px solid transparent",
                }}
              >
                {label}
              </span>
            )}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const edgeTypes = { fabric: FabricEdge };
