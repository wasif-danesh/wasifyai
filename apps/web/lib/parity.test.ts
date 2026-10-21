import { CHAT_ITEM, EXTRA_ITEMS, MENU_GROUPS } from "@wasifyai/ui";
import { describe, expect, it } from "vitest";
import { resolveWebItem } from "./menu";
import { PARITY } from "./parity";
import { VOICE_SCREENS, type VoiceScreenName } from "./voice-screens";

const ids = [
  CHAT_ITEM.id,
  ...MENU_GROUPS.flatMap((g) => g.items.map((i) => i.id)),
  ...EXTRA_ITEMS.map((i) => i.id),
];

describe("the web follows the desktop's menu", () => {
  it("has a decision for every menu item, and none for an item that is gone", () => {
    expect(Object.keys(PARITY).sort()).toEqual([...ids].sort());
  });

  it("does what each decision says", () => {
    // every voice screen offered, as a deployment with models for all of them does
    const voiceScreens = Object.keys(VOICE_SCREENS) as VoiceScreenName[];
    const resolve = resolveWebItem("/", null, { voiceScreens });
    for (const id of ids) {
      const view = resolve(id);
      const row = PARITY[id];
      if (row?.status === "live") expect(view && !("hidden" in view), id).toBeTruthy();
      if (row?.status === "soon") expect(view, id).toBeUndefined();
      if (row?.status === "desktop-only") expect(view, id).toEqual({ hidden: true });
    }
  });

  it("gives every decision a reason", () => {
    for (const [id, row] of Object.entries(PARITY)) expect(row.note.length, id).toBeGreaterThan(5);
  });
});
