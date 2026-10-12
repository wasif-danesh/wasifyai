// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { VoiceCatalog } from "@wasifyai/contracts";
import { describe, expect, it, vi } from "vitest";
import { SpeechForm } from "./SpeechForm";

const v = (id: string, label: string, quality = "good", def = false) => ({
  id,
  label,
  quality,
  default: def,
});
const catalog = {
  languages: [
    {
      id: "en-US",
      name: "English (US)",
      english: "English (US)",
      genders: { female: [v("a", "Bella", "good", true), v("b", "Nova")], male: [v("c", "Adam")] },
    },
    {
      id: "fr",
      name: "Français",
      english: "French",
      genders: { female: [v("d", "Siwis")], male: [] },
    },
    {
      id: "es",
      name: "Español",
      english: "Spanish",
      genders: { female: [v("e", "Dora", "limited", true)], male: [v("f", "Alex", "limited")] },
    },
  ],
} as unknown as VoiceCatalog;

async function chooseLanguage(name: RegExp) {
  await userEvent.click(screen.getByRole("combobox", { name: "Language" }));
  await userEvent.click(await screen.findByRole("option", { name }));
}

describe("SpeechForm", () => {
  it("submits trimmed text with the chosen language and gender", async () => {
    const onSubmit = vi.fn();
    render(<SpeechForm catalog={catalog} onSubmit={onSubmit} />);
    const button = screen.getByRole("button", { name: "Create speech" });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText("What should it say?"), "  Hello  ");
    await userEvent.click(screen.getByRole("radio", { name: "Male" }));
    await userEvent.click(button);
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({ text: "Hello", language: "en-US", gender: "male" }),
    );
  });

  it("disables a gender with no voice and moves to the one the language has", async () => {
    render(<SpeechForm catalog={catalog} onSubmit={vi.fn()} />);
    await userEvent.click(screen.getByRole("radio", { name: "Male" }));
    await chooseLanguage(/French/);
    expect(screen.getByRole("radio", { name: "Male" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Female" })).toBeChecked();
  });

  it("warns when the voices for a language are limited", async () => {
    render(<SpeechForm catalog={catalog} onSubmit={vi.fn()} />);
    await chooseLanguage(/Spanish/);
    expect(screen.getByText(/still limited/)).toBeInTheDocument();
  });

  it("offers a voice choice only when there is more than one", () => {
    render(<SpeechForm catalog={catalog} onSubmit={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "Which voice" })).toBeInTheDocument();
  });

  it("asks for text instead of sending nothing", async () => {
    const onSubmit = vi.fn();
    render(<SpeechForm catalog={catalog} onSubmit={onSubmit} initial={{ text: "x" }} />);
    await userEvent.clear(screen.getByLabelText("What should it say?"));
    await userEvent.keyboard("{Control>}{Enter}{/Control}");
    expect(await screen.findByText("Type the words you want spoken.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
