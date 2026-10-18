// A small thing one screen hands to the next through the tab's session storage: a recipe sent to Create
// ("Make it again") or a result sent to Edit ("Edit this result"). Read once, then forgotten.
export function putHandoff(key: string, value: unknown): void {
  try {
    sessionStorage.setItem(`wasifyai:handoff:${key}`, JSON.stringify(value));
  } catch {
    // storage can be unavailable (private mode); the next screen simply starts empty
  }
}

export function takeHandoff<T>(key: string): T | null {
  try {
    const name = `wasifyai:handoff:${key}`;
    const raw = sessionStorage.getItem(name);
    sessionStorage.removeItem(name);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}
