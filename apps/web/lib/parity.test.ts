import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
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

const repo = (path: string) => fileURLToPath(new URL(`../../../${path}`, import.meta.url));

describe("the release gate", () => {
  it("lets a gap through only when someone accepted it", () => {
    for (const [id, row] of Object.entries(PARITY)) {
      if (row.status === "live") continue;
      expect(
        row.accepted?.length ?? 0,
        `${id} is not live and nobody accepted that`,
      ).toBeGreaterThan(20);
    }
  });

  it("holds the desktop's actions to the same rows", () => {
    const { actions } = JSON.parse(readFileSync(repo("docs/contracts/actions.json"), "utf8")) as {
      actions: { id: string; ui: string | null; ui_exempt: string }[];
    };
    expect(actions.length).toBeGreaterThan(30);
    for (const a of actions) {
      if (a.ui === null) {
        expect(a.ui_exempt.length, `${a.id} has no menu item and no reason`).toBeGreaterThan(10);
      } else {
        // the screen an action stands for has a decision, and a gap in it is an accepted one
        expect(PARITY[a.ui], `${a.id} names the menu item ${a.ui}, which has no row`).toBeDefined();
      }
    }
  });

  it("keeps the ledger page in step with the rows", () => {
    const table = [
      "| Menu item | Web | Why | Accepted |",
      "|---|---|---|---|",
      ...Object.entries(PARITY).map(
        ([id, r]) => `| \`${id}\` | ${r.status} | ${r.note} | ${r.accepted ?? ""} |`,
      ),
    ].join("\n");
    const path = repo("docs/web-parity-ledger.md");
    const page = readFileSync(path, "utf8");
    const [head, rest] = page.split("<!-- parity:start -->\n");
    const [, tail] = (rest ?? "").split("<!-- parity:end -->");
    expect(rest, "the ledger has no generated section").toBeDefined();
    const next = `${head}<!-- parity:start -->\n${table}\n<!-- parity:end -->${tail}`;
    if (process.env.UPDATE_LEDGER) writeFileSync(path, next);
    else
      expect(
        page,
        "the ledger is out of date: UPDATE_LEDGER=1 pnpm --filter web exec vitest run lib/parity.test.ts",
      ).toBe(next);
  });
});
