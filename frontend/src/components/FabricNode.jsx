import { useContext, useEffect, useRef } from "react";
import { Handle, Position } from "@xyflow/react";
import { TYPE_STYLES } from "../lib/types";
import { ShapeSVG } from "../lib/shapes";
import { EditorContext } from "./editorContext";

// Custom React Flow node — one SVG shape + an HTML label overlay + two
// connection handles (left=target, right=source). Double-click swaps the
// label for an inline input; Enter/blur commits, Escape cancels.
export function FabricNode({ id, data, selected }) {
  const s = TYPE_STYLES[data.ftype];
  const { editingId, finishEdit } = useContext(EditorContext) || {};
  const isEditing = editingId === id;
  const inputRef = useRef(null);

  // Auto-focus + select-all when edit mode starts
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  if (!s) return null;
  const w = s.w, h = s.h;

  const labelLayer = isEditing ? (
    <input
      ref={inputRef}
      // `nodrag` and `nopan` are React Flow class hooks — they prevent the
      // canvas drag/pan handlers from intercepting events on this element.
      className="nodrag nopan"
      defaultValue={data.label}
      onBlur={(e) => finishEdit?.(id, e.currentTarget.value, false)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          finishEdit?.(id, e.currentTarget.value, false);
        } else if (e.key === "Escape") {
          e.preventDefault();
          finishEdit?.(id, null, true);
        }
      }}
      // Stop click/mousedown so the canvas doesn't deselect or start dragging
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      style={{
        position: "absolute",
        top: "12%",
        left: "10%",
        width: "80%",
        height: "76%",
        textAlign: "center",
        background: "#ffffff",
        color: s.textColor,
        fontFamily: "inherit",
        fontWeight: 600,
        fontSize: 12,
        lineHeight: 1.2,
        border: "1px solid #0a84ff",
        borderRadius: 4,
        outline: "none",
        padding: "2px 6px",
      }}
    />
  ) : (
    <div
      style={{
        position: "absolute",
        top: 0, left: 0, width: w, height: h,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "6px 12px",
        textAlign: "center",
        color: s.textColor,
        fontWeight: 600,
        fontSize: 12,
        lineHeight: 1.2,
        wordBreak: "break-word",
        pointerEvents: "none",
        userSelect: "none",
      }}
    >
      {data.label}
    </div>
  );

  return (
    <div style={{ width: w, height: h, position: "relative" }}>
      <ShapeSVG ftype={data.ftype} w={w} h={h} selected={selected} />
      {labelLayer}
      <Handle
        type="target"
        position={Position.Left}
        className="fabric-handle fabric-handle-target"
        title="Connect from another node"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="fabric-handle fabric-handle-source"
        title="Drag to connect"
      />
    </div>
  );
}

export const nodeTypes = { fabric: FabricNode };
