import { useRef, useState } from "react";
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
type Turn = { user: string; answer: string; steps: Step[]; error?: string };

// One event streamed from the backend. `type` is: status | tool_call | tool_result | answer | error
type SseEvent = {
  type: string;
  text?: string;
  name?: string;
  args?: Record<string, unknown>;
  result?: BashResult;
  content?: string;
  message?: string;
  messages?: Record<string, unknown>[]; // the full OpenAI-format history
};

// ---------- component --------------------------------------------------------

export default function App() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  // The OpenAI-format message history we send back every turn. The backend
  // hands us the authoritative updated list in the final "answer" event.
  const history = useRef<Record<string, unknown>[]>([]);

  // Mutable parts of the turn currently being built. We write to refs as
  // events arrive, then copy them into React state so the UI re-renders.
  const stepsRef = useRef<Step[]>([]);
  const answerRef = useRef("");
  const errorRef = useRef<string | undefined>(undefined);

  const bottomRef = useRef<HTMLDivElement>(null);

  function syncCurrentTurn() {
    setTurns((prev) => {
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
        body: JSON.stringify({ messages: history.current }),
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

        // SSE events are separated by a blank line. Keep the last (possibly
        // incomplete) chunk in the buffer.
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";

        for (const block of blocks) {
          const dataLine = block
            .split("\n")
            .find((line) => line.startsWith("data: "));
          if (!dataLine) continue;
          const event: SseEvent = JSON.parse(dataLine.slice(6));

          if (event.type === "tool_call") {
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
    }
  }

  return (
    <div className="app">
      <header>
        <h1>World's Simplest Harness</h1>
        <p>
          Ask it to build something — it runs <code>bash</code> in{" "}
          <code>sample-project/</code>.
        </p>
      </header>

      <main className="chat">
        {turns.length === 0 && (
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
    </div>
  );
}
