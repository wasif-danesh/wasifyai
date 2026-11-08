// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ProductModels } from "@wasifyai/contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiSend = vi.fn();
vi.mock("@/lib/api", () => ({ apiSend: (...a: unknown[]) => apiSend(...a) }));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const IMAGES: ProductModels = {
  product_id: "wasifyai-image",
  chosen: "flux2-klein-4b",
  models: [
    {
      id: "flux2-klein-4b",
      title: "FLUX.2 klein 4B",
      can: ["image.edit", "image.generate", "image.inpaint", "image.reference"],
    },
    { id: "ideogram-4", title: "Ideogram 4", can: ["image.generate"] },
  ],
};

beforeEach(() => apiSend.mockReset());
afterEach(() => vi.clearAllMocks());

describe("chooseModel (the server action)", () => {
  it("sends the model and refuses odd names before calling the API", async () => {
    const { chooseModel } = await import("../../app/(site)/admin/media/actions");
    apiSend.mockResolvedValue({ status: 200, data: IMAGES });
    const form = new FormData();
    form.set("model", "ideogram-4");
    const out = await chooseModel("wasifyai-image", { status: "idle" }, form);
    expect(out).toEqual({ status: "saved", model: "ideogram-4" });
    expect(apiSend).toHaveBeenCalledWith("PUT", "/admin/media/models/wasifyai-image", {
      model: "ideogram-4",
    });
    form.set("model", "../x");
    expect((await chooseModel("wasifyai-image", { status: "idle" }, form)).status).toBe("error");
    expect(apiSend).toHaveBeenCalledTimes(1);
  });
});

describe("MediaModelChoice", () => {
  it("shows the chosen model, says what another can do, and saves only a change", async () => {
    const { MediaModelChoice } = await import("./MediaModelChoice");
    render(<MediaModelChoice choice={IMAGES} />);
    expect(screen.getByText(/Can edit, create, inpaint, combine/)).toBeTruthy();
    const save = screen.getByRole("button", { name: "Use this model" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    await userEvent.click(screen.getByRole("combobox", { name: "Images model" }));
    await userEvent.click(screen.getByRole("option", { name: "Ideogram 4" }));
    expect(screen.getByText(/Can create\. /)).toBeTruthy();
    expect(save.disabled).toBe(false);
  });
});
