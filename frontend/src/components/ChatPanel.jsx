import { useState, useRef, useEffect, forwardRef, useImperativeHandle } from "react";

// One chat-message bubble.
function MessageBubble({ role, text, imageUrl, error }) {
  const cls = error ? "message error" : `message ${role}`;
  return (
    <div className={cls}>
      {imageUrl && (
        <img src={imageUrl} alt="user upload" className="message-image" />
      )}
      {text && <span>{text}</span>}
    </div>
  );
}

// Editable summary message with Confirm / Revise controls.
function SummaryMessage({ summary, onConfirm, onRevise, disabled }) {
  const [text, setText] = useState(summary);
  const [editing, setEditing] = useState(false);
  const ref = useRef(null);

  const handleConfirm = () => {
    onConfirm(text !== summary ? text : undefined);
  };
  const handleRevise = () => {
    setEditing(true);
    setTimeout(() => ref.current?.focus(), 0);
    onRevise?.();
  };

  return (
    <div className="message assistant summary">
      <div
        ref={ref}
        className={"summary-content" + (editing ? " editing" : "")}
        contentEditable={editing && !disabled}
        suppressContentEditableWarning
        onBlur={(e) => setText(e.currentTarget.innerText)}
      >
        {summary}
      </div>
      <div className="summary-actions">
        <button className="btn btn-primary" onClick={handleConfirm} disabled={disabled}>
          Confirm
        </button>
        <button className="btn" onClick={handleRevise} disabled={disabled || editing}>
          Revise
        </button>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="message assistant typing">
      <span className="dot" />
      <span className="dot" />
      <span className="dot" />
    </div>
  );
}

export const ChatPanel = forwardRef(function ChatPanel({
  messages,
  isProcessing,
  onSend,
  onConfirm,
  onReset,
}, ref) {
  const [text, setText] = useState("");
  const [imageBase64, setImageBase64] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);
  const messagesRef = useRef(null);
  const textareaRef = useRef(null);

  // Lets App's empty-state CTA reuse the existing image picker.
  useImperativeHandle(ref, () => ({
    triggerImageUpload: () => fileInputRef.current?.click(),
  }), []);

  // Auto-scroll to bottom on new messages.
  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
    }
  }, [messages]);

  // Auto-resize textarea up to ~300px.
  const handleTextChange = (e) => {
    setText(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 300) + "px";
  };

  const handleSubmit = () => {
    if (isProcessing) return;
    const trimmed = text.trim();
    if (!trimmed && !imageBase64) return;
    onSend({ message: trimmed, imageBase64, imagePreview });
    setText("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setImageBase64(null);
    setImagePreview(null);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const readFile = (file) => {
    if (!file || !file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const dataUrl = ev.target.result;
      setImagePreview(dataUrl);
      setImageBase64(String(dataUrl).split(",")[1] || null);
    };
    reader.readAsDataURL(file);
  };

  const onFileChange = (e) => {
    if (e.target.files?.[0]) readFile(e.target.files[0]);
    e.target.value = "";
  };

  const onDragEnter = (e) => {
    e.preventDefault();
    setDragActive(true);
  };
  const onDragLeave = (e) => {
    e.preventDefault();
    setDragActive(false);
  };
  const onDragOver = (e) => e.preventDefault();
  const onDrop = (e) => {
    e.preventDefault();
    setDragActive(false);
    if (e.dataTransfer.files?.[0]) readFile(e.dataTransfer.files[0]);
  };

  return (
    <div className="chat-panel" onDragEnter={onDragEnter}>
      {dragActive && (
        <div
          className="drop-overlay"
          onDragLeave={onDragLeave}
          onDragOver={onDragOver}
          onDrop={onDrop}
        >
          Drop image to attach
        </div>
      )}

      <div className="chat-header">
        <div className="chat-header-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <span>Weaver</span>
        </div>
        <button className="btn btn-ghost" onClick={onReset} title="Start a new session">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="1 4 1 10 7 10" />
            <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
          </svg>
          New
        </button>
      </div>

      <div className="chat-messages" ref={messagesRef}>
        {messages.map((m, i) => {
          if (m.kind === "summary") {
            return (
              <SummaryMessage
                key={i}
                summary={m.summary}
                disabled={m.consumed || isProcessing}
                onConfirm={(editedSummary) => onConfirm(editedSummary, m)}
              />
            );
          }
          return (
            <MessageBubble
              key={i}
              role={m.role}
              text={m.text}
              imageUrl={m.imageUrl}
              error={m.error}
            />
          );
        })}
        {isProcessing && <TypingIndicator />}
      </div>

      <div className="chat-input-area">
        {imagePreview && (
          <div className="image-preview-pill">
            <img src={imagePreview} alt="upload preview" />
            <button
              className="image-preview-remove"
              onClick={() => {
                setImagePreview(null);
                setImageBase64(null);
              }}
            >
              ×
            </button>
          </div>
        )}
        <div className="input-row">
          <button
            className="btn btn-icon"
            onClick={() => fileInputRef.current?.click()}
            title="Attach image"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <polyline points="21 15 16 10 5 21" />
            </svg>
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={onFileChange}
            style={{ display: "none" }}
          />
          <textarea
            ref={textareaRef}
            value={text}
            onChange={handleTextChange}
            onKeyDown={handleKeyDown}
            placeholder="Describe an AI workflow or ask to modify…"
            rows={1}
            disabled={isProcessing}
          />
          <button
            className="btn btn-icon btn-primary"
            onClick={handleSubmit}
            disabled={isProcessing || (!text.trim() && !imageBase64)}
            title="Send"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
        <p className="privacy-notice">
          Privacy notice: This is an academic prototype. We process the
          information you provide (e.g., text and uploaded files) only to run
          the tool and troubleshoot issues. We may use service providers
          (e.g., hosting, AI model providers) to operate the tool. Please
          avoid uploading sensitive personal data. We do not store your
          inputs on our servers after processing.
        </p>
      </div>
    </div>
  );
});
