// What the web app's /api calls get back in the browser checks. Pictures are small inline SVGs, so nothing is
// fetched and every run draws the same pixels.
import type { Page, Route } from "@playwright/test";

const svg = (a: string, b: string) =>
  `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="768" height="768" viewBox="0 0 768 768"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs><rect width="768" height="768" fill="url(#g)"/><circle cx="384" cy="330" r="120" fill="rgba(255,255,255,.35)"/></svg>`,
  )}`;

const NOW = Date.now();
const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString();

export const IMAGES = [
  ["i1", "A lighthouse on a cliff at sunrise, soft watercolour", "#f59e0b", "#7c3aed", true],
  ["i2", "A cosy reading nook with a sleeping cat", "#10b981", "#1d4ed8", false],
  ["i3", "A paper-craft city at night, glowing windows", "#ec4899", "#0f172a", false],
].map(([id, prompt, a, b, favourite], n) => ({
  id,
  prompt,
  mode: "text",
  width: 1024,
  height: 1024,
  created_at: hoursAgo(n + 1),
  image_url: svg(a as string, b as string),
  thumb_url: svg(a as string, b as string),
  recipe: { v: 1, mode: "text", prompt, size: "square", width: 1024, height: 1024, seed: 1000 + n },
  favourite,
}));

/** The tasks the mocked service has a ready model for: every voice screen is offered. */
const VOICE_TASKS = [
  "speak",
  "transcribe",
  "design",
  "clone",
  "convert",
  "edit",
  "music",
  "separate",
  "lipsync",
];

/** A model the voice screens list, one per task. */
const VOICE_MODEL = (task: string) => ({
  id: `hosted-${task}`,
  title: `Model for ${task}`,
  licence: "provider terms",
  engine: "remote",
  family: "hosted",
  tasks: [task],
  recommended: [task],
  languages: ["en"],
  sample_rate: 24000,
  commercial_use: "yes",
  licence_evidence: "https://openrouter.ai/terms",
  reviewed: "2026-10-18",
  measured: { platform: "hosted", speed_x: null, memory_gb: null, load_s: null },
  voices: [{ id: "alloy", label: "Alloy", language: "en", gender: "female" }],
  default_voice: "alloy",
  options: [],
  music: {},
  state: "ready",
  size_bytes: 0,
  note: "",
});

export const VIDEOS = [
  {
    id: "v1",
    prompt: "A red fox walks through fresh snow at dawn",
    status: "done",
    color: ["#fb923c", "#0369a1"],
  },
  {
    id: "v2",
    prompt: "Waves roll onto a quiet beach at sunset",
    status: "working",
    color: ["#06b6d4", "#1e3a8a"],
  },
  {
    id: "v3",
    prompt: "A paper boat floats down a rain-soaked street",
    status: "failed",
    color: ["#64748b", "#0f172a"],
  },
].map((v, n) => ({
  id: v.id,
  prompt: v.prompt,
  mode: "text",
  status: v.status,
  seconds: 2,
  created_at: hoursAgo(n + 1),
  width: v.status === "done" ? 768 : null,
  height: v.status === "done" ? 512 : null,
  error: v.status === "failed" ? "This took too long and was stopped. Please try again." : null,
  video_url: v.status === "done" ? "data:video/mp4;base64," : null,
  poster_url: v.status === "done" ? svg(v.color[0] as string, v.color[1] as string) : null,
}));

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

export const NOTEBOOK_ID = "0f3c1a527a494d1e9a318f1d5b6c7d80";
export const NOTEBOOKS = [
  [NOTEBOOK_ID, "Launch plan", 3, 3],
  ["1a2b3c4d5e6f4a1b8c9d0e1f2a3b4c5d", "Thesis reading", 5, 4],
  ["2b3c4d5e6f7a4b2c9d0e1f2a3b4c5d6e", "Trip to Lisbon", 0, 0],
].map(([id, title, sources, ready], n) => ({
  id,
  title,
  created_at: hoursAgo(n * 30 + 5),
  updated_at: hoursAgo(n * 30 + 5),
  opened_at: null,
  sources,
  ready,
  reading: (sources as number) - (ready as number),
  failed: 0,
}));

export const SOURCES = [
  ["s1", "budget-2026.pdf", "file", ".pdf", 412_000, "ready"],
  ["s2", "launch-notes.md", "file", ".md", 3_100, "ready"],
  ["s3", "Idea: second supplier", "note", null, 180, "ready"],
].map(([id, title, kind, suffix, size, status], n) => ({
  id,
  notebook_id: NOTEBOOK_ID,
  folder_id: null,
  title,
  kind,
  status,
  error: null,
  mime: kind === "file" ? "application/octet-stream" : null,
  suffix,
  size_bytes: size,
  pages: kind === "file" ? 3 : null,
  created_at: hoursAgo(n + 2),
  updated_at: hoursAgo(n + 2),
}));

export const CHATS = [
  { id: "0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80", title: "A poem about a fox" },
  { id: "1a2b3c4d-5e6f-4a1b-8c9d-0e1f2a3b4c5d", title: "Plan for the launch" },
].map((c, n) => ({ ...c, created_at: hoursAgo(n + 2), updated_at: hoursAgo(n + 2) }));

/** One finished run, as the server-sent events the screens read. */
export function sseDone(outputs: Record<string, unknown>, node: string): string {
  const frame = (seq: number, event: string, data: object) =>
    `id: ${seq}\nevent: ${event}\ndata: ${JSON.stringify({ run_id: "r1", thread_id: "t1", seq, ts: "", ...data })}\n\n`;
  return (
    frame(1, "node", { node, status: "started", label: "Working" }) +
    frame(2, "done", { outputs: { status: "done", ...outputs } })
  );
}

/** Answer every /api call the image and video screens make. */
export async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = route.request().method();

    if (path === "/products/wasifyai-image/images" && method === "GET") {
      return json(route, { images: IMAGES, next_before: null });
    }
    const image = /^\/products\/wasifyai-image\/images\/(\w+)$/.exec(path);
    if (image && method === "GET") {
      const found = IMAGES.find((i) => i.id === image[1]);
      return found ? json(route, found) : json(route, { detail: "image not found" }, 404);
    }
    if (path === "/products/wasifyai-video/videos" && method === "GET") {
      const status = url.searchParams.get("status");
      return json(route, {
        videos: VIDEOS.filter((v) => !status || v.status === status),
        next_before: null,
      });
    }
    if (path === "/products/wasifyai-voice/models" && method === "GET") {
      const task = url.searchParams.get("task");
      return json(route, { models: (task ? [task] : VOICE_TASKS).map(VOICE_MODEL) });
    }
    if (path === "/products/wasifyai-voice/runtime") return json(route, { hosted: true });
    if (path === "/products/wasifyai-voice/lipsync-engine") {
      return json(route, {
        installed: true,
        source: "managed",
        running: false,
        plan: { supported: true, platform: "mock", commit: "", bytes: 0, uv: true },
        install: { state: "ready", step: null, message: "", done_bytes: 0, total_bytes: 0 },
      });
    }
    if (path.startsWith("/products/wasifyai-voice/") && method === "GET") {
      return json(route, { items: [] });
    }
    const nbase = "/products/wasifyai-notebooks";
    if (path === `${nbase}/notebooks` && method === "GET") return json(route, NOTEBOOKS);
    const notebook = new RegExp(`^${nbase}/notebooks/(\\w+)(/.*)?$`).exec(path);
    if (notebook && method === "GET") {
      const [, id, rest = ""] = notebook;
      const found = NOTEBOOKS.find((n) => n.id === id);
      if (!found) return json(route, { detail: "notebook not found" }, 404);
      if (rest === "") return json(route, found);
      if (rest === "/documents") return json(route, SOURCES);
      if (rest === "/folders" || rest === "/conversations" || rest === "/artifacts") {
        return json(route, []);
      }
      if (rest === "/guide") return json(route, { guide: null, stale: false, ready: false });
    }
    if (path === "/products/wasifyai-assistant/conversations" && method === "GET") {
      return json(route, { conversations: CHATS });
    }
    const chat = /^\/products\/wasifyai-assistant\/conversations\/([\w-]+)$/.exec(path);
    if (chat && method === "GET") {
      const found = CHATS.find((c) => c.id === chat[1]);
      if (!found) return json(route, { detail: "conversation not found" }, 404);
      const part = (text: string) => [{ type: "text", text }];
      return json(route, {
        ...found,
        messages: [
          {
            id: "m1",
            seq: 1,
            role: "user",
            created_at: found.created_at,
            parts: part("Write a short poem about a fox."),
          },
          {
            id: "m2",
            seq: 2,
            role: "assistant",
            created_at: found.created_at,
            parts: part(
              "A fox in the snow, quiet and bright,\nleaves small footprints into the night.",
            ),
          },
        ],
      });
    }
    if (path === "/products/wasifyai-assistant/runs") {
      const frame = (seq: number, event: string, data: object) =>
        `id: ${seq}\nevent: ${event}\ndata: ${JSON.stringify({ run_id: "r1", thread_id: "t1", seq, ts: "", ...data })}\n\n`;
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          frame(1, "node", { node: "agent", status: "started", label: "Thinking" }) +
          frame(2, "token", {
            node: "agent",
            text: "A fox is a small, quick wild dog with a bushy tail.",
          }) +
          frame(3, "done", {
            outputs: { status: "done", conversation_id: CHATS[0]?.id, title: CHATS[0]?.title },
          }),
      });
    }
    if (path === "/products/wasifyai-image/runs") {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseDone(
          {
            image_id: "i1",
            image_url: IMAGES[0]?.image_url,
            thumb_url: IMAGES[0]?.thumb_url,
            width: 1024,
            height: 1024,
            prompt: IMAGES[0]?.prompt,
            mode: "text",
          },
          "generate_image",
        ),
      });
    }
    if (path === "/products/wasifyai-video/runs") {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseDone(
          {
            video_id: "v1",
            video_url: "data:video/mp4;base64,",
            poster_url: VIDEOS[0]?.poster_url,
            width: 768,
            height: 512,
            seconds: 2,
            prompt: VIDEOS[0]?.prompt,
            mode: "text",
          },
          "generate_video",
        ),
      });
    }
    return json(route, { detail: `not mocked: ${method} ${path}` }, 404);
  });
}
