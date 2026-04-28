import { TYPE_STYLES } from "./types";

// Compute SVG polygon points for the non-rectangular Fabric shapes.
function polygonPoints(shape, w, h, inset) {
  switch (shape) {
    case "diamond":
      return `${w / 2},${inset} ${w - inset},${h / 2} ${w / 2},${h - inset} ${inset},${h / 2}`;
    case "hexagon": {
      const dh = w * 0.18;
      return [
        `${dh},${inset}`, `${w - dh},${inset}`,
        `${w - inset},${h / 2}`,
        `${w - dh},${h - inset}`, `${dh},${h - inset}`,
        `${inset},${h / 2}`,
      ].join(" ");
    }
    case "octagon": {
      const ow = w * 0.16, oh = h * 0.28;
      return [
        `${ow},${inset}`, `${w - ow},${inset}`,
        `${w - inset},${oh}`, `${w - inset},${h - oh}`,
        `${w - ow},${h - inset}`, `${ow},${h - inset}`,
        `${inset},${h - oh}`, `${inset},${oh}`,
      ].join(" ");
    }
    case "tag": {
      const tn = Math.min(14, w * 0.15);
      return [
        `${tn},${inset}`, `${w - inset},${inset}`,
        `${w - inset},${h - inset}`, `${tn},${h - inset}`,
        `${inset},${h / 2}`,
      ].join(" ");
    }
    default:
      return "";
  }
}

// Shared SVG renderer used by both the canvas FabricNode and the palette
// thumbnails. `miniature` shrinks the stroke + dash pattern for thumbnail use.
export function ShapeSVG({ ftype, w, h, selected, miniature }) {
  const s = TYPE_STYLES[ftype];
  if (!s) return null;
  const baseSw = miniature ? 1.5 : s.borderWidth;
  const sw = selected ? Math.max(baseSw, 3) : baseSw;
  const stroke = selected ? "#0a84ff" : s.border;
  const dash =
    s.borderStyle === "dashed" ? (miniature ? "3,2" : "6,4") : undefined;
  const inset = sw / 2;
  const common = { fill: s.bg, stroke, strokeWidth: sw, strokeDasharray: dash };

  let shape;
  switch (s.shape) {
    case "rounded-rect":
      shape = (
        <rect
          x={inset} y={inset}
          width={w - sw} height={h - sw}
          rx={miniature ? 4 : 8} ry={miniature ? 4 : 8}
          {...common}
        />
      );
      break;
    case "ellipse":
      shape = (
        <ellipse cx={w / 2} cy={h / 2}
          rx={(w - sw) / 2} ry={(h - sw) / 2}
          {...common}
        />
      );
      break;
    case "diamond":
    case "hexagon":
    case "octagon":
    case "tag":
      shape = <polygon points={polygonPoints(s.shape, w, h, inset)} {...common} />;
      break;
    default:
      shape = <rect x={inset} y={inset} width={w - sw} height={h - sw} {...common} />;
  }

  return (
    <svg
      width={w} height={h}
      style={{ position: "absolute", top: 0, left: 0, overflow: "visible" }}
    >
      {shape}
    </svg>
  );
}
