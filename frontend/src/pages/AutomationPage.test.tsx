import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AutomationPage from "./AutomationPage";
import type {
  AutomationRecord,
  BackgroundJobRecord,
  GmailStatus,
  NotificationRecord,
} from "../types/api";

const api = vi.hoisted(() => ({
  cancelBackgroundJob: vi.fn(),
  createAutomation: vi.fn(),
  getGmailStatus: vi.fn(),
  listAutomations: vi.fn(),
  listBackgroundJobs: vi.fn(),
  listNotifications: vi.fn(),
  runAutomation: vi.fn(),
  updateAutomation: vi.fn(),
  updateNotification: vi.fn(),
}));

vi.mock("../services/api", () => api);

const gmail: GmailStatus = {
  connected: true,
  email: "reader@example.test",
  status: "connected",
  last_synced_at: null,
  requires_reconnect: false,
  compose_enabled: false,
};

const rule: AutomationRecord = {
  id: "automation-1",
  kind: "gmail_sync",
  enabled: true,
  interval_minutes: 60,
  next_run_at: "2030-01-02T10:00:00Z",
  last_run_at: null,
  created_at: "2030-01-01T10:00:00Z",
  updated_at: "2030-01-01T10:00:00Z",
};

const job: BackgroundJobRecord = {
  id: "job-1",
  automation_id: rule.id,
  job_type: "gmail_sync",
  status: "queued",
  attempts: 0,
  max_attempts: 5,
  available_at: "2030-01-02T10:00:00Z",
  started_at: null,
  finished_at: null,
  last_error_code: null,
  result_summary: null,
  created_at: "2030-01-01T10:00:00Z",
  updated_at: "2030-01-01T10:00:00Z",
};

const notification: NotificationRecord = {
  id: "notification-1",
  source_job_id: "job-1",
  kind: "gmail_sync",
  title: "Gmail synchronization complete",
  message: "2 messages synchronized.",
  data: { synced: 2 },
  read_at: null,
  created_at: "2030-01-01T10:00:00Z",
};

function renderPage() {
  return render(
    <MemoryRouter>
      <AutomationPage />
    </MemoryRouter>,
  );
}

describe("Automation page", () => {
  beforeEach(() => {
    Object.values(api).forEach((mock) => mock.mockReset());
    api.getGmailStatus.mockResolvedValue(gmail);
    api.listAutomations.mockResolvedValue([rule]);
    api.listBackgroundJobs.mockResolvedValue({
      items: [job],
      total: 1,
      page: 1,
      page_size: 10,
    });
    api.listNotifications.mockResolvedValue({
      items: [notification],
      total: 1,
      unread_count: 1,
      page: 1,
      page_size: 10,
    });
    api.updateAutomation.mockResolvedValue({ ...rule, enabled: false });
    api.createAutomation.mockResolvedValue({
      ...rule,
      id: "automation-2",
      kind: "daily_briefing",
    });
    api.updateNotification.mockResolvedValue({
      ...notification,
      read_at: "2030-01-02T10:00:00Z",
    });
  });

  afterEach(cleanup);

  it("renders persisted jobs and notifications rather than browser-only demo state", async () => {
    renderPage();
    expect(await screen.findByText("Background jobs")).toBeTruthy();
    expect(screen.getByText("Gmail synchronization complete")).toBeTruthy();
    expect(screen.getByText("2 messages synchronized.")).toBeTruthy();
    expect(screen.queryByText("LOCAL DEMO")).toBeNull();
  });

  it("creates an enabled automation only after the user toggles it on", async () => {
    api.listAutomations.mockResolvedValue([]);
    renderPage();
    fireEvent.click(await screen.findByRole("switch", { name: "Enable AI inbox briefing" }));
    await waitFor(() => expect(api.createAutomation).toHaveBeenCalledOnce());
    expect(api.createAutomation).toHaveBeenCalledWith({
      kind: "daily_briefing",
      interval_minutes: 1440,
      enabled: true,
    });
  });

  it("shows loading failures without fake jobs or notifications", async () => {
    api.listAutomations.mockRejectedValue(new Error("Automation service unavailable"));
    renderPage();
    expect(await screen.findByText("Automation service unavailable")).toBeTruthy();
    expect(screen.getByText("No background jobs have been queued.")).toBeTruthy();
    expect(screen.getByText("Job results and reminders will appear here.")).toBeTruthy();
  });

  it("can mark a user notification as read", async () => {
    renderPage();
    fireEvent.click(
      await screen.findByRole("button", { name: "Mark notification read" }),
    );
    expect(await screen.findByText(/0 unread/)).toBeTruthy();
    expect(api.updateNotification).toHaveBeenCalledWith(notification.id, true);
  });
});
