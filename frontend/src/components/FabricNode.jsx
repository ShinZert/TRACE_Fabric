import { useContext, useEffect, useRef } from "react";
import { Handle, Position } from "@xyflow/react";
import { TYPE_STYLES } from "../lib/types";
import { ShapeSVG } from "../lib/shapes";
import { EditorContext } from "./editorContext";

// Custom React Flow node — one SVG shape + an HTML label overlay + four
// per-side connect handles that only appear on hover (miro/draw.io feel)
// plus an invisible whole-shape "auto" handle that anchors floating
// edges. ReactFlow runs in connectionMode="loose" so a single handle per
// side acts as both source and target. Double-click swaps the label for
// an inline input; Enter/blur commits, Escape cancels.
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
  const issues = data.issues || [];
  const hasIssues = issues.length > 0;
  const issueTitle = hasIssues ? issues.map((i) => i.message).join("\n") : undefined;
  const wrapperClassName = hasIssues ? "fabric-node-wrap fabric-node-invalid" : "fabric-node-wrap";

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

  // One handle per side. IDs `side-<name>` map to the from_side / to_side
  // values flow JSON exposes. connectionMode="loose" on the canvas lets
  // each one accept incoming connections too.
  const sides = [
    { side: "top", pos: Position.Top },
    { side: "right", pos: Position.Right },
    { side: "bottom", pos: Position.Bottom },
    { side: "left", pos: Position.Left },
  ];

  return (
    <div
      className={wrapperClassName}
      style={{ width: w, height: h, position: "relative" }}
      title={issueTitle}
    >
      <ShapeSVG ftype={data.ftype} w={w} h={h} selected={selected} />
      {labelLayer}
      {sides.map(({ side, pos }) => (
        <Handle
          key={`side-${side}`}
          id={`side-${side}`}
          type="source"
          position={pos}
          className={`fabric-handle fabric-handle-${side}`}
          title={`Drag to connect (${side})`}
        />
      ))}
    </div>
  );
}

export const nodeTypes = { fabric: FabricNode };
