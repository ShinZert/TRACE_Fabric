import {
  useState, useCallback, useEffect, useMemo, useRef,
} from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  reconnectEdge,
  useReactFlow,
} from "@xyflow/react";
import { TYPE_STYLES, slugifyType } from "../lib/types";
import {
  layoutWithDagre,
  traceToFlow,
  flowToTrace,
  flowEdgeDefaults,
} from "../lib/layout";
import { toPng } from "html-to-image";
import { validateTrace } from "../lib/validate";
import { nodeTypes } from "./FabricNode";
import { edgeTypes } from "./FabricEdge";
import { LeftPalette } from "./LeftPalette";
import { Inspector } from "./Inspector";
import { EditorContext } from "./editorContext";

const HISTORY_CAP = 60;

// Shallow-equal check on element/flow IDs — used to decide whether a new
// `trace` prop should reset the editor's internal state. Catches the common
// case where the LLM returned a fresh trace without touching unrelated
// re-renders. process_name is intentionally excluded so renaming the title
// doesn't blow away manual node positions or undo history.
function traceSignature(trace) {
  if (!trace) return "";
  const els = (trace.elements || []).map((e) => `${e.id}:${e.type}`).join("|");
  const fls = (trace.flows || []).map((f) => `${f.id}:${f.from}>${f.to}`).join("|");
  return `${els}::${fls}`;
}

