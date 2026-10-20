// One message that tries everything the safety rules forbid (ADR-0082 decision 4, spike CU0 section 8). The Vitest case
// (markdown-safety.test.tsx) and the browser case (apps/web/e2e/chat-next-safety.spec.ts) both render it; neither may see a
// request to the tracker, a flag set on `window`, an element made from raw HTML, or a link that is not http(s).

/** Where a hit is recorded: a request to any address under it means a picture or a diagram label was fetched. */
export const TRACKER = "http://127.0.0.1:9";
export const REMOTE = "https://evil.invalid";

export const ADVERSARIAL = [
  "Plain words, then raw HTML:",
  "",
  "<script>window.__pwned1 = 1</script>",
  `<img src="${TRACKER}/raw-img.png" onerror="window.__pwned2 = 1">`,
  `<iframe src="${REMOTE}/frame"></iframe>`,
  "<b>bold by html</b>",
  "",
  "Links:",
  "",
  "[js](javascript:window.__pwned3=1) [data](data:text/html,<script>window.__pwned4=1</script>) [vb](vbscript:msgbox)",
  "[file](file:///etc/passwd) [rel](/relative/path) [ok](https://example.com/page)",
  "",
  "Pictures:",
  "",
  `![remote](${REMOTE}/remote.png)`,
  `![loopback](${TRACKER}/loopback.png)`,
  "![inline](data:image/png;base64,iVBORw0KGgo=)",
  "",
  "```ts",
  "const answer: number = 42;",
  "```",
  "",
  "Inline math $x$ stays text, block math:",
  "",
  "$$E = mc^2$$",
  "",
  "```mermaid",
  "flowchart LR",
  "  A[Start] --> B[End]",
  "```",
  "",
  "```mermaid",
  "flowchart LR",
  `  A["<img src='${TRACKER}/label.png' onerror='window.__pwned5=1'>"] --> B[End]`,
  `  click A "javascript:window.__pwned6=1"`,
  "```",
].join("\n");
