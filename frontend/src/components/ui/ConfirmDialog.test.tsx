import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("focuses the safe action and closes with Escape", () => {
    const cancel = vi.fn();
    render(<ConfirmDialog open title="Archive record?" description="This changes its status." destructive onCancel={cancel} onConfirm={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(cancel).toHaveBeenCalledOnce();
  });

  it("does not close a busy operation with Escape", () => {
    const cancel = vi.fn();
    render(<ConfirmDialog open busy title="Delete record?" description="This cannot be undone." onCancel={cancel} onConfirm={vi.fn()} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(cancel).not.toHaveBeenCalled();
  });
});
