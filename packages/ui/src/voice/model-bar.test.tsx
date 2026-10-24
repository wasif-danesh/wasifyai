// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModelChoicesProvider } from "../models";
import type { ChoicesApi } from "../models";
import { WindowBarProvider } from "../window-bar";
import { ModelPicker } from "./ModelPicker";

const api: ChoicesApi = {
  list: async () => ({ choices: [], diskFreeBytes: 500e9, memoryBytes: 64e9 }),
  choose: async () => {},
  get: async () => {},
};

describe("where the model button of a voice screen goes", () => {
  it("is in the window's top bar, not in the body, like the chat and image screens", () => {
    const bar = document.createElement("div");
    document.body.append(bar);
    const { container } = render(
      <WindowBarProvider bar={{ target: bar, claim: () => () => {} }}>
        <ModelChoicesProvider source={() => api}>
          <ModelPicker models={[]} task="speak" value={null} onChange={() => {}} />
        </ModelChoicesProvider>
      </WindowBarProvider>,
    );
    expect(within(bar).getByRole("button", { name: /Select voice model/ })).toBeInTheDocument();
    expect(within(container).queryByRole("button", { name: /Select voice model/ })).toBeNull();
    expect(within(container).queryByText("Model")).toBeNull(); // no label left in the body
  });

  it("is the plain list in the body where there is no picker (the web)", () => {
    render(<ModelPicker models={[]} task="speak" value={null} onChange={() => {}} />);
    expect(screen.getByLabelText("Model")).toBeInTheDocument();
  });
});

describe("the same place on the web, which has no window bar", () => {
  it("is a bar at the top of the screen", async () => {
    const { TopBarSlot } = await import("../window-bar");
    render(
      <ModelChoicesProvider source={() => api}>
        <TopBarSlot>
          <ModelPicker models={[]} task="speak" value={null} onChange={() => {}} />
        </TopBarSlot>
      </ModelChoicesProvider>,
    );
    const bar = await screen.findByTestId("top-bar");
    expect(
      await within(bar).findByRole("button", { name: /Select voice model/ }),
    ).toBeInTheDocument();
  });
});
