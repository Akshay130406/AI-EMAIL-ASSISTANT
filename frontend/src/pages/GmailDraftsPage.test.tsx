import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import GmailDraftsPage from "./GmailDraftsPage";
import type { DraftRecord, GmailStatus } from "../types/api";

const api = vi.hoisted(() => ({
  beginGmailComposeConnect: vi.fn(),
  createGmailDraft: vi.fn(),
  deleteGmailDraft: vi.fn(),
  listGmailDrafts: vi.fn(),
  sendGmailDraft: vi.fn(),
  updateGmailDraft: vi.fn(),
}));

vi.mock("../services/api", () => api);

const connected: GmailStatus = {
  connected: true,
  email: "reader@example.test",
  status: "connected",
  last_synced_at: null,
  requires_reconnect: false,
  compose_enabled: true,
};

const draft: DraftRecord = {
  id: "draft-1",
  user_id: "user-1",
  recipient: "to@example.test",
  recipients: ["to@example.test"],
  cc: [],
  bcc: [],
  subject: "A real Gmail draft",
  body: "Message content",
  status: "draft",
  gmail_draft_id: "gmail-draft-1",
  gmail_message_id: "gmail-message-1",
  send_status: "not_sent",
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
};

function renderPage(connection = connected) {
  return render(<GmailDraftsPage connection={connection} />);
}

describe("Gmail drafts page", () => {
  beforeEach(() => {
    api.beginGmailComposeConnect.mockReset();
    api.createGmailDraft.mockReset();
    api.deleteGmailDraft.mockReset();
    api.listGmailDrafts.mockReset();
    api.sendGmailDraft.mockReset();
    api.updateGmailDraft.mockReset();
    api.updateGmailDraft.mockResolvedValue(draft);
  });

  afterEach(cleanup);

  it("offers the separate compose authorization when Gmail is read-only", async () => {
    renderPage({ ...connected, compose_enabled: false });
    const button = screen.getByRole("button", { name: "Enable draft access" });
    fireEvent.click(button);
    expect(api.beginGmailComposeConnect).toHaveBeenCalledOnce();
    expect(api.listGmailDrafts).not.toHaveBeenCalled();
  });

  it("loads real drafts and saves a new Gmail draft", async () => {
    api.listGmailDrafts.mockResolvedValue({
      items: [draft],
      total: 1,
      page: 1,
      page_size: 20,
    });
    api.createGmailDraft.mockResolvedValue({ ...draft, id: "draft-2" });
    renderPage();

    expect(await screen.findByText("A real Gmail draft")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "New draft" }));
    fireEvent.change(screen.getByLabelText("To"), {
      target: { value: "new@example.test" },
    });
    fireEvent.change(screen.getByLabelText("Subject"), {
      target: { value: "New subject" },
    });
    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "New message" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    expect(await screen.findByRole("status")).toBeTruthy();
    expect(api.createGmailDraft).toHaveBeenCalledWith({
      recipients: ["new@example.test"],
      cc: [],
      bcc: [],
      subject: "New subject",
      body: "New message",
    });
  });

  it("shows loading failures without substituting sample drafts", async () => {
    api.listGmailDrafts.mockRejectedValue(new Error("Gmail is unavailable"));
    renderPage();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("Gmail is unavailable")).toBeTruthy();
    expect(screen.queryByText("No sample emails found")).toBeNull();
  });

  it("reports draft save failures without showing a success message", async () => {
    api.listGmailDrafts.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    });
    api.createGmailDraft.mockRejectedValue(new Error("Gmail rejected the draft"));
    renderPage();
    fireEvent.change(await screen.findByLabelText("To"), {
      target: { value: "recipient@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("Gmail rejected the draft")).toBeTruthy();
    expect(screen.queryByText("Draft saved to Gmail.")).toBeNull();
  });

  it("shows final content before confirmation and never offers retry for an uncertain send", async () => {
    api.listGmailDrafts.mockResolvedValue({
      items: [draft],
      total: 1,
      page: 1,
      page_size: 20,
    });
    api.sendGmailDraft.mockResolvedValue({
      draft_id: draft.id,
      status: "sent",
      gmail_message_id: "sent-message",
    });
    renderPage();
    fireEvent.click(await screen.findByText("A real Gmail draft"));
    fireEvent.click(screen.getByRole("button", { name: "Send…" }));
    expect(api.sendGmailDraft).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog").textContent).toContain("Message content");
    fireEvent.click(screen.getByRole("button", { name: "Confirm and send" }));
    expect(await screen.findByText("Gmail confirmed that the message was sent.")).toBeTruthy();
    expect(api.updateGmailDraft).toHaveBeenCalledWith(draft.id, {
      recipients: ["to@example.test"],
      cc: [],
      bcc: [],
      subject: "A real Gmail draft",
      body: "Message content",
    });
    expect(api.sendGmailDraft).toHaveBeenCalledWith(draft.id);

    cleanup();
    api.listGmailDrafts.mockResolvedValue({
      items: [{ ...draft, send_status: "unknown" }],
      total: 1,
      page: 1,
      page_size: 20,
    });
    renderPage();
    fireEvent.click(await screen.findByText("A real Gmail draft"));
    expect(screen.getByText("Send status: unknown")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Send…" })).toBeNull();
  });

  it("does not send if the final confirmation is cancelled", async () => {
    api.listGmailDrafts.mockResolvedValue({
      items: [draft],
      total: 1,
      page: 1,
      page_size: 20,
    });
    renderPage();
    fireEvent.click(await screen.findByText("A real Gmail draft"));
    fireEvent.click(screen.getByRole("button", { name: "Send…" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.updateGmailDraft).not.toHaveBeenCalled();
    expect(api.sendGmailDraft).not.toHaveBeenCalled();
  });
});
