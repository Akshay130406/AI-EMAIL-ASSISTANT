import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import InboxPage from "./InboxPage";

const api = vi.hoisted(() => ({
  getGmailStatus: vi.fn(),
  listEmails: vi.fn(),
  getEmailThread: vi.fn(),
  syncGmail: vi.fn(),
}));

vi.mock("../services/api", () => api);

function renderInbox() {
  return render(
    <MemoryRouter>
      <InboxPage folder="inbox" />
    </MemoryRouter>,
  );
}

describe("inbox Gmail connection states", () => {
  beforeEach(() => {
    api.getGmailStatus.mockReset();
    api.listEmails.mockReset();
    api.getEmailThread.mockReset();
    api.syncGmail.mockReset();
  });

  afterEach(cleanup);

  it("keeps the existing demo experience when Gmail has never been connected", async () => {
    api.getGmailStatus.mockResolvedValue({
      connected: false,
      email: null,
      status: "not_connected",
      last_synced_at: null,
      requires_reconnect: false,
      compose_enabled: false,
    });

    renderInbox();

    expect(await screen.findByText("A local product preview populated with clearly labeled sample messages.")).toBeTruthy();
    expect(api.listEmails).not.toHaveBeenCalled();
  });

  it("shows a real Gmail empty state without rendering demo messages", async () => {
    api.getGmailStatus.mockResolvedValue({
      connected: true,
      email: "reader@example.test",
      status: "connected",
      last_synced_at: null,
      requires_reconnect: false,
      compose_enabled: false,
    });
    api.listEmails.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    });

    renderInbox();

    expect(await screen.findByText("No Gmail messages found")).toBeTruthy();
    expect(screen.getByText(/Read-only messages from reader@example.test/)).toBeTruthy();
    expect(screen.queryByText("A local product preview populated with clearly labeled sample messages.")).toBeNull();
  });

  it("shows Gmail inbox loading and API failure states", async () => {
    api.getGmailStatus.mockResolvedValue({
      connected: true,
      email: "reader@example.test",
      status: "connected",
      last_synced_at: null,
      requires_reconnect: false,
      compose_enabled: false,
    });
    let resolveList!: (value: { items: never[]; total: number; page: number; page_size: number }) => void;
    api.listEmails.mockReturnValue(
      new Promise((resolve) => {
        resolveList = resolve;
      }),
    );

    renderInbox();
    expect(await screen.findByText("Loading Gmail messages…")).toBeTruthy();
    resolveList({ items: [], total: 0, page: 1, page_size: 20 });
    expect(await screen.findByText("No Gmail messages found")).toBeTruthy();

    api.listEmails.mockRejectedValue(new Error("network unavailable"));
    fireEvent.change(screen.getByLabelText("Search Gmail"), { target: { value: "query" } });
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("does not fall back to sample messages when Gmail status cannot be verified", async () => {
    api.getGmailStatus.mockRejectedValue(new Error("network error"));

    renderInbox();

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("No sample emails found")).toBeNull();
  });
});
