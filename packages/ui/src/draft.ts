// What the person typed in the chat box, carried to the tool a quick start opens (ADR-0093, stage U9): kept in the tab's session
// storage, taken once by the screen that opens. A render that runs twice (React's strict mode) gets the same words for a moment.

const KEY = "wasifyai:draft";
let taken: { text: string; at: number } | null = null;

/** Leave words for the next make screen that opens. */
export function handDraft(text: string): void {
  taken = null;
  try {
    if (text.trim()) sessionStorage.setItem(KEY, text.trim());
    else sessionStorage.removeItem(KEY);
  } catch {
    // storage can be blocked: the tool opens empty
  }
}

/** The words left for this screen, once (or "" when there are none). */
export function takeDraft(): string {
  if (taken && Date.now() - taken.at < 1000) return taken.text;
  try {
    const text = sessionStorage.getItem(KEY) ?? "";
    sessionStorage.removeItem(KEY);
    taken = text ? { text, at: Date.now() } : null;
    return text;
  } catch {
    return "";
  }
}
