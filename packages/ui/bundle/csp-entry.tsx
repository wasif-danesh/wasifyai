// What the content-security-policy check opens (apps/web/e2e/chat-csp.spec.ts): the new chat with a scripted engine, served under the
// desktop window's real policy. `?hostile=1` answers with the adversarial message, otherwise with a harmless one that uses everything
// (code, maths, a diagram). Not part of the app.
import { createRoot } from "react-dom/client";
import { ChatScreen } from "../src/chat/ChatScreen";
import { ADVERSARIAL } from "../src/chat/thread/markdown/adversarial";

const GOOD = [
  "Some **words**, a [link](https://example.com), and:",
  "",
  "```ts",
  "const answer: number = 42;",
  "```",
  "",
  "$$E = mc^2$$",
  "",
  "```mermaid",
  "flowchart LR",
  "  A[Start] --> B[End]",
  "```",
].join("\n");

const text = new URLSearchParams(location.search).get("hostile") ? ADVERSARIAL : GOOD;
const RUN = "5b6c1c1e-0000-4000-8000-000000000001";
const frame = (seq: number, event: string, data: object) =>
  ({ event, data: { run_id: RUN, thread_id: "t", seq, ts: "", ...data } }) as never;

const runs = {
  startRun: async (_p: string, _i: object, _s: AbortSignal, on: (e: never) => void) => {
    on(frame(1, "token", { node: "agent", text }));
    on(frame(2, "done", { outputs: { status: "done", conversation_id: "c1", title: "t" } }));
  },
  watchRun: async () => {},
};
const assistant = { list: async () => [], get: async () => ({}) } as never;

const root = document.getElementById("root");
if (root)
  createRoot(root).render(<ChatScreen runs={runs} assistant={assistant} images={{} as never} />);
