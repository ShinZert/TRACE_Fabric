// Visual descriptors for every Fabric element type.
// One source of truth for: canvas node rendering, palette thumbnails,
// inspector dropdown labels, minimap colour coding, palette tooltips,
// and the legend.
export const TYPE_STYLES = {
  humanSource: {
    label: "Human source", shape: "ellipse",
    bg: "#dbeafe", border: "#1d4ed8", borderWidth: 2,
    w: 130, h: 70, textColor: "#1e3a8a",
    description: "A person initiating, contributing to, or receiving from the workflow.",
    example: "Reviewer, applicant, customer-support agent.",
  },
  inputOutput: {
    label: "Input / output", shape: "rounded-rect",
    bg: "#f3f4f6", border: "#9ca3af", borderWidth: 2, borderStyle: "dashed",
    w: 140, h: 56, textColor: "#374151",
    description: "Data flowing into or out of a step.",
    example: "Uploaded document, model prediction, user query.",
  },
  fixedAIModel: {
    label: "AI Model\n(Trained)", shape: "hexagon",
    bg: "#ede9fe", border: "#6d28d9", borderWidth: 2,
    w: 160, h: 76, textColor: "#4c1d95",
    description: "An AI model used as-is — weights don't change in this workflow.",
    example: "GPT-4 drafting a customer reply.",
  },
  trainingAIModel: {
    label: "AI Model\n(In-training)", shape: "hexagon",
    bg: "#ede9fe", border: "#6d28d9", borderWidth: 2, borderStyle: "dashed",
    w: 160, h: 76, textColor: "#4c1d95",
    description: "An AI model that learns from or is updated by the workflow.",
    example: "Fraud-detection model retrained on labelled cases nightly.",
  },
  governanceMechanism: {
    label: "Governance", shape: "octagon",
    bg: "#fef3c7", border: "#b45309", borderWidth: 2,
    w: 150, h: 76, textColor: "#78350f",
    description: "Policy, audit, or compliance check applied to a step.",
    example: "Bias audit before deployment; PII filter on outputs.",
  },
  ui: {
    label: "User interface", shape: "tag",
    bg: "#ccfbf1", border: "#0f766e", borderWidth: 2,
    w: 140, h: 60, textColor: "#134e4a",
    description: "Interface a human uses to interact with the system.",
    example: "Reviewer dashboard, chat widget, approval screen.",
  },
  decisionPoint: {
    label: "Decision point", shape: "diamond",
    bg: "#ffffff", border: "#1d1d1f", borderWidth: 3,
    w: 140, h: 100, textColor: "#1d1d1f",
    description: "Branching point — outgoing paths go to accept / modify / reject.",
    example: "Reviewer decides whether to use the AI suggestion.",
  },
  accept: {
    label: "Accept", shape: "rounded-rect",
    bg: "#86efac", border: "#15803d", borderWidth: 2,
    w: 110, h: 44, textColor: "#14532d",
    description: "Output is approved and used as-is.",
    example: "Loan application auto-approved at the threshold.",
  },
  modify: {
    label: "Modify", shape: "rounded-rect",
    bg: "#fde68a", border: "#a16207", borderWidth: 2,
    w: 110, h: 44, textColor: "#713f12",
    description: "Output is edited by a human before being used.",
    example: "Editor revises AI-drafted summary before send.",
  },
  reject: {
    label: "Reject", shape: "rounded-rect",
    bg: "#fca5a5", border: "#b91c1c", borderWidth: 2,
    w: 110, h: 44, textColor: "#7f1d1d",
    description: "Output is discarded; usually leads to restart or an end event.",
    example: "Flagged claim sent to manual triage.",
  },
  restart: {
    label: "Restart (loop)", shape: "rounded-rect",
    bg: "#e5e7eb", border: "#6b7280", borderWidth: 2,
    w: 120, h: 50, textColor: "#374151",
    description: "Loop back to retry an earlier step with new context.",
    example: "Re-prompt the model after the reviewer's correction.",
  },
  finalOutcome: {
    label: "Final outcome", shape: "rounded-rect",
    bg: "#1d1d1f", border: "#1d1d1f", borderWidth: 2,
    w: 160, h: 60, textColor: "#ffffff",
    description: "Terminal result delivered to the user or downstream system.",
    example: "Application approved and funds disbursed.",
  },
};

export const TYPE_KEYS = Object.keys(TYPE_STYLES);

// Slug a label into a snake_case id stem, matching the schema regex
// ^[a-z][a-z0-9_]*$. Caller appends a counter for uniqueness.
export function slugifyType(ftype) {
  return ftype
    .replace(/([A-Z])/g, "_$1")
    .toLowerCase()
    .replace(/^_/, "");
}
