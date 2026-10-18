// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AddSources } from "./AddSources";
import { NotebookList } from "./NotebookList";
import { NotebookPlaceProvider } from "./place";

const noop = () => {};
const empty = (
  <NotebookList notebooks={[]} onOpen={noop} onCreate={noop} onRename={noop} onRemove={noop} />
);
const adding = <AddSources onFiles={noop} onNote={noop} busy={false} />;

describe("where the documents are kept, as the screens say it", () => {
  it("says they stay on this computer by default (the desktop window)", () => {
    render(
      <>
        {empty}
        {adding}
      </>,
    );
    expect(screen.getByText(/everything stays on this computer/)).toBeInTheDocument();
    expect(screen.getByText(/Documents stay on this computer/)).toBeInTheDocument();
  });

  it("says they are kept in the person's account on the web, and never 'this computer'", () => {
    const { container } = render(
      <NotebookPlaceProvider place="hosted">
        {empty}
        {adding}
      </NotebookPlaceProvider>,
    );
    expect(screen.getByText(/your documents are private to you/)).toBeInTheDocument();
    expect(screen.getByText(/kept in your account/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/this computer/);
  });
});
