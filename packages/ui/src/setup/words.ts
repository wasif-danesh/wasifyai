// The words of a group's setup card (ADR-0109), in one place so they can be translated and tested. The engine says
// what a group needs (`SetupGroup`); these say it to a person.
import type { SetupGroup, SetupPart } from "@wasifyai/client";
import { formatBytes } from "../notebook/format";
import { CHAT_ITEM, EXTRA_ITEMS, MENU_GROUPS } from "../shell/menu";

const GROUP_LABEL: Record<string, string> = {
  chat: "Chat",
  lipsync: "Lip sync",
  ...Object.fromEntries(MENU_GROUPS.map((g) => [g.id, g.label])),
  ...Object.fromEntries(EXTRA_ITEMS.map((i) => [i.id, i.label])),
};

const ITEM_LABEL: Record<string, string> = {
  [CHAT_ITEM.id]: "Chat",
  ...Object.fromEntries(MENU_GROUPS.flatMap((g) => g.items.map((i) => [i.id, i.label]))),
  ...Object.fromEntries(EXTRA_ITEMS.map((i) => [i.id, i.label])),
};

export function groupLabel(id: string): string {
  return GROUP_LABEL[id] ?? id;
}

export function itemLabel(id: string): string {
  return ITEM_LABEL[id] ?? id;
}

/** "Video and Voice", "Images, Video and Voice" */
export function joinWords(words: string[]): string {
  if (words.length <= 1) return words[0] ?? "";
  return `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
}

const gb = (bytes: number) => Math.round((bytes / 1e9) * 10) / 10;

/** The biggest memory a part of the group needs, in GB. */
function biggest(group: SetupGroup): number {
  return Math.max(0, ...group.parts.map((p) => p.memory_bytes ?? 0));
}

/** What the card says under its heading. */
export function whyLine(group: SetupGroup): string {
  const label = groupLabel(group.id);
  const mem = group.memory_bytes ? gb(group.memory_bytes) : null;
  const need = gb(biggest(group));
  if (group.key.only && mem)
    return `${label} needs about ${need} GB of memory and this computer has ${mem} GB, so it runs on a cloud model with your API key.`;
  if (group.key.first && mem && group.id !== "chat")
    return `${label} needs about ${need} GB of memory, most of this computer's ${mem} GB, so an API key is recommended. You can still download it.`;
  if (group.key.first && group.id === "chat")
    return "A chat model would take most of this computer's memory, so an API key is recommended. You can still download one.";
  const items = group.items;
  const left = items.filter((i) => i.state === "left_out" || i.state === "unavailable");
  const partly = items.filter((i) => i.state === "partly");
  if (left.length || partly.length) {
    const ready = items.length - left.length;
    let s = `${label}: ${ready} of ${items.length} ready on this computer.`;
    if (left.length)
      s += ` ${joinWords(left.map((i) => itemLabel(i.id)))} needs a bigger computer.`;
    if (partly.length)
      s += ` ${joinWords(partly.map((i) => itemLabel(i.id)))} works, but part of it needs a bigger computer.`;
    return s;
  }
  return items.length > 1
    ? `Sets up all ${items.length} items of ${label}. Runs on this computer, privately.`
    : "Runs on this computer, privately.";
}

/** " It also uses Video and Voice: the button sets them up too." */
export function usesLine(group: SetupGroup): string {
  if (!group.uses.length) return "";
  return ` It also uses ${joinWords(group.uses.map(groupLabel))}: the button sets them up too.`;
}

/** What one part's row says on the right. */
export function partStatus(part: SetupPart, keyFirst: boolean, chatBytes: number | null): string {
  if (part.set_up) return "✓ set up";
  if (part.installing) return "setting up";
  if (!part.available) return part.reason || "not on this computer";
  if (keyFirst) return "not needed with a key";
  if (!part.included) return "needs a bigger computer";
  if (part.kind === "chat")
    return chatBytes === null
      ? "chosen for this computer"
      : chatBytes === 0
        ? "already on this computer"
        : formatBytes(chatBytes);
  return formatBytes(part.bytes);
}

/** The total the main button shows: the group's download, and the chat model's when it is part of it. */
export function downloadTotal(
  group: SetupGroup,
  chatBytes: number | null,
  instead = false,
): number {
  const chat = group.parts.some((p) => p.kind === "chat" && !p.set_up && p.included)
    ? (chatBytes ?? 0)
    : 0;
  return (instead ? group.download_instead_bytes : group.download_bytes) + chat;
}

export function primaryLabel(group: SetupGroup, chatBytes: number | null): string {
  if (group.key.first) return "Use an API key";
  const names = [groupLabel(group.id), ...group.uses.map(groupLabel)];
  return `Set up ${joinWords(names)} · ${formatBytes(downloadTotal(group, chatBytes))}`;
}

export function insteadLabel(group: SetupGroup, chatBytes: number | null): string | null {
  if (!group.key.first || group.key.only) return null;
  return `Download instead · ${formatBytes(downloadTotal(group, chatBytes, true))}`;
}
