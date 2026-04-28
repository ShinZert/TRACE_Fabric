import { useCallback, useEffect, useRef, useState } from "react";
import { ChatPanel } from "./components/ChatPanel";
import { Editor } from "./components/Editor";
import { chat, syncTrace, resetSession, traceDownloadUrl } from "./lib/api";
import { sampleTrace } from "./lib/sampleTrace";

const WELCOME_MESSAGE = {
  role: "assistant",
  text:
    "Hi! Describe an AI workflow — who initiates it, which AI models act on " +
    "it, what governance checks it, and what humans do with the output. " +
    "I'll generate a Fabric decision-trace diagram. You can also upload a " +
    "sketch.",
};

// Used by the empty-state "Try an example prompt" CTA. Touches every Fabric
// concept (human source, fixed AI, governance, decisionPoint with
// accept/modify/reject) so the user sees a representative trace on first run.
const EXAMPLE_PROMPT =
  "A bank uses an AI model to score loan applications. A compliance team " +
  "audits flagged scores for fair-lending issues before a loan officer " +
  "approves the loan, modifies the terms, or rejects the application.";

export default function App() {
  const [messages, setMessages] = useState([WELCOME_MESSAGE]);
  const [trace, setTrace] = useState(null);
  // `traceDraft` is what the editor is currently showing (may include
  // unsynced edits); `trace` is the canonical state shared with the backend.
  const [traceDraft, setTraceDraft] = useState(null);
  const [pendingImage, setPendingImage] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const chatPanelRef = useRef(null);

  const isDirty = (() => {
    if (!trace || !traceDraft) return false;
    // Cheap signature comparison — IDs + types + label + edges
    const sig = (t) =>
      JSON.stringify({
        n: t.process_name,
        e: (t.elements || []).map((x) => `${x.id}:${x.type}:${x.name}`),
        f: (t.flows || []).map((x) => `${x.id}:${x.from}>${x.to}:${x.name || ""}`),
      });
    return sig(trace) !== sig(traceDraft);
  })();

  const appendMessages = useCallback((...newMsgs) => {
    setMessages((m) => [...m, ...newMsgs]);
  }, []);

  // Mark all prior summary messages as consumed so their buttons disable.
  const consumeSummaries = useCallback(() => {
    setMessages((m) =>
      m.map((msg) => (msg.kind === "summary" ? { ...msg, consumed: true } : msg))
    );
  }, []);

  // ----- Chat send / confirm -----------------------------------------------

  const handleSend = useCallback(
    async ({ message, imageBase64, imagePreview }) => {
      if (isProcessing) return;
      consumeSummaries();
      // The user message bubble (with optional image)
      appendMessages({
        role: "user",
        text: message || (imageBase64 ? "" : ""),
        imageUrl: imagePreview || null,
      });

      // Track image for potential re-send on confirm of upcoming summary
      setPendingImage(imageBase64 || null);

      setIsProcessing(true);
      try {
        const data = await chat({ message, imageBase64 });
        if (data.type === "summary") {
          appendMessages({ kind: "summary", summary: data.summary });
        } else if (data.type === "diagram") {
          appendMessages({
            role: "assistant",
            text: `Generated: ${data.process_name || "Trace"}`,
          });
          if (data.warnings && data.warnings.length > 0) {
            appendMessages({
              role: "assistant",
              text:
                "Note — the trace has issues you may want to fix in the editor: " +
                data.warnings.join("; "),
            });
          }
          setTrace(data.trace);
          setTraceDraft(data.trace);
          setPendingImage(null);
        }
      } catch (err) {
        appendMessages({ error: true, text: `Error: ${err.message}` });
      } finally {
        setIsProcessing(false);
      }
    },
    [isProcessing, consumeSummaries, appendMessages]
  );

  const handleConfirm = useCallback(
    async (editedSummary) => {
      if (isProcessing) return;
      consumeSummaries();
      appendMessages({
        role: "user",
        text: editedSummary !== undefined ? "Confirmed (with edits)" : "Confirmed",
      });
      setIsProcessing(true);
      try {
        const data = await chat({
          confirm: true,
          imageBase64: pendingImage,
          editedSummary,
        });
        if (data.type === "diagram") {
          appendMessages({
            role: "assistant",
            text: `Generated: ${data.process_name || "Trace"}`,
          });
          if (data.warnings && data.warnings.length > 0) {
            appendMessages({
              role: "assistant",
              text:
                "Note — the trace has issues you may want to fix in the editor: " +
                data.warnings.join("; "),
            });
          }
          setTrace(data.trace);
          setTraceDraft(data.trace);
          setPendingImage(null);
        } else if (data.type === "summary") {
          appendMessages({ kind: "summary", summary: data.summary });
        }
      } catch (err) {
        appendMessages({ error: true, text: `Error: ${err.message}` });
      } finally {
        setIsProcessing(false);
      }
    },
    [isProcessing, pendingImage, consumeSummaries, appendMessages]
  );

  // ----- Editor → backend sync --------------------------------------------

  // Sync the current editor draft to the backend. When `silent` is true (the
  // auto-sync path), we skip the chat confirmation message and only surface
  // warnings/errors — successful auto-saves are communicated by the dirty
  // pill clearing on its own.
  const handleSync = useCallback(
    async ({ silent = false } = {}) => {
      if (!traceDraft || !isDirty || isSyncing) return;
      setIsSyncing(true);
      try {
        const data = await syncTrace(traceDraft);
        setTrace(data.trace);
        setTraceDraft(data.trace);
        const hasWarnings = data.warnings && data.warnings.length > 0;
        if (!silent) {
          const warnLine = hasWarnings
            ? ` Warnings: ${data.warnings.join("; ")}.`
            : "";
          appendMessages({
            role: "assistant",
            text: "Edits synced. I'll use the updated trace for future changes." + warnLine,
          });
        } else if (hasWarnings) {
          appendMessages({
            role: "assistant",
            text: `Auto-saved with warnings: ${data.warnings.join("; ")}.`,
          });
        }
      } catch (err) {
        if (!silent) {
          appendMessages({ error: true, text: `Sync failed: ${err.message}` });
        }
        // Silent failures stay quiet — the dirty pill will remain visible
        // and the next idle window will retry, or the user can hit the
        // manual Sync button to surface the error.
      } finally {
        setIsSyncing(false);
      }
    },
    [traceDraft, isDirty, isSyncing, appendMessages]
  );

  // Auto-sync on idle: 2s after the last editor change, push the draft to
  // the backend so the LLM always sees the current state. The manual "Sync
  // edits" button is still available as a force-now affordance.
  useEffect(() => {
    if (!isDirty || isProcessing || isSyncing || !traceDraft) return;
    const timer = setTimeout(() => {
      handleSync({ silent: true });
    }, 2000);
    return () => clearTimeout(timer);
  }, [isDirty, isProcessing, isSyncing, traceDraft, handleSync]);

  const handleReset = useCallback(async () => {
    if (isProcessing) return;
    try {
      await resetSession();
    } catch {
      /* fall through — clear UI even if server call fails */
    }
    setMessages([WELCOME_MESSAGE]);
    setTrace(null);
    setTraceDraft(null);
    setPendingImage(null);
  }, [isProcessing]);

  // ----- Load an example trace without going through the LLM -------------
  // Useful both as user-facing onboarding (here's what Fabric traces look
  // like) and to skip the chat round-trip while iterating on the editor.

  const handleLoadSample = useCallback(async () => {
    if (isProcessing) return;
    setTrace(sampleTrace);
    setTraceDraft(sampleTrace);
    setMessages([
      {
        role: "assistant",
        text:
          `Loaded an example: "${sampleTrace.process_name}". ` +
          "Try editing nodes (double-click to rename), dragging from the palette, " +
          "or ask me to modify the trace. Click 'New' above to start fresh.",
      },
    ]);
    setPendingImage(null);
    // Best-effort sync to the backend so subsequent chat-edits operate on
    // the sample. The editor still works locally if this fails.
    try {
      await syncTrace(sampleTrace);
    } catch {
      /* ignore */
    }
  }, [isProcessing]);

  // ----- Empty-state CTAs --------------------------------------------------

  const handleUploadSketch = useCallback(() => {
    chatPanelRef.current?.triggerImageUpload();
  }, []);

  const handleTryExamplePrompt = useCallback(() => {
    if (isProcessing) return;
    handleSend({ message: EXAMPLE_PROMPT });
  }, [isProcessing, handleSend]);

  // ----- Import ------------------------------------------------------------

  const handleImportJson = useCallback(
    async (file) => {
      if (isProcessing) return;
      let parsed;
      try {
        const text = await file.text();
        parsed = JSON.parse(text);
      } catch (err) {
        appendMessages({ error: true, text: `Import failed: ${err.message}` });
        return;
      }
      if (
        !parsed ||
        typeof parsed !== "object" ||
        !Array.isArray(parsed.elements) ||
        !Array.isArray(parsed.flows)
      ) {
        appendMessages({
          error: true,
          text: "Import failed: file does not look like a Fabric trace (expected an object with `elements` and `flows` arrays).",
        });
        return;
      }
      setTrace(parsed);
      setTraceDraft(parsed);
      setMessages([
        {
          role: "assistant",
          text:
            `Imported "${parsed.process_name || "trace"}". ` +
            "Edit in the canvas, or describe changes in chat.",
        },
      ]);
      setPendingImage(null);
      try {
        await syncTrace(parsed);
      } catch {
        /* editor still works locally if sync fails */
      }
    },
    [isProcessing, appendMessages]
  );

  // ----- Export ------------------------------------------------------------

  const handleExportJson = useCallback(() => {
    const t = traceDraft || trace;
    if (!t) return;
    const url = traceDownloadUrl(t);
    const a = document.createElement("a");
    a.href = url;
    a.download = (t.process_name || "fabric-trace").replace(/\s+/g, "_").toLowerCase() + ".json";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }, [trace, traceDraft]);

  return (
    <div className="app">
      <ChatPanel
        ref={chatPanelRef}
        messages={messages}
        isProcessing={isProcessing}
        onSend={handleSend}
        onConfirm={handleConfirm}
        onReset={handleReset}
      />
      <Editor
        trace={traceDraft}
        onTraceCommit={setTraceDraft}
        onSync={handleSync}
        onExportJson={handleExportJson}
        onImportJson={handleImportJson}
        onLoadSample={handleLoadSample}
        onUploadSketch={handleUploadSketch}
        onTryExamplePrompt={handleTryExamplePrompt}
        isDirty={isDirty}
        isSyncing={isSyncing}
        syncDisabledReason={
          !traceDraft
            ? "No trace yet"
            : !isDirty
              ? "No unsynced edits"
              : null
        }
      />
    </div>
  );
}
