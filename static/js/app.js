// Fabric - Frontend Application

(function () {
  "use strict";

  // DOM elements
  const chatMessages = document.getElementById("chatMessages");
  const messageInput = document.getElementById("messageInput");
  const sendBtn = document.getElementById("sendBtn");
  const uploadBtn = document.getElementById("uploadBtn");
  const fileInput = document.getElementById("fileInput");
  const imagePreview = document.getElementById("imagePreview");
  const previewImg = document.getElementById("previewImg");
  const removeImage = document.getElementById("removeImage");
  const dropOverlay = document.getElementById("dropOverlay");
  const emptyState = document.getElementById("emptyState");
  const diagramTitle = document.getElementById("diagramTitle");
  const zoomInBtn = document.getElementById("zoomInBtn");
  const zoomOutBtn = document.getElementById("zoomOutBtn");
  const fitBtn = document.getElementById("fitBtn");
  const exportBtn = document.getElementById("exportBtn");
  const undoBtn = document.getElementById("undoBtn");
  const redoBtn = document.getElementById("redoBtn");
  const syncBtn = document.getElementById("syncBtn");
  const syncIndicator = document.getElementById("syncIndicator");
  const exportPngBtn = document.getElementById("exportPngBtn");
  const newSessionBtn = document.getElementById("newSessionBtn");

  // State
  let currentXml = null;
  let pendingImageBase64 = null;
  let confirmationImageBase64 = null; // Image stored for re-send on confirm
  let isProcessing = false;
  let isDirty = false;
  let isSyncing = false;
  let viewer = null;
  let baselineStackIndex = -1;

  // Initialize bpmn-js modeler
  function initModeler() {
    viewer = new BpmnJS({
      container: "#bpmn-canvas",
      keyboard: { bindTo: document },
    });

    // Track edits via command stack changes
    viewer.on("commandStack.changed", updateToolbarState);

    // Hide palette until a diagram is loaded
    hidePalette();
  }

  function hidePalette() {
    const palette = document.querySelector(".djs-palette");
    if (palette) palette.style.display = "none";
  }

  function showPalette() {
    const palette = document.querySelector(".djs-palette");
    if (palette) palette.style.display = "";
  }

  // Update toolbar button states based on command stack
  function updateToolbarState() {
    if (!viewer) return;

    try {
      const commandStack = viewer.get("commandStack");
      const canUndo = commandStack.canUndo();
      const canRedo = commandStack.canRedo();

      undoBtn.disabled = !canUndo;
      redoBtn.disabled = !canRedo;

      // Check if current stack index differs from baseline
      const currentIndex = commandStack._stackIdx;
      isDirty = currentIndex !== baselineStackIndex;
      syncBtn.disabled = !isDirty || isSyncing;

      if (isDirty) {
        syncIndicator.classList.add("active");
        syncBtn.classList.add("dirty");
      } else {
        syncIndicator.classList.remove("active");
        syncBtn.classList.remove("dirty");
      }
    } catch (e) {
      // Command stack not available yet
    }
  }

  // Render BPMN XML in the modeler
  async function renderDiagram(xml) {
    if (!viewer) initModeler();
    emptyState.style.display = "none";

    try {
      await viewer.importXML(xml);
      const canvas = viewer.get("canvas");
      canvas.zoom("fit-viewport");
      currentXml = xml;

      // Set baseline — this is the "clean" state
      const commandStack = viewer.get("commandStack");
      baselineStackIndex = commandStack._stackIdx;

      isDirty = false;
      updateToolbarState();
      showPalette();
    } catch (err) {
      console.error("Error rendering BPMN:", err);
      addMessage(
        "assistant",
        "Error rendering diagram. The generated BPMN may have issues."
      );
    }
  }

  // Add a message to the chat
  function addMessage(role, text, imageUrl) {
    const div = document.createElement("div");
    div.className = `message ${role}`;

    if (imageUrl) {
      const img = document.createElement("img");
      img.src = imageUrl;
      img.className = "image-preview";
      div.appendChild(img);
      if (text) {
        const br = document.createElement("br");
        div.appendChild(br);
      }
    }

    if (text) {
      const span = document.createElement("span");
      span.textContent = text;
      div.appendChild(span);
    }

    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
  }

  // Disable all active summary Confirm/Revise buttons
  function disableSummaryButtons() {
    document.querySelectorAll(".summary-actions").forEach(function (el) {
      el.querySelectorAll("button").forEach(function (btn) {
        btn.disabled = true;
      });
    });
  }

  // Add a summary message with inline-editable content and Confirm/Revise buttons
  function addSummaryMessage(summaryText) {
    const div = document.createElement("div");
    div.className = "message assistant";

    var originalText = summaryText;

    // Editable content area
    var content = document.createElement("div");
    content.className = "summary-content";
    content.contentEditable = "true";
    content.innerText = summaryText;
    div.appendChild(content);

    const actions = document.createElement("div");
    actions.className = "summary-actions";

    const confirmBtn = document.createElement("button");
    confirmBtn.className = "btn-confirm";
    confirmBtn.textContent = "Confirm";
    confirmBtn.addEventListener("click", function () {
      handleConfirm(content, originalText);
    });

    const reviseBtn = document.createElement("button");
    reviseBtn.className = "btn-revise";
    reviseBtn.textContent = "Revise";
    reviseBtn.addEventListener("click", function () {
      handleRevise(content, reviseBtn);
    });

    actions.appendChild(confirmBtn);
    actions.appendChild(reviseBtn);
    div.appendChild(actions);

    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
  }

  // Handle Confirm button click
  async function handleConfirm(contentEl, originalText) {
    if (isProcessing) return;
    isProcessing = true;
    sendBtn.disabled = true;
    disableSummaryButtons();

    contentEl.contentEditable = "false";

    var editedText = contentEl.innerText.trim();
    var wasEdited = editedText !== originalText;

    addMessage("user", wasEdited ? "Confirmed (with edits)" : "Confirmed");
    showTyping();

    try {
      const body = { confirm: true };
      if (confirmationImageBase64) {
        body.image_base64 = confirmationImageBase64;
      }
      if (wasEdited) {
        body.edited_summary = editedText;
      }

      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await response.json();
      removeTyping();

      if (data.error) {
        addMessage("error", "Error: " + data.error);
      } else {
        const processName = data.process_name || "Process";
        addMessage("assistant", "Generated: " + processName);
        diagramTitle.textContent = processName;

        if (data.bpmn_xml) {
          await renderDiagram(data.bpmn_xml);
        }
      }
    } catch (err) {
      removeTyping();
      addMessage("error", "Network error: " + err.message);
    }

    confirmationImageBase64 = null;
    isProcessing = false;
    sendBtn.disabled = false;
    messageInput.focus();
  }

  // Handle Revise button click — focus the editable summary for inline editing
  function handleRevise(contentEl, reviseBtn) {
    reviseBtn.disabled = true;
    contentEl.classList.add("editing");
    contentEl.focus();
  }

  // Show typing indicator
  function showTyping() {
    const div = document.createElement("div");
    div.className = "message assistant";
    div.id = "typingIndicator";
    div.innerHTML = `<div class="typing-indicator">
      <span class="loading-dot"></span>
      <span class="loading-dot"></span>
      <span class="loading-dot"></span>
    </div>`;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  // Remove typing indicator
  function removeTyping() {
    const indicator = document.getElementById("typingIndicator");
    if (indicator) indicator.remove();
  }

  // Send message to backend
  async function sendMessage() {
    const text = messageInput.value.trim();
    if (!text && !pendingImageBase64) return;
    if (isProcessing) return;

    isProcessing = true;
    sendBtn.disabled = true;
    disableSummaryButtons();

    // Show user message
    const imageUrl = pendingImageBase64
      ? `data:image/png;base64,${pendingImageBase64}`
      : null;
    addMessage("user", text, imageUrl);

    // Build request body before clearing state
    const body = { message: text };
    if (pendingImageBase64) {
      body.image_base64 = pendingImageBase64;
    }

    // Store image for potential re-send on confirm
    confirmationImageBase64 = pendingImageBase64;

    // Clear input
    messageInput.value = "";
    messageInput.style.height = "auto";
    messageInput.placeholder = "Describe a process or request changes...";
    clearImagePreview();

    // Show typing
    showTyping();

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await response.json();
      removeTyping();

      if (data.error) {
        addMessage("error", "Error: " + data.error);
      } else if (data.type === "summary") {
        // Summary flow — show summary with Confirm/Revise buttons
        addSummaryMessage(data.summary);
      } else {
        // Diagram flow — render the BPMN diagram
        const processName = data.process_name || "Process";
        addMessage("assistant", "Generated: " + processName);
        diagramTitle.textContent = processName;

        if (data.bpmn_xml) {
          await renderDiagram(data.bpmn_xml);
        }
        confirmationImageBase64 = null;
      }
    } catch (err) {
      removeTyping();
      addMessage("error", "Network error: " + err.message);
    }

    isProcessing = false;
    sendBtn.disabled = false;
    messageInput.focus();
  }

  // Sync manual diagram edits back to the AI session
  async function syncDiagram() {
    if (!viewer || !isDirty || isSyncing) return;

    isSyncing = true;
    syncBtn.disabled = true;
    syncBtn.classList.add("syncing");

    try {
      const result = await viewer.saveXML({ format: true });
      const xml = result.xml;

      const response = await fetch("/api/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bpmn_xml: xml }),
      });

      const data = await response.json();

      if (data.error) {
        addMessage("error", `Sync error: ${data.error}`);
      } else {
        currentXml = xml;
        addMessage("assistant", "Edits synced. I'll use the updated diagram for future changes.");

        if (data.warnings && data.warnings.length > 0) {
          addMessage("assistant", "Warnings: " + data.warnings.join("; "));
        }

        // Reset dirty state — reimport to clear the command stack
        await viewer.importXML(xml);
        const canvas = viewer.get("canvas");
        canvas.zoom("fit-viewport");

        // Update baseline to current (synced) state
        const commandStack = viewer.get("commandStack");
        baselineStackIndex = commandStack._stackIdx;

        isDirty = false;
      }
    } catch (err) {
      addMessage("error", `Sync failed: ${err.message}`);
    }

    isSyncing = false;
    syncBtn.classList.remove("syncing");
    updateToolbarState();
  }

  // Reset session — clear chat, diagram, and backend state
  async function resetSession() {
    if (isProcessing) return;

    try {
      await fetch("/api/reset", { method: "POST" });
    } catch (err) {
      // Continue with UI reset even if backend call fails
    }

    // Clear frontend state
    currentXml = null;
    pendingImageBase64 = null;
    confirmationImageBase64 = null;
    isDirty = false;
    baselineStackIndex = -1;

    // Clear chat messages and restore welcome message
    chatMessages.innerHTML = "";
    addMessage(
      "assistant",
      "Hi! I can help you create BPMN workflow diagrams. Describe a process in text or upload a flowchart image, and I\u2019ll generate a BPMN diagram for you. You can also ask me to modify existing diagrams."
    );

    // Reset diagram panel
    diagramTitle.textContent = "No diagram yet";
    emptyState.style.display = "";
    if (viewer) {
      viewer.destroy();
      viewer = null;
    }
    initModeler();

    // Reset input
    messageInput.value = "";
    messageInput.style.height = "auto";
    messageInput.placeholder = "Describe a workflow or ask to modify...";
    clearImagePreview();
    updateToolbarState();
  }

  // Handle image file selection
  function handleImageFile(file) {
    if (!file || !file.type.startsWith("image/")) return;

    const reader = new FileReader();
    reader.onload = function (e) {
      const base64 = e.target.result.split(",")[1];
      pendingImageBase64 = base64;
      previewImg.src = e.target.result;
      imagePreview.style.display = "inline-block";
    };
    reader.readAsDataURL(file);
  }

  // Clear image preview
  function clearImagePreview() {
    pendingImageBase64 = null;
    previewImg.src = "";
    imagePreview.style.display = "none";
  }

  // Auto-resize textarea
  function autoResize() {
    messageInput.style.height = "auto";
    messageInput.style.height =
      Math.min(messageInput.scrollHeight, 300) + "px";
  }

  // Event listeners

  // Send button
  sendBtn.addEventListener("click", sendMessage);

  // Enter to send, Shift+Enter for newline
  messageInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Auto-resize textarea
  messageInput.addEventListener("input", autoResize);

  // Upload button
  uploadBtn.addEventListener("click", function () {
    fileInput.click();
  });

  // File input change
  fileInput.addEventListener("change", function () {
    if (fileInput.files.length > 0) {
      handleImageFile(fileInput.files[0]);
    }
    fileInput.value = "";
  });

  // Remove image button
  removeImage.addEventListener("click", clearImagePreview);

  // Drag and drop
  document.addEventListener("dragenter", function (e) {
    e.preventDefault();
    dropOverlay.classList.add("active");
  });

  dropOverlay.addEventListener("dragleave", function (e) {
    e.preventDefault();
    dropOverlay.classList.remove("active");
  });

  dropOverlay.addEventListener("dragover", function (e) {
    e.preventDefault();
  });

  dropOverlay.addEventListener("drop", function (e) {
    e.preventDefault();
    dropOverlay.classList.remove("active");
    if (e.dataTransfer.files.length > 0) {
      handleImageFile(e.dataTransfer.files[0]);
    }
  });

  // Toolbar buttons — Undo / Redo / Sync
  undoBtn.addEventListener("click", function () {
    if (viewer) {
      viewer.get("commandStack").undo();
    }
  });

  redoBtn.addEventListener("click", function () {
    if (viewer) {
      viewer.get("commandStack").redo();
    }
  });

  syncBtn.addEventListener("click", syncDiagram);
  newSessionBtn.addEventListener("click", resetSession);

  // Toolbar buttons — Zoom
  zoomInBtn.addEventListener("click", function () {
    if (viewer) {
      const canvas = viewer.get("canvas");
      canvas.zoom(canvas.zoom() * 1.2);
    }
  });

  zoomOutBtn.addEventListener("click", function () {
    if (viewer) {
      const canvas = viewer.get("canvas");
      canvas.zoom(canvas.zoom() / 1.2);
    }
  });

  fitBtn.addEventListener("click", function () {
    if (viewer) {
      const canvas = viewer.get("canvas");
      canvas.zoom("fit-viewport");
    }
  });

  // Export — use saveXML to capture unsaved edits
  exportBtn.addEventListener("click", async function () {
    if (!viewer || !currentXml) {
      alert("No diagram to export. Generate a diagram first.");
      return;
    }
    try {
      const result = await viewer.saveXML({ format: true });
      const blob = new Blob([result.xml], { type: "application/xml" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = (diagramTitle.textContent || "diagram") + ".bpmn";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Export error:", err);
      alert("Failed to export diagram.");
    }
  });

  // Export PNG — render SVG to canvas, then download as PNG
  exportPngBtn.addEventListener("click", async function () {
    if (!viewer || !currentXml) {
      alert("No diagram to export. Generate a diagram first.");
      return;
    }
    try {
      const result = await viewer.saveSVG();
      const svgStr = result.svg;

      // Parse SVG to read its intrinsic dimensions
      const parser = new DOMParser();
      const svgDoc = parser.parseFromString(svgStr, "image/svg+xml");
      const svgEl = svgDoc.documentElement;

      const viewBox = svgEl.getAttribute("viewBox");
      if (!viewBox) throw new Error("SVG has no viewBox");
      const parts = viewBox.split(/[\s,]+/).map(Number);
      const svgWidth = parts[2];
      const svgHeight = parts[3];

      // Scale up for crisp output (2x)
      const scale = 2;
      const canvasWidth = svgWidth * scale;
      const canvasHeight = svgHeight * scale;

      const canvas = document.createElement("canvas");
      canvas.width = canvasWidth;
      canvas.height = canvasHeight;
      const ctx = canvas.getContext("2d");

      // White background
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvasWidth, canvasHeight);

      const img = new Image();
      const svgBlob = new Blob([svgStr], { type: "image/svg+xml;charset=utf-8" });
      const svgUrl = URL.createObjectURL(svgBlob);

      img.onload = function () {
        ctx.drawImage(img, 0, 0, canvasWidth, canvasHeight);
        URL.revokeObjectURL(svgUrl);

        canvas.toBlob(function (pngBlob) {
          const pngUrl = URL.createObjectURL(pngBlob);
          const a = document.createElement("a");
          a.href = pngUrl;
          a.download = (diagramTitle.textContent || "diagram") + ".png";
          a.click();
          URL.revokeObjectURL(pngUrl);
        }, "image/png");
      };

      img.onerror = function () {
        URL.revokeObjectURL(svgUrl);
        alert("Failed to render diagram as PNG.");
      };

      img.src = svgUrl;
    } catch (err) {
      console.error("PNG export error:", err);
      alert("Failed to export diagram as PNG.");
    }
  });

  // Initialize
  initModeler();
})();
