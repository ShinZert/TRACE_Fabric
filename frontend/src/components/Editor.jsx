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
  useReactFlow,
} from "@xyflow/react";
import { TYPE_STYLES, slugifyType } from "../lib/types";
import {
  layoutWithDagre,
  traceToFlow,
  flowToTrace,
  flowEdgeDefaults,
} from "../lib/layout";
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
  const commit = useCallback(
    (nextNodes, nextEdges) => {
      onTraceCommit?.(flowToTrace(processName, nextNodes, nextEdges));
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

  const onConnect = useCallback(
    (conn) => {
      pushHistory();
      setEdges((es) => {
        const next = addEdge(
          {
            ...conn,
            id: `flow_${Date.now()}`,
            type: "fabric",
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
      setNodes((ns) => {
        // applyNodeChanges has already removed them; this is just to commit
        const remainingIds = new Set(ns.map((n) => n.id));
        for (const d of deleted) remainingIds.delete(d.id);
        const next = ns.filter((n) => remainingIds.has(n.id));
        commit(next, edges);
        return next;
      });
    },
    [pushHistory, commit, edges]
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
      } else if (!cmd && (e.key === "v" || e.key === "V")) {
        e.preventDefault();
        setMode("select");
      } else if (!cmd && (e.key === "h" || e.key === "H")) {
        e.preventDefault();
        setMode("pan");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedId) || null,
    [nodes, selectedId]
  );
  const selectedEdge = useMemo(
    () => edges.find((e) => e.id === selectedEdgeId) || null,
    [edges, selectedEdgeId]
  );

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
      </div>

      <div className={`canvas-wrap mode-${mode}`}>
        <LeftPalette mode={mode} setMode={setMode} />
        <EditorContext.Provider value={{ editingId, finishEdit, editingEdgeId, finishEdgeEdit }}>
        <ReactFlow
          nodes={nodes}
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
          selectionOnDrag={mode === "select"}
          selectionMode="partial"
          multiSelectionKeyCode={["Shift"]}
          zoomOnScroll
          panOnScroll={false}
        >
          <Background gap={24} size={1} color="#d2d2d7" />
          <Controls position="bottom-left" showInteractive={false} />
        </ReactFlow>
        </EditorContext.Provider>
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
        onUpdateNode={handleUpdateNode}
        onDeleteNode={handleDeleteNode}
        onUpdateEdge={handleUpdateEdge}
        onDeleteEdge={handleDeleteEdge}
      />
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
