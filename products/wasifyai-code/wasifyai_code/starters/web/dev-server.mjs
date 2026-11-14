// A small server for working on this project: it serves the files of this folder to this computer only, and
// tells the open page to load again when a file changes. It needs nothing installed.
//
//   npm run dev            (PORT and HOST are read when they are set)
import { watch } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";

const ROOT = resolve(".");
const PORT = Number(process.env.PORT) || 5173;
const HOST = process.env.HOST || "127.0.0.1";
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
};
const RELOAD = `<script>new EventSource("/__changes").onmessage = () => location.reload();</script>`;
const listeners = new Set();

function inside(path) {
  const full = resolve(join(ROOT, normalize(decodeURIComponent(path))));
  return full === ROOT || full.startsWith(ROOT + sep) ? full : null;
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url, "http://localhost");
  if (url.pathname === "/__changes") {
    response.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
    response.write(": open\n\n");
    listeners.add(response);
    request.on("close", () => listeners.delete(response));
    return;
  }
  let file = inside(url.pathname);
  try {
    if (file && (await stat(file)).isDirectory()) file = join(file, "index.html");
    if (!file) throw new Error("outside the project");
    let body = await readFile(file);
    const type = TYPES[extname(file).toLowerCase()] ?? "application/octet-stream";
    if (type.startsWith("text/html")) body = Buffer.from(body.toString().replace("</body>", `${RELOAD}</body>`));
    response.writeHead(200, { "content-type": type, "cache-control": "no-store" });
    response.end(body);
  } catch {
    response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    response.end("Not found");
  }
});

let timer = null;
watch(ROOT, { recursive: true }, (_event, name) => {
  if (!name || name.startsWith("node_modules") || name.startsWith(".git")) return;
  clearTimeout(timer);
  timer = setTimeout(() => {
    for (const listener of listeners) listener.write("data: changed\n\n");
  }, 80);
});

server.listen(PORT, HOST, () => {
  console.log(`Serving this project at http://${HOST}:${PORT}/`);
});
