import { useState } from "react";
import { createPortal } from "react-dom";
import { TYPE_STYLES } from "../lib/types";
import { ShapeSVG } from "../lib/shapes";

// Palette is grouped into labelled sections rather than a flat 14-thumbnail
// grid. Each section maps to a chunk of the Fabric ontology so the type
// taxonomy is visible and users can locate a shape without scanning all 14.
const PALETTE_GROUPS = [
  { label: "Events",    types: ["startEvent", "endEvent"] },
  { label: "Actors",    types: ["humanSource", "ui"] },
  { label: "AI",        types: ["fixedAIModel", "trainingAIModel"] },
  { label: "Data",      types: ["inputOutput"] },
  { label: "Oversight", types: ["governanceMechanism"] },
  { label: "Decision",  types: ["decisionPoint", "accept", "modify", "reject"] },
  { label: "Outcomes",  types: ["restart", "finalOutcome"] },
];

const ICONS = {
  hand: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 11V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v0" />
      <path d="M14 10V4a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v2" />
      <path d="M10 10.5V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v8" />
      <path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15" />
    </svg>
  ),
  cursor: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z" />
      <path d="M13 13l6 6" />
    </svg>
  ),
};

export function LeftPalette({ mode, setMode }) {
  // Hovered palette item — drives the rich tooltip rendered via portal so it
  // isn't clipped by the palette's own overflow-y. `top` anchors vertically
  // to the hovered shape; `left` is the palette's right edge + a gap.
  const [hovered, setHovered] = useState(null);

  const onDragStart = (event, ftype) => {
    event.dataTransfer.setData("application/fabric-type", ftype);
    event.dataTransfer.effectAllowed = "move";
  };

  const onShapeEnter = (event, ftype) => {
    const itemRect = event.currentTarget.getBoundingClientRect();
    const palette = event.currentTarget.closest(".left-palette");
    const paletteRect = palette
      ? palette.getBoundingClientRect()
      : { right: itemRect.right };
    setHovered({
      ftype,
      top: itemRect.top + itemRect.height / 2,
      left: paletteRect.right + 10,
    });
  };

  return (
    <div className="left-palette" onMouseDown={(e) => e.stopPropagation()}>
      <div className="palette-tools">
        <button
          className={"palette-tool" + (mode === "pan" ? " active" : "")}
          title="Hand tool — drag to pan (H)"
          onClick={() => setMode("pan")}
        >
          {ICONS.hand}
        </button>
        <button
          className={"palette-tool" + (mode === "select" ? " active" : "")}
          title="Selection tool — drag to box-select (V)"
          onClick={() => setMode("select")}
        >
          {ICONS.cursor}
        </button>
      </div>
      <div className="palette-sep" />
      {PALETTE_GROUPS.map((group) => (
        <div key={group.label} className="palette-section">
          <div className="palette-section-label">{group.label}</div>
          <div className="palette-shapes">
            {group.types.map((ftype) => {
              const s = TYPE_STYLES[ftype];
              if (!s) return null;
              const mw = 26, mh = 20;
              return (
                <div
                  key={ftype}
                  className="palette-shape"
                  draggable
                  onDragStart={(e) => onDragStart(e, ftype)}
                  onMouseEnter={(e) => onShapeEnter(e, ftype)}
                  onMouseLeave={() => setHovered(null)}
                >
                  <div style={{ position: "relative", width: mw, height: mh }}>
                    <ShapeSVG ftype={ftype} w={mw} h={mh} miniature />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
      {hovered && createPortal(
        <PaletteTooltip
          ftype={hovered.ftype}
          top={hovered.top}
          left={hovered.left}
        />,
        document.body
      )}
    </div>
  );
}

function PaletteTooltip({ ftype, top, left }) {
  const s = TYPE_STYLES[ftype];
  if (!s) return null;
  return (
    <div className="palette-tooltip" style={{ top, left }}>
      <div className="palette-tooltip-label">{s.label}</div>
      {s.description && (
        <div className="palette-tooltip-desc">{s.description}</div>
      )}
      {s.example && (
        <div className="palette-tooltip-example">e.g. {s.example}</div>
      )}
      <div className="palette-tooltip-hint">Drag onto canvas</div>
    </div>
  );
}
