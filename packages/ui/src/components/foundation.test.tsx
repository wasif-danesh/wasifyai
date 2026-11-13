// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImageIcon } from "lucide-react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { ActionsRow } from "./actions-row";
import { Checkbox } from "./checkbox";
import { EmptyState } from "./empty-state";
import { ErrorNotice, plainError } from "./error-notice";
import { Experts } from "./experts";
import { Field } from "./field";
import { Player } from "./player";
import { RadioGroup } from "./radio-group";
import { RecentStrip } from "./recent-strip";
import { Segmented } from "./segmented";
import { Select } from "./select";
import { Slider } from "./slider";
import { Stage } from "./stage";
import { Stepper } from "./stepper";

// Radix's pointer handling needs these in jsdom
beforeAll(() => {
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
  window.HTMLMediaElement.prototype.play = vi.fn(async () => {});
  window.HTMLMediaElement.prototype.pause = vi.fn();
});

describe("Field", () => {
  it("wires the label, the hint and the error to the control", () => {
    render(
      <Field label="Name" hint="Short is best." error="Say something.">
        {({ id, describedBy, invalid }) => (
          <input id={id} aria-describedby={describedBy} aria-invalid={invalid} />
        )}
      </Field>,
    );
    const box = screen.getByLabelText("Name");
    expect(box).toHaveAccessibleDescription("Short is best. Say something.");
    expect(box).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Say something.");
  });
});

describe("Select", () => {
  it("lists the options with their hints and tells the change", async () => {
    const onChange = vi.fn();
    render(
      <Select
        aria-label="Voice"
        value="heart"
        onValueChange={onChange}
        options={[
          { value: "heart", label: "Heart", hint: "warm" },
          { value: "sky", label: "Sky", hint: "bright" },
        ]}
      />,
    );
    const trigger = screen.getByRole("combobox", { name: "Voice" });
    expect(trigger).toHaveTextContent("Heart");
    await userEvent.click(trigger);
    await userEvent.click(await screen.findByRole("option", { name: /Sky/ }));
    expect(onChange).toHaveBeenCalledWith("sky");
  });
});

describe("Checkbox and RadioGroup", () => {
  it("are labelled and report a choice", async () => {
    const onCheck = vi.fn();
    const onPick = vi.fn();
    render(
      <>
        <Checkbox
          checked={false}
          onCheckedChange={onCheck}
          label="Keep the music"
          hint="behind the voice"
        />
        <RadioGroup
          label="Whose picture"
          value="me"
          onValueChange={onPick}
          options={[
            { value: "me", label: "Me" },
            { value: "other", label: "Someone who allowed it" },
          ]}
        />
      </>,
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "Keep the music" }));
    expect(onCheck).toHaveBeenCalledWith(true);
    expect(screen.getByRole("radio", { name: "Me" })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "Someone who allowed it" }));
    expect(onPick).toHaveBeenCalledWith("other");
  });
});

describe("Slider", () => {
  it("says its value in words", () => {
    render(
      <Slider
        label="Length"
        value={30}
        min={5}
        max={240}
        onValueChange={() => {}}
        format={(v) => `0:${v}`}
      />,
    );
    const thumb = screen.getByRole("slider", { name: "Length" });
    expect(thumb).toHaveAttribute("aria-valuetext", "0:30");
    expect(screen.getByText("0:30")).toBeInTheDocument();
  });
});

describe("Segmented and Stepper", () => {
  it("keep one chosen and mark the current step", async () => {
    const onChange = vi.fn();
    render(
      <>
        <Segmented
          label="Mode"
          value="create"
          onValueChange={onChange}
          options={[
            { value: "create", label: "Create" },
            { value: "edit", label: "Edit" },
          ]}
        />
        <Stepper steps={["Add pictures", "Check", "Teach"]} current={1} />
      </>,
    );
    expect(screen.getByRole("radio", { name: "Create" })).toHaveAttribute("data-state", "on");
    await userEvent.click(screen.getByRole("radio", { name: "Edit" }));
    expect(onChange).toHaveBeenCalledWith("edit");
    const steps = within(screen.getByRole("list", { name: "Steps" })).getAllByRole("listitem");
    expect(steps[0]).toHaveAttribute("data-state", "done");
    expect(steps[1]).toHaveAttribute("aria-current", "step");
    expect(steps[2]).toHaveAttribute("data-state", "upcoming");
  });
});