function EditorInner({
  trace,
  onTraceCommit,
  onSync,
  onExportJson,
  onImportJson,
  onLoadSample,
  onUploadSketch,
  onTryExamplePrompt,
  isDirty,
  isSyncing,
  syncWarnings,
  syncDisabledReason,
}) {
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editingEdgeId, setEditingEdgeId] = useState(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [mode, setMode] = useState("pan");
  const [history, setHistory] = useState({ past: [], future: [] });
  const [showIssues, setShowIssues] = useState(false);

  const idCounter = useRef(0);
  const lastTraceSig = useRef("");
  const fileInputRef = useRef(null);
  const reactFlow = useReactFlow();

  const processName = trace?.process_name || "Process";

  // Reset editor state when an incoming trace differs from what's loaded.
  useEffect(() => {
    const sig = traceSignature(trace);
    if (sig === lastTraceSig.current) return;
    lastTraceSig.current = sig;
    if (!trace) {
      setNodes([]);
      setEdges([]);
      setHistory({ past: [], future: [] });
      setSelectedId(null);
      return;
    }
    const { nodes: ns, edges: es } = traceToFlow(trace);
    setNodes(layoutWithDagre(ns, es));
    setEdges(es);
    setHistory({ past: [], future: [] });
    setSelectedId(null);
  }, [trace]);

  // ---------- helpers --------------------------------------------------
  // Pre-stamp lastTraceSig with the about-to-be-committed signature so the
  // trace-prop effect treats the round-trip as "already seen" and skips its
  // re-layout. Without this, structural local edits (reconnect, add/delete
  // edge or node) bounce the canvas back to a fresh dagre layout.
  const commit = useCallback(
    (nextNodes, nextEdges) => {
      const newTrace = flowToTrace(processName, nextNodes, nextEdges);
      lastTraceSig.current = traceSignature(newTrace);
      onTraceCommit?.(newTrace);
    },
    [onTraceCommit, processName]
  );

  const pushHistory = useCallback(() => {
    setHistory((h) => ({
      past: [...h.past, { nodes, edges }].slice(-HISTORY_CAP),
      future: [],
    }));
  }, [nodes, edges]);

  const undo = useCallback(() => {
    setHistory((h) => {
      if (h.past.length === 0) return h;
      const prev = h.past[h.past.length - 1];
      const current = { nodes, edges };
      setNodes(prev.nodes);
      setEdges(prev.edges);
      commit(prev.nodes, prev.edges);
      return {
        past: h.past.slice(0, -1),
        future: [current, ...h.future].slice(0, HISTORY_CAP),
      };
    });
  }, [nodes, edges, commit]);

  const redo = useCallback(() => {
    setHistory((h) => {
      if (h.future.length === 0) return h;
      const next = h.future[0];
      const current = { nodes, edges };
      setNodes(next.nodes);
      setEdges(next.edges);
      commit(next.nodes, next.edges);
      return {
        past: [...h.past, current].slice(-HISTORY_CAP),
        future: h.future.slice(1),
      };
    });
  }, [nodes, edges, commit]);

  // ---------- React Flow change handlers -------------------------------
  const onNodesChange = useCallback(
    (changes) => setNodes((ns) => applyNodeChanges(changes, ns)),
    []
  );
  const onEdgesChange = useCallback(
    (changes) => setEdges((es) => applyEdgeChanges(changes, es)),
    []
  );
  const onNodeDragStart = useCallback(() => {
    pushHistory();
  }, [pushHistory]);
  const onNodeDragStop = useCallback(() => {
    // Commit the post-drag positions to the canonical trace.
    commit(nodes, edges);
  }, [commit, nodes, edges]);

  // Helper: extract a side name from a handle id like "side-top".
  // Returns null for "side-auto" or anything we don't recognize.
  const sideFromHandle = (handle) => {
    if (!handle || !handle.startsWith("side-")) return null;
    const s = handle.slice(5);
    return s === "auto" ? null : s;
  };

  const onConnect = useCallback(
    (conn) => {
      pushHistory();
      const fromSide = sideFromHandle(conn.sourceHandle);
      const toSide = sideFromHandle(conn.targetHandle);
      const explicit = !!(fromSide || toSide);
      setEdges((es) => {
        const next = addEdge(
          {
            ...conn,
            id: `flow_${Date.now()}`,
            type: "fabric",
            data: { explicitSides: explicit, fromSide, toSide },
            ...flowEdgeDefaults,
          },
          es
        );
        commit(nodes, next);
        return next;
      });
    },
    [pushHistory, commit, nodes]
  );

  // Drag an existing edge endpoint onto another node to re-attach it
  // (draw.io / miro style). reconnectEdge swaps source/target/handles in
  // place so the edge id stays stable.
  const onReconnect = useCallback(
    (oldEdge, newConnection) => {
      pushHistory();
      const fromSide = sideFromHandle(newConnection.sourceHandle);
      const toSide = sideFromHandle(newConnection.targetHandle);
      const explicit = !!(fromSide || toSide);
      setEdges((es) => {
        // shouldReplaceId:false preserves the original flow_* id so the
        // schema's ^[a-z][a-z0-9_]*$ check still passes on next sync (the
        // default replaces it with React Flow's internal `xy-edge__...`).
        const reconnected = reconnectEdge(oldEdge, newConnection, es, {
          shouldReplaceId: false,
        });
        const next = reconnected.map((e) =>
          e.id === oldEdge.id
            ? {
                ...e,
                data: { ...e.data, explicitSides: explicit, fromSide, toSide },
              }
            : e
        );
        commit(nodes, next);
        return next;
      });
    },
    [pushHistory, commit, nodes]
  );

  // ---------- Drag-and-drop from the palette ---------------------------
  const onDragOver = useCallback((event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event) => {
      event.preventDefault();
      const ftype = event.dataTransfer.getData("application/fabric-type");
      if (!ftype || !TYPE_STYLES[ftype]) return;
      const flowPos = reactFlow.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      const s = TYPE_STYLES[ftype];
      const dropPos = { x: flowPos.x - s.w / 2, y: flowPos.y - s.h / 2 };

      pushHistory();
      idCounter.current += 1;
      const id = `${slugifyType(ftype)}_${Date.now().toString(36)}_${idCounter.current}`;
      const newNode = {
        id,
        type: "fabric",
        position: dropPos,
        data: { label: TYPE_STYLES[ftype].label, ftype },
      };
      setNodes((ns) => {
        const next = [...ns, newNode];
        commit(next, edges);
        return next;
      });
      setSelectedId(id);
    },
    [reactFlow, pushHistory, commit, edges]
  );

  // ---------- Inspector actions ----------------------------------------
  const handleUpdateNode = useCallback(
    (id, updates) => {
      pushHistory();
      setNodes((ns) => {
        const next = ns.map((n) =>
          n.id === id ? { ...n, data: { ...n.data, ...updates } } : n
        );
        commit(next, edges);
        return next;
      });
    },
    [pushHistory, commit, edges]
  );

  // Inline label editing (double-click a node → editable input)
  const startEdit = useCallback((id) => {
    setEditingId(id);
    setSelectedId(id);
  }, []);

  const finishEdit = useCallback(
    (id, newLabel, cancelled) => {
      setEditingId(null);
      if (cancelled) return;
      // Only commit if the label actually changed (avoids a no-op history push)
      const node = nodes.find((n) => n.id === id);
      if (!node) return;
      const next = (newLabel ?? "").trim();
      if (next === node.data.label) return;
      handleUpdateNode(id, { label: next });
    },
    [nodes, handleUpdateNode]
  );

  // ----- Edge update / delete + inline label editing ------------------
  const handleUpdateEdge = useCallback(
    (id, updates) => {
      pushHistory();
      setEdges((es) => {
        const next = es.map((e) => (e.id === id ? { ...e, ...updates } : e));
        commit(nodes, next);
        return next;
      });
    },
    [pushHistory, commit, nodes]
  );

  const handleDeleteEdge = useCallback(
    (id) => {
      pushHistory();
      setEdges((es) => {
        const next = es.filter((e) => e.id !== id);
        commit(nodes, next);
        return next;
      });
      setSelectedEdgeId(null);
    },
    [pushHistory, commit, nodes]
  );

  const startEdgeEdit = useCallback((id) => {
    setEditingEdgeId(id);
    setSelectedEdgeId(id);
  }, []);

  const finishEdgeEdit = useCallback(
    (id, newLabel, cancelled) => {
      setEditingEdgeId(null);
      if (cancelled) return;
      const edge = edges.find((e) => e.id === id);
      if (!edge) return;
      const next = (newLabel ?? "").trim();
      const current = (edge.label ?? "").trim();
      if (next === current) return;
      handleUpdateEdge(id, { label: next });
    },
    [edges, handleUpdateEdge]
  );

  const handleDeleteNode = useCallback(
    (id) => {
      pushHistory();
      setNodes((ns) => {
        const nextNodes = ns.filter((n) => n.id !== id);
        setEdges((es) => {
          const nextEdges = es.filter((e) => e.source !== id && e.target !== id);
          commit(nextNodes, nextEdges);
          return nextEdges;
        });
        return nextNodes;
      });
      setSelectedId(null);
    },
    [pushHistory, commit]
  );

  // Edge / node deletes triggered by Del/Backspace go through React Flow's
  // own onNodesChange / onEdgesChange path. We intercept post-removal to
  // commit and snapshot history.
  const onNodesDelete = useCallback(
    (deleted) => {
      pushHistory();
      const deletedIds = new Set(deleted.map((d) => d.id));
      // React Flow hides edges that point to non-existent nodes but keeps
      // them in state, so the validator would flag them as unknown_ref. Drop
      // any edge connected to a deleted node before committing.
      const nextEdges = edges.filter(
        (e) => !deletedIds.has(e.source) && !deletedIds.has(e.target)
      );
      const nextNodes = nodes.filter((n) => !deletedIds.has(n.id));
      setNodes(nextNodes);
      setEdges(nextEdges);
      commit(nextNodes, nextEdges);
    },
    [pushHistory, commit, nodes, edges]
  );
  const onEdgesDelete = useCallback(
    () => {
      pushHistory();
      // edges state is already updated by applyEdgeChanges before this fires
      commit(nodes, edges);
    },
    [pushHistory, commit, nodes, edges]
  );

  // ---------- Title rename ---------------------------------------------
  const startEditTitle = useCallback(() => {
    if (!trace) return;
    setTitleDraft(processName);
    setEditingTitle(true);
  }, [trace, processName]);

  const finishEditTitle = useCallback(
    (cancelled) => {
      setEditingTitle(false);
      if (cancelled) return;
      const next = (titleDraft || "").trim();
      if (!next || next === processName) return;
      onTraceCommit?.(flowToTrace(next, nodes, edges));
    },
    [titleDraft, processName, nodes, edges, onTraceCommit]
  );

  // ---------- Toolbar actions ------------------------------------------
  const handleRelayout = useCallback(() => {
    pushHistory();
    setNodes((ns) => {
      const next = layoutWithDagre(ns, edges);
      commit(next, edges);
      return next;
    });
  }, [edges, pushHistory, commit]);

  // ---------- Keyboard shortcuts ---------------------------------------
  useEffect(() => {
    const onKey = (e) => {
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) {
        return;
      }
      const cmd = e.ctrlKey || e.metaKey;
      if (cmd && !e.shiftKey && (e.key === "z" || e.key === "Z")) {
        e.preventDefault();
        undo();
      } else if (cmd && (e.key === "y" || e.key === "Y" || (e.shiftKey && (e.key === "z" || e.key === "Z")))) {
        e.preventDefault();
        redo();
      } else if (cmd && (e.key === "=" || e.key === "+")) {
        e.preventDefault();
        reactFlow.zoomIn({ duration: 200 });
      } else if (cmd && e.key === "-") {
        e.preventDefault();
        reactFlow.zoomOut({ duration: 200 });
      } else if (cmd && e.key === "0") {
        e.preventDefault();
        reactFlow.fitView({ duration: 300, padding: 0.15 });
      } else if (!cmd && (e.key === "v" || e.key === "V")) {
        e.preventDefault();
        setMode("select");
      } else if (!cmd && (e.key === "h" || e.key === "H")) {
        e.preventDefault();
        setMode("pan");
      } else if (!cmd && (e.key === "m" || e.key === "M")) {
        e.preventDefault();
        setMode("marquee");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo, reactFlow]);

  // Live client-side validation. The backend (services/schema_validator.py)
  // remains authoritative; this just gives instant in-canvas feedback so the
  // user can see *where* the problem is without waiting for /api/sync.
  const validation = useMemo(
    () => validateTrace(flowToTrace(processName, nodes, edges)),
    [processName, nodes, edges]
  );

  // Fold backend warnings from the last sync into the same panel that shows
  // local validation issues. They have no nodeId (the backend returns plain
  // strings), so they appear as un-revealable bullets and don't decorate any
  // node. Local validation already covers most of the same checks, so in
  // practice this list is usually empty.
  const combinedIssues = useMemo(() => {
    const extras = (syncWarnings || []).map((message, i) => ({
      code: "sync_warning",
      severity: "warning",
      message,
      key: `sync-${i}`,
    }));
    return {
      issues: [...validation.issues, ...extras],
      errorCount: validation.summary.errorCount,
      warningCount: validation.summary.warningCount + extras.length,
    };
  }, [validation, syncWarnings]);

  // Attach per-node issues for FabricNode to render its red ring + tooltip.
  // Decorated copies are passed to React Flow only — raw `nodes` state is
  // untouched so commit() / history snapshots never carry validation data
  // into the trace JSON.
  const decoratedNodes = useMemo(() => {
    if (validation.byNodeId.size === 0) return nodes;
    return nodes.map((n) => {
      const issues = validation.byNodeId.get(n.id);
      if (!issues) return n;
      return { ...n, data: { ...n.data, issues } };
    });
  }, [nodes, validation]);

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedId) || null,
    [nodes, selectedId]
  );
  const selectedEdge = useMemo(
    () => edges.find((e) => e.id === selectedEdgeId) || null,
    [edges, selectedEdgeId]
  );
  const selectedIssues = selectedNode
    ? validation.byNodeId.get(selectedNode.id) || []
    : [];

  const revealNode = useCallback(
    (nodeId) => {
      setSelectedId(nodeId);
      setSelectedEdgeId(null);
      reactFlow.fitView({
        nodes: [{ id: nodeId }],
        duration: 300,
        padding: 0.4,
      });
    },
    [reactFlow]
  );

  // Export the current diagram as a PNG. We snapshot `.react-flow` (the root,
  // not just `.react-flow__viewport`) so EdgeLabelRenderer's portaled labels
  // are included. We temporarily fitView to ensure the whole diagram is in
  // frame, capture, then restore the previous viewport.
  const handleExportPng = useCallback(async () => {
    if (nodes.length === 0) return;
    const root = document.querySelector(".react-flow");
    if (!root) return;

    const savedViewport = reactFlow.getViewport();
    reactFlow.fitView({ padding: 0.1, duration: 0 });

    // Wait for two animation frames so React Flow re-renders at the new
    // transform before html-to-image walks the DOM.
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

    try {
      const dataUrl = await toPng(root, {
        backgroundColor: "#ffffff",
        pixelRatio: 2,
        // Strip React Flow chrome (controls, minimap, attribution, panels)
        // from the screenshot so the export is just the diagram.
        filter: (el) => {
          if (!(el instanceof Element)) return true;
          if (el.classList?.contains("react-flow__panel")) return false;
          if (el.classList?.contains("react-flow__controls")) return false;
          if (el.classList?.contains("react-flow__minimap")) return false;
          if (el.classList?.contains("react-flow__background")) return false;
          return true;
        },
      });

      const a = document.createElement("a");
      a.href = dataUrl;
      a.download =
        (processName || "fabric-trace").replace(/\s+/g, "_").toLowerCase() + ".png";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } finally {
      reactFlow.setViewport(savedViewport, { duration: 0 });
    }
  }, [nodes.length, reactFlow, processName]);

  const canUndo = history.past.length > 0;
  const canRedo = history.future.length > 0;

  return (
    <div className="editor-pane">
      <div className="editor-toolbar">
        {editingTitle ? (
          <input
            autoFocus
            className="editor-title-input"
            value={titleDraft}
            onChange={(e) => setTitleDraft(e.target.value)}
            onBlur={() => finishEditTitle(false)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                finishEditTitle(false);
              } else if (e.key === "Escape") {
                e.preventDefault();
                finishEditTitle(true);
              }
            }}
          />
        ) : (
          <span
            className={"editor-title" + (trace ? " editor-title-editable" : "")}
            onClick={startEditTitle}
            title={trace ? "Click to rename" : undefined}
          >
            {processName}
          </span>
        )}
        {(isDirty || isSyncing) && (
          <span
            className={"dirty-pill" + (isSyncing ? " dirty-pill-saving" : "")}
            title={isSyncing
              ? "Saving edits to the AI session…"
              : "Editing — auto-saves shortly after you stop"}
          >
            {isSyncing ? "Saving…" : "Editing…"}
          </span>
        )}
        {combinedIssues.issues.length > 0 && (
          <button
            type="button"
            className={
              "issues-pill" +
              (combinedIssues.errorCount > 0
                ? " issues-pill-error"
                : " issues-pill-warning") +
              (showIssues ? " issues-pill-active" : "")
            }
            onClick={() => setShowIssues((s) => !s)}
            title="Show diagram issues"
          >
            {combinedIssues.issues.length === 1
              ? "1 issue"
              : `${combinedIssues.issues.length} issues`}
          </button>
        )}
        <div className="editor-toolbar-spacer" />
        <button className="btn" onClick={undo} disabled={!canUndo} title="Undo (Ctrl/Cmd+Z)">
          Undo
        </button>
        <button className="btn" onClick={redo} disabled={!canRedo} title="Redo (Ctrl/Cmd+Shift+Z)">
          Redo
        </button>
        <button className="btn" onClick={handleRelayout} disabled={nodes.length === 0}>
          Re-layout
        </button>
        <button
          className={"btn btn-primary" + (isDirty ? " btn-attention" : "")}
          onClick={onSync}
          disabled={!!syncDisabledReason || isSyncing}
          title={syncDisabledReason || "Sync edits back to the AI session"}
        >
          {isSyncing ? "Syncing…" : "Sync edits"}
        </button>
        <button
          className="btn"
          onClick={() => fileInputRef.current?.click()}
          disabled={!onImportJson}
          title="Load a Fabric trace JSON file"
        >
          Import JSON
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json,.json"
          style={{ display: "none" }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file && onImportJson) onImportJson(file);
            // Reset so picking the same file twice still fires onChange
            e.target.value = "";
          }}
        />
        <button className="btn" onClick={onExportJson} disabled={nodes.length === 0}>
          Export JSON
        </button>
        <button
          className="btn"
          onClick={handleExportPng}
          disabled={nodes.length === 0}
          title="Download the diagram as a PNG image"
        >
          Export PNG
        </button>
      </div>

      <div className="editor-body">
      <div className={`canvas-wrap mode-${mode}`}>
        <LeftPalette mode={mode} setMode={setMode} />
        <EditorContext.Provider value={{ editingId, finishEdit, editingEdgeId, finishEdgeEdit }}>
        <ReactFlow
          nodes={decoratedNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeDragStart={onNodeDragStart}
          onNodeDragStop={onNodeDragStop}
          onNodesDelete={onNodesDelete}
          onEdgesDelete={onEdgesDelete}
          onConnect={onConnect}
          onReconnect={onReconnect}
          connectionMode="loose"
          connectionLineType="smoothstep"
          onNodeClick={(_, n) => { setSelectedId(n.id); setSelectedEdgeId(null); }}
          onNodeDoubleClick={(_, n) => startEdit(n.id)}
          onEdgeClick={(_, e) => { setSelectedEdgeId(e.id); setSelectedId(null); }}
          onEdgeDoubleClick={(_, e) => startEdgeEdit(e.id)}
          onPaneClick={() => {
            setSelectedId(null);
            setSelectedEdgeId(null);
            setEditingId(null);
            setEditingEdgeId(null);
          }}
          onDragOver={onDragOver}
          onDrop={onDrop}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          deleteKeyCode={["Backspace", "Delete"]}
          proOptions={{ hideAttribution: true }}
          panOnDrag={mode === "pan"}
          selectionOnDrag={mode === "marquee"}
          selectionMode="partial"
          multiSelectionKeyCode={["Shift"]}
          zoomOnScroll
          zoomOnPinch
          zoomActivationKeyCode="Control"
          panOnScroll
        >
          <Background gap={24} size={1} color="#d2d2d7" />
          <Controls position="bottom-left" showInteractive={false} />
        </ReactFlow>
        </EditorContext.Provider>
        {showIssues && combinedIssues.issues.length > 0 && (
          <div className="issues-panel" role="dialog" aria-label="Diagram issues">
            <div className="issues-panel-header">
              <span className="issues-panel-title">
                {combinedIssues.issues.length === 1
                  ? "1 issue"
                  : `${combinedIssues.issues.length} issues`}
              </span>
              <button
                type="button"
                className="issues-panel-close"
                onClick={() => setShowIssues(false)}
                title="Close"
                aria-label="Close issues panel"
              >
                ×
              </button>
            </div>
            <ul className="issues-panel-list">
              {combinedIssues.issues.map((it, idx) => (
                <li
                  key={it.key || idx}
                  className={`issues-panel-item issues-panel-item-${it.severity}`}
                >
                  <span className="issues-panel-dot" aria-hidden="true" />
                  <span className="issues-panel-msg">{it.message}</span>
                  {it.nodeId && (
                    <button
                      type="button"
                      className="issues-panel-reveal"
                      onClick={() => revealNode(it.nodeId)}
                    >
                      Reveal
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        {nodes.length === 0 && (
          <div className="empty-state">
            <div className="empty-state-card">
              <h2 className="empty-state-title">Map an AI workflow</h2>
              <p className="empty-state-tagline">
                A Fabric trace shows how humans, AI models, and governance
                steps interact — including accept, modify, and reject
                decisions.
              </p>
              <div className="empty-state-ctas">
                {onLoadSample && (
                  <button className="btn btn-primary" onClick={onLoadSample}>
                    Load sample
                  </button>
                )}
                {onUploadSketch && (
                  <button className="btn" onClick={onUploadSketch}>
                    Upload a sketch
                  </button>
                )}
                {onTryExamplePrompt && (
                  <button className="btn" onClick={onTryExamplePrompt}>
                    Try an example prompt
                  </button>
                )}
              </div>
              <p className="empty-state-hint">
                …or describe a workflow in the chat to the left.
              </p>
            </div>
          </div>
        )}
      </div>

      <Inspector
        node={selectedNode}
        edge={selectedEdge}
        issues={selectedIssues}
        onUpdateNode={handleUpdateNode}
        onDeleteNode={handleDeleteNode}
        onUpdateEdge={handleUpdateEdge}
        onDeleteEdge={handleDeleteEdge}
      />
      </div>
    </div>
  );
}

// React Flow needs to be inside a Provider for useReactFlow() / hooks to work.
export function Editor(props) {
  return (
    <ReactFlowProvider>
      <EditorInner {...props} />
    </ReactFlowProvider>
  );
}
