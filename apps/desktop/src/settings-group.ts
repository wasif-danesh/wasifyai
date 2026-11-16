// Which Settings group to show: another screen (a picker's "Set up a key", the engine smoke check) asks for one before
// it opens Settings, and the page shows it when it mounts or, already open, at once.
export type SettingsGroupId =
  | "general"
  | "keys"
  | "computer"
  | "privacy"
  | "apps"
  | "code"
  | "help";

const EVENT = "wasify:settings-group";
let wanted: SettingsGroupId | null = null;

/** Ask Settings to show `id`: kept for the page's next mount and sent to a page already open. */
export function showSettingsGroup(id: SettingsGroupId) {
  wanted = id;
  window.dispatchEvent(new CustomEvent<SettingsGroupId>(EVENT, { detail: id }));
}

/** The group asked for before the page mounted, once. */
export function takeSettingsGroup(): SettingsGroupId | null {
  const id = wanted;
  wanted = null;
  return id;
}

/** Hear the groups asked for while the page is open; returns the way to stop. */
export function onSettingsGroup(fn: (id: SettingsGroupId) => void): () => void {
  const listen = (e: Event) => {
    wanted = null;
    fn((e as CustomEvent<SettingsGroupId>).detail);
  };
  window.addEventListener(EVENT, listen);
  return () => window.removeEventListener(EVENT, listen);
}