describe("Experts and EmptyState", () => {
  it("start closed, and say what goes here", () => {
    render(
      <>
        <Experts summary="seed, tempo">
          <p>Seed</p>
        </Experts>
        <EmptyState
          icon={ImageIcon}
          title="Your picture appears here."
          text="Describe it, then press Make."
        />
      </>,
    );
    expect(screen.getByText("For experts").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByRole("heading", { name: "Your picture appears here." })).toBeInTheDocument();
  });
});

describe("ErrorNotice", () => {
  it("cleans paths, addresses, codes and traces out of a message", () => {
    expect(plainError("not mocked: GET /products/wasifyai-video/status")).toBe(
      "That did not work.",
    );
    expect(plainError("Error: The model could not be loaded (HTTP 503)")).toBe(
      "The model could not be loaded.",
    );
    expect(plainError("That file is too large. Use one under 300 MB.")).toBe(
      "That file is too large. Use one under 300 MB.",
    );
    expect(
      plainError("Failed: ECONNREFUSED http://127.0.0.1:8188/prompt\n  at fetch (node:x)"),
    ).toBe("That did not work.");
  });

  it("shows the plain words, the next step and keeps the raw text for experts", () => {
    render(
      <ErrorNotice
        message="not mocked: GET /products/x/status"
        next="Start the engine, then try again."
        onRetry={() => {}}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("That did not work.");
    expect(alert).toHaveTextContent("Start the engine, then try again.");
    expect(alert).not.toHaveTextContent("/products");
    expect(screen.getByText("Details for experts").closest("details")).toHaveTextContent(
      "GET /products/x/status",
    );
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("ActionsRow", () => {
  it("shows three buttons and the rest behind More", async () => {
    const picked: string[] = [];
    const action = (label: string) => ({ label, onSelect: () => picked.push(label) });
    render(
      <ActionsRow
        actions={[
          action("Play"),
          action("Save"),
          action("Make again"),
          action("Rename"),
          action("Delete"),
        ]}
      />,
    );
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Play",
      "Save",
      "Make again",
      "More",
    ]);
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
    expect(picked).toEqual(["Rename"]);
  });
});

describe("Stage", () => {
  it("has its four states", () => {
    const { rerender } = render(
      <Stage state={{ kind: "empty", title: "Your picture appears here." }} />,
    );
    const stage = () => screen.getByRole("region", { name: "Result" });
    expect(stage()).toHaveAttribute("data-state", "empty");
    rerender(
      <Stage
        state={{
          kind: "working",
          label: "Making your picture…",
          text: "about 20 seconds",
          value: 0.4,
          onStop: () => {},
        }}
      />,
    );
    expect(screen.getByRole("progressbar", { name: "Making your picture…" })).toHaveAttribute(
      "value",
      "40",
    );
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    rerender(
      <Stage
        state={{
          kind: "error",
          message: "Error: the engine stopped (HTTP 502)",
          onRetry: () => {},
        }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("The engine stopped.");
    rerender(
      <Stage
        state={{
          kind: "result",
          children: <img alt="A lighthouse" src="x.png" />,
          actions: [{ label: "Edit this", onSelect: () => {} }],
        }}
      />,
    );
    expect(stage()).toHaveAttribute("data-state", "result");
    expect(screen.getByRole("img", { name: "A lighthouse" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit this" })).toBeInTheDocument();
  });
});

describe("Player and RecentStrip", () => {
  it("play, pause and open", async () => {
    const open = vi.fn();
    render(
      <>
        <Player src="a.mp3" title="Hello" duration={65} />
        <RecentStrip
          items={[{ id: "1", cover: <span />, label: "A lighthouse", onOpen: open }]}
          onSeeAll={() => {}}
        />
      </>,
    );
    expect(screen.getByText("1:05")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Play Hello" }));
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "A lighthouse" }));
    expect(open).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "See all" })).toBeInTheDocument();
  });
});
