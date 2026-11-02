import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// ---------- types -----------------------------------------------------------

type BashResult = {
  exit_code?: number | null;
  stdout?: string;
  stderr?: string;
  error?: string;
};
type Step = { name: string; args: Record<string, unknown>; result?: BashResult };
type Turn = {
  user: string;
  answer: string;
  steps: Step[];
  error?: string | null;
  incomplete?: boolean;
};

// Ordered by the backend (newest first); the UI renders as received and never
// sorts. `updated_at` is only used to format the label.
type SessionMeta = {
  id: string;
  created_at?: string;
  updated_at?: string;
  user_turns: number;
  messages: number;
  preview?: string;
};

type SessionPayload = {
  session_id: string;
  model?: string;
  started_at?: string;
  messages: Record<string, unknown>[];
  turns: Turn[];
  warnings: string[];
};

type SseEvent = {
  type: string;
  text?: string;
  name?: string;
  args?: Record<string, unknown>;
  result?: BashResult;
  content?: string;
  message?: string;
  messages?: Record<string, unknown>[];
  session_id?: string;
};

// ---------- helpers ---------------------------------------------------------

// Local time, formatted "yyyy-mm-dd hh-mm-ss".
function fmt(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}-${p(d.getMinutes())}-${p(d.getSeconds())}`
  );
}

function sessionParam(): string | null {
  return new URLSearchParams(window.location.search).get("session");
}

// ---------- component --------------------------------------------------------

export default function App() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  // Session list (sidebar) + selection.
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const history = useRef<Record<string, unknown>[]>([]);
  const sessionIdRef = useRef<string | null>(null);

  const stepsRef = useRef<Step[]>([]);
  const answerRef = useRef("");
  const errorRef = useRef<string | undefined>(undefined);

  const bottomRef = useRef<HTMLDivElement>(null);

  function syncCurrentTurn() {
    setTurns((prev) => {
      if (prev.length === 0) return prev;
      const next = [...prev];
      const last = next[next.length - 1];
      next[next.length - 1] = {
        user: last.user,
        answer: answerRef.current,
        steps: [...stepsRef.current],
        error: errorRef.current,
      };
      return next;
    });
  }

  async function refreshSessions() {
    try {
      const resp = await fetch("/api/sessions");
      if (resp.ok) setSessions((await resp.json()).sessions ?? []);
    } catch {
      /* non-fatal: leave the list as-is */
    }
  }

  async function openSession(id: string) {
    setLoading(true);
    setLoadError(null);
    try {
      const resp = await fetch(`/api/sessions/${encodeURIComponent(id)}`);
      if (!resp.ok) throw new Error(`Could not load session (HTTP ${resp.status})`);
      const data: SessionPayload = await resp.json();
      setTurns(data.turns);
      history.current = data.messages;
      sessionIdRef.current = data.session_id;
      setSelectedId(data.session_id);
      // Deep-link: reflect the selection in the URL.
      const url = new URL(window.location.href);
      url.searchParams.set("session", data.session_id);
      window.history.replaceState(null, "", url);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  function newChat() {
    setTurns([]);
    history.current = [];
    sessionIdRef.current = null;
    setSelectedId(null);
    setLoadError(null);
    const url = new URL(window.location.href);
    url.searchParams.delete("session");
    window.history.replaceState(null, "", url);
  }

  // On mount: load the list, and auto-open ?session=<id> if present.
  useEffect(() => {
    refreshSessions();
    const id = sessionParam();
    if (id) openSession(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);

    stepsRef.current = [];
    answerRef.current = "";
    errorRef.current = undefined;

    setTurns((prev) => [...prev, { user: text, answer: "", steps: [] }]);
    history.current.push({ role: "user", content: text });

    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: history.current,
          session_id: sessionIdRef.current,
        }),
      });
      if (!resp.ok) throw new Error(`Backend returned HTTP ${resp.status}`);
      if (!resp.body) throw new Error("No response body");

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";

        for (const block of blocks) {
          const dataLine = block
            .split("\n")
            .find((line) => line.startsWith("data: "));
          if (!dataLine) continue;
          const event: SseEvent = JSON.parse(dataLine.slice(6));

          if (event.type === "session") {
            sessionIdRef.current = event.session_id ?? null;
            if (event.session_id) setSelectedId(event.session_id);
          } else if (event.type === "tool_call") {
            stepsRef.current.push({
              name: event.name ?? "",
              args: event.args ?? {},
            });
            syncCurrentTurn();
          } else if (event.type === "tool_result") {
            const last = stepsRef.current[stepsRef.current.length - 1];
            if (last) last.result = event.result;
            syncCurrentTurn();
          } else if (event.type === "answer") {
            answerRef.current = event.content ?? "";
            if (event.messages) history.current = event.messages;
            if (event.session_id) {
              sessionIdRef.current = event.session_id;
              setSelectedId(event.session_id);
            }
            syncCurrentTurn();
          } else if (event.type === "error") {
            errorRef.current = event.message ?? "Unknown error";
            syncCurrentTurn();
          }
        }

        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
      }
    } catch (err) {
      errorRef.current = err instanceof Error ? err.message : String(err);
      syncCurrentTurn();
    } finally {
      setBusy(false);
      // (Re)load the sidebar so the new/updated session sorts to the top.
      refreshSessions();
    }
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-header">Sessions</div>
        <button className="new-chat" onClick={newChat} disabled={busy}>
          + New chat
        </button>
        <ul className="session-list">
          {sessions.map((s) => (
            <li key={s.id}>
              <button
                className={`session-item${s.id === selectedId ? " active" : ""}`}
                onClick={() => openSession(s.id)}
                disabled={busy || loading}
                title={s.preview ? `${s.id}\n${s.preview}` : s.id}
              >
                <span className="session-time">{fmt(s.updated_at)}</span>
                <span className="session-id">{s.id.slice(0, 5)}</span>
              </button>
            </li>
          ))}
          {sessions.length === 0 && <li className="session-empty">No sessions yet.</li>}
        </ul>
      </aside>

      <div className="app">
        <header>
          <h1>World's Simplest Harness</h1>
          <p>
            Ask it to build something — it runs <code>bash</code> in{" "}
            <code>sample-project/</code>.
          </p>
        </header>

        <main className="chat">
          {loading && <div className="empty">Loading session…</div>}
          {loadError && <div className="bubble error">{loadError}</div>}
          {!loading && !loadError && turns.length === 0 && (
            <div className="empty">
              Try: <em>"Create a Python script that prints the first 20 Fibonacci
              numbers, then run it."</em>
            </div>
          )}

          {turns.map((turn, i) => (
            <TurnView key={i} turn={turn} />
          ))}
          <div ref={bottomRef} />
        </main>

        <footer>
          <textarea
            value={input}
            placeholder="Ask the harness to do something…"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={3}
          />
          <button onClick={send} disabled={busy || !input.trim()}>
            {busy ? "Working…" : "Send"}
          </button>
        </footer>
      </div>
    </div>
  );
}

// ---------- one turn of the conversation -------------------------------------

function TurnView({ turn }: { turn: Turn }) {
  return (
    <div className="turn">
      <div className="bubble user">
        <div className="box-header">User message</div>
        {turn.user}
      </div>

      {turn.steps.map((step, i) => (
        <div key={i} className="step">
          <div className="step-header">Tool call: {step.name}</div>
          <div className="command">
            <span className="prompt">$</span> {step.name} {JSON.stringify(step.args)}
          </div>
          {step.result && (
            <pre className="output">
              {step.result.error ? (
                <span className="stderr">{step.result.error}</span>
              ) : (
                <>
                  {step.result.stdout}
                  {step.result.stderr && (
                    <span className="stderr">{step.result.stderr}</span>
                  )}
                  <span className="exit">[exit {step.result.exit_code}]</span>
                </>
              )}
            </pre>
          )}
        </div>
      ))}

      {turn.error ? (
        <div className="bubble error">
          <div className="box-header">Error</div>
          {turn.error}
        </div>
      ) : (
        turn.answer && (
          <div className="bubble assistant">
            <div className="box-header">Assistant message</div>
            <div className="markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {turn.answer}
              </ReactMarkdown>
            </div>
          </div>
        )
      )}

      {turn.incomplete && (
        <div className="bubble incomplete">
          <div className="box-header">Note</div>
          (session ended mid-turn — no answer was recorded)
        </div>
      )}
    </div>
  );
}
