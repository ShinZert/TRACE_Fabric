import { describe, expect, test } from "vitest";
import { traceToFlow, flowToTrace, layoutWithDagre } from "../layout";

const sample = {
  process_name: "Test",
  elements: [
    { id: "start", type: "humanSource", name: "Operator" },
    { id: "task1", type: "fixedAIModel", name: "Do It" },
    { id: "end", type: "finalOutcome", name: "Done" },
  ],
  flows: [
    { id: "f1", from: "start", to: "task1" },
    { id: "f2", from: "task1", to: "end" },
  ],
};

describe("traceToFlow / flowToTrace", () => {
  test("round-trips a simple trace", () => {
    const { nodes, edges } = traceToFlow(sample);
    const back = flowToTrace(sample.process_name, nodes, edges);
    expect(back.process_name).toBe("Test");
    expect(back.elements).toHaveLength(3);
    expect(back.flows).toHaveLength(2);
    expect(back.elements[1]).toEqual({ id: "task1", type: "fixedAIModel", name: "Do It" });
    expect(back.flows[0]).toMatchObject({ id: "f1", from: "start", to: "task1" });
  });

  test("traceToFlow returns empty arrays for null trace", () => {
    expect(traceToFlow(null)).toEqual({ nodes: [], edges: [] });
  });

  test("explicit handle sides survive the round trip", () => {
    const withSides = {
      ...sample,
      flows: [
        { id: "f1", from: "start", to: "task1", from_side: "bottom", to_side: "top" },
        { id: "f2", from: "task1", to: "end" },
      ],
    };
    const { nodes, edges } = traceToFlow(withSides);
    const back = flowToTrace("Test", nodes, edges);
    expect(back.flows[0].from_side).toBe("bottom");
    expect(back.flows[0].to_side).toBe("top");
    expect(back.flows[1].from_side).toBeUndefined();
    expect(back.flows[1].to_side).toBeUndefined();
  });
});

describe("layoutWithDagre", () => {
  test("assigns numeric positions to all nodes", () => {
    const { nodes, edges } = traceToFlow(sample);
    const positioned = layoutWithDagre(nodes, edges);
    expect(positioned).toHaveLength(3);
    positioned.forEach((n) => {
      expect(typeof n.position.x).toBe("number");
      expect(typeof n.position.y).toBe("number");
      expect(Number.isFinite(n.position.x)).toBe(true);
      expect(Number.isFinite(n.position.y)).toBe(true);
    });
  });

  test("LR layout puts start left of end", () => {
    const { nodes, edges } = traceToFlow(sample);
    const positioned = layoutWithDagre(nodes, edges);
    const start = positioned.find((n) => n.id === "start");
    const end = positioned.find((n) => n.id === "end");
    expect(start.position.x).toBeLessThan(end.position.x);
  });
});
