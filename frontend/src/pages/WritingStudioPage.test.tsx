import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import WritingStudioPage from "./WritingStudioPage";

const api = vi.hoisted(() => ({
  writeEmail: vi.fn(),
  rewriteEmail: vi.fn(),
  getGmailStatus: vi.fn(),
  createGmailDraft: vi.fn(),
  beginGmailComposeConnect: vi.fn(),
}));

vi.mock("../services/api", () => api);

describe("Gemini Writing Studio", () => {
  beforeEach(() => {
    api.writeEmail.mockReset();
    api.rewriteEmail.mockReset();
    api.getGmailStatus.mockReset().mockResolvedValue({
      connected: false,
      email: null,
      status: "not_connected",
      last_synced_at: null,
      requires_reconnect: false,
      compose_enabled: false,
    });
    api.createGmailDraft.mockReset();
    api.beginGmailComposeConnect.mockReset();
  });

  afterEach(cleanup);

  it("requests and displays an editable Gemini draft", async () => {
    api.writeEmail.mockResolvedValue({
      subject: "Project update",
      body: "Hello,\n\nHere is the update.",
      subject_suggestions: [],
    });
    render(<MemoryRouter><WritingStudioPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("What should the email say?"), {
      target: { value: "Share the project update without adding dates." },
    });
    fireEvent.change(screen.getByLabelText("Tone"), { target: { value: "Persuasive" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate draft" }));

    await waitFor(() => expect(api.writeEmail).toHaveBeenCalledWith(
      expect.objectContaining({
        instructions: "Share the project update without adding dates.",
        tone: "Persuasive",
      }),
    ));
    await waitFor(() => {
      expect((screen.getByLabelText("Draft content") as HTMLTextAreaElement).value).toBe(
        "Hello,\n\nHere is the update.",
      );
    });
    expect(screen.getByText("Gemini draft suggestion ready. Review and edit before using.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Connect Gmail in Settings/ })).toBeTruthy();
  });

  it("shows provider errors without replacing text with sample output", async () => {
    api.rewriteEmail.mockRejectedValue(new Error("Gemini is not configured"));
    render(<MemoryRouter><WritingStudioPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Draft content"), {
      target: { value: "Original user draft." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Rewrite" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Gemini is not configured");
    expect(screen.getByDisplayValue("Original user draft.")).toBeTruthy();
  });

  it("saves an edited AI suggestion as a Gmail draft without sending", async () => {
    api.getGmailStatus.mockResolvedValue({
      connected: true,
      email: "reader@example.test",
      status: "connected",
      last_synced_at: null,
      requires_reconnect: false,
      compose_enabled: true,
    });
    api.writeEmail.mockResolvedValue({
      subject: "Project update",
      body: "Generated body",
      subject_suggestions: [],
    });
    api.createGmailDraft.mockResolvedValue({});
    render(<MemoryRouter><WritingStudioPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("To"), {
      target: { value: "reader@example.test" },
    });
    fireEvent.change(screen.getByLabelText("What should the email say?"), {
      target: { value: "Summarize the task." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate draft" }));
    await screen.findByDisplayValue("Generated body");
    fireEvent.change(screen.getByLabelText("Draft content"), {
      target: { value: "Edited by the user." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save to Gmail Drafts" }));

    await waitFor(() => expect(api.createGmailDraft).toHaveBeenCalledWith({
      recipients: ["reader@example.test"],
      cc: [],
      bcc: [],
      subject: "Project update",
      body: "Edited by the user.",
    }));
    expect(screen.getByText("Draft saved to Gmail. It has not been sent.")).toBeTruthy();
  });
});
