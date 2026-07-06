import { useEffect, useState } from "react";
import { authStatus, login as apiLogin } from "../lib/api";

/**
 * Wraps the app behind the shared password gate. On mount it asks the backend
 * whether the gate is active (`/api/auth/status`); if it's disabled or the
 * session already cleared it, children render immediately. Otherwise it shows
 * a password screen and unlocks once `/api/login` accepts the password.
 *
 * The gate is enforced server-side (every /api/* call 401s until authed) — this
 * component is just the UI. It fails closed: if the status check errors, the
 * lock screen is shown rather than leaking the app.
 */
export function PasswordGate({ children }) {
  const [status, setStatus] = useState("checking"); // checking | locked | open
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    authStatus()
      .then((s) => {
        if (!cancelled) setStatus(!s.gate || s.authed ? "open" : "locked");
      })
      .catch(() => {
        if (!cancelled) setStatus("locked"); // fail closed
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    if (submitting || !password) return;
    setSubmitting(true);
    setError("");
    try {
      await apiLogin(password);
      setStatus("open");
    } catch (err) {
      setError(err.message || "Incorrect password");
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  if (status === "open") return children;

  if (status === "checking") {
    return (
      <div className="gate">
        <div className="gate-card gate-loading">Loading…</div>
      </div>
    );
  }

  return (
    <div className="gate">
      <form className="gate-card" onSubmit={handleSubmit}>
        <h1 className="gate-title">Weaver</h1>
        <p className="gate-subtitle">Enter the password to continue.</p>
        <input
          className="gate-input"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          autoFocus
          autoComplete="current-password"
          disabled={submitting}
        />
        {error && <div className="gate-error">{error}</div>}
        <button
          className="btn btn-primary gate-btn"
          type="submit"
          disabled={submitting || !password}
        >
          {submitting ? "Checking…" : "Unlock"}
        </button>
      </form>
    </div>
  );
}
