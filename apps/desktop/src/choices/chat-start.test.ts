import type { ModelChoice } from "@wasifyai/ui";
import { describe, expect, it } from "vitest";
import { offerOf } from "./ChatStart";

const c = (over: Partial<ModelChoice>): ModelChoice => ({
  id: "a",
  title: "A",
  plain: "",
  tier: "also",
  state: "needs_download",
  chosen: false,
  downloadBytes: 1,
  engineBytes: 0,
  engineName: null,
  fit: null,
  fitReason: null,
  licence: "",
  commercial: "yes",
  licenceUrl: null,
  source: "app",
  ...over,
});

describe("the first-run chat offer", () => {
  it("offers the recommended model when none is in use", () => {
    const o = offerOf([c({ id: "x" }), c({ id: "best", tier: "recommended" })]);
    expect(o).toMatchObject({ finish: false, choice: { id: "best" } });
  });

  it("offers nothing when a model is in use and ready", () => {
    expect(
      offerOf([c({ chosen: true, state: "ready" }), c({ id: "b", tier: "recommended" })]),
    ).toBeNull();
  });

  it("offers to finish a chosen model that needs the engine", () => {
    const o = offerOf([
      c({ id: "mine", chosen: true, engineBytes: 3e8 }),
      c({ id: "b", tier: "recommended" }),
    ]);
    expect(o).toMatchObject({ finish: true, choice: { id: "mine" } });
  });

  it("offers nothing when there is nothing to get", () => {
    expect(offerOf([c({ state: "ready" })])).toBeNull();
  });
});
