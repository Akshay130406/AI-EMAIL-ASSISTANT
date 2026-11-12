import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import MeetingsPage from "./MeetingsPage";
import type {
  CalendarEventRecord,
  CalendarStatus,
} from "../types/api";

const api = vi.hoisted(() => ({
  beginCalendarConnect: vi.fn(),
  createCalendarEvent: vi.fn(),
  deleteCalendarEvent: vi.fn(),
  disconnectCalendar: vi.fn(),
  findCalendarConflicts: vi.fn(),
  getCalendarAvailability: vi.fn(),
  getCalendarStatus: vi.fn(),
  listCalendars: vi.fn(),
  listCalendarEvents: vi.fn(),
  requestMeetingAssistance: vi.fn(),
  updateCalendarEvent: vi.fn(),
}));

vi.mock("../services/api", () => api);

const connected: CalendarStatus = {
  connected: true,
  status: "connected",
  email: "calendar@example.test",
  requires_reconnect: false,
};

const disconnected: CalendarStatus = {
  connected: false,
  status: "not_connected",
  email: null,
  requires_reconnect: false,
};

const event: CalendarEventRecord = {
  id: "event-1",
  calendar_id: "primary",
  summary: "Project review",
  description: "Review project milestones.",
  start: "2030-01-02T10:00:00Z",
  end: "2030-01-02T10:30:00Z",
  time_zone: "UTC",
  attendees: ["person@example.test"],
  html_link: null,
  status: "confirmed",
};

function renderPage() {
  return render(<MeetingsPage />);
}

describe("Meetings page", () => {
  beforeEach(() => {
    Object.values(api).forEach((mock) => mock.mockReset());
    api.getCalendarStatus.mockResolvedValue(disconnected);
    api.listCalendars.mockResolvedValue({
      items: [],
      next_page_token: null,
    });
    api.listCalendarEvents.mockResolvedValue({
      items: [],
      next_page_token: null,
    });
    api.findCalendarConflicts.mockResolvedValue({ conflicts: [], calendar_id: "primary" });
    api.createCalendarEvent.mockResolvedValue(event);
    api.updateCalendarEvent.mockResolvedValue(event);
    api.deleteCalendarEvent.mockResolvedValue(undefined);
  });

  afterEach(cleanup);

  it("keeps the sample schedule clearly labeled when Calendar is disconnected", async () => {
    renderPage();
    expect((await screen.findAllByText("Design critique")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("SAMPLE").length).toBeGreaterThan(0);
    expect(api.listCalendarEvents).not.toHaveBeenCalled();
  });

  it("shows real events without mixing sample data when connected", async () => {
    api.getCalendarStatus.mockResolvedValue(connected);
    api.listCalendars.mockResolvedValue({
      items: [{
        id: "primary",
        summary: "My calendar",
        time_zone: "UTC",
        primary: true,
        access_role: "owner",
      }],
      next_page_token: null,
    });
    api.listCalendarEvents.mockResolvedValue({
      items: [event],
      next_page_token: null,
    });
    renderPage();

    expect(await screen.findByText("Project review")).toBeTruthy();
    expect(screen.queryByText("Design critique")).toBeNull();
    expect(screen.getByText("GOOGLE CALENDAR")).toBeTruthy();
  });

  it("does not substitute sample meetings when the real Calendar request fails", async () => {
    api.getCalendarStatus.mockResolvedValue(connected);
    api.listCalendarEvents.mockRejectedValue(new Error("Calendar unavailable"));
    renderPage();

    expect(await screen.findByText("Calendar unavailable")).toBeTruthy();
    expect(screen.queryByText("Design critique")).toBeNull();
  });

  it("requires a user confirmation before creating a real Calendar event", async () => {
    api.getCalendarStatus.mockResolvedValue(connected);
    api.listCalendars.mockResolvedValue({
      items: [{
        id: "primary",
        summary: "My calendar",
        time_zone: "UTC",
        primary: true,
        access_role: "owner",
      }],
      next_page_token: null,
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Schedule" }));
    fireEvent.change(screen.getByLabelText("Meeting title"), {
      target: { value: "Confirmed planning meeting" },
    });
    fireEvent.change(screen.getByLabelText("Attendee emails (comma-separated)"), {
      target: { value: "guest@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review & create" }));

    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(screen.getByText("guest@example.test")).toBeTruthy();
    expect(screen.getByText(Intl.DateTimeFormat().resolvedOptions().timeZone)).toBeTruthy();
    expect(api.createCalendarEvent).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm and create" }));
    await waitFor(() => expect(api.createCalendarEvent).toHaveBeenCalledOnce());
    expect(api.createCalendarEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        summary: "Confirmed planning meeting",
        request_id: expect.any(String),
      }),
      "primary",
    );
  });

  it("lists calendars and does not allow writes to a read-only calendar", async () => {
    api.getCalendarStatus.mockResolvedValue(connected);
    api.listCalendars.mockResolvedValue({
      items: [{
        id: "shared",
        summary: "Shared calendar",
        time_zone: "America/Los_Angeles",
        primary: false,
        access_role: "reader",
      }],
      next_page_token: null,
    });
    api.listCalendarEvents.mockResolvedValue({
      items: [],
      next_page_token: null,
    });
    renderPage();

    expect(await screen.findByRole("option", { name: "Shared calendar" })).toBeTruthy();
    expect(api.listCalendarEvents).toHaveBeenCalledWith(
      expect.objectContaining({ calendar_id: "shared" }),
    );
    expect(screen.getByRole("button", { name: "Schedule" }).hasAttribute("disabled")).toBe(true);
  });

  it("shows event details and timezone before confirmed deletion", async () => {
    api.getCalendarStatus.mockResolvedValue(connected);
    api.listCalendars.mockResolvedValue({
      items: [{
        id: "primary",
        summary: "My calendar",
        time_zone: "America/Los_Angeles",
        primary: true,
        access_role: "owner",
      }],
      next_page_token: null,
    });
    api.listCalendarEvents.mockResolvedValue({
      items: [event],
      next_page_token: null,
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("Project review");
    expect(dialog.textContent).toContain("UTC");
    expect(api.deleteCalendarEvent).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    expect(await screen.findByText("Calendar event deleted.")).toBeTruthy();
    expect(api.deleteCalendarEvent).toHaveBeenCalledWith("event-1", "primary");
  });

  it("blocks an uncertain event write until the calendar is refreshed", async () => {
    api.getCalendarStatus.mockResolvedValue(connected);
    api.listCalendars.mockResolvedValue({
      items: [{
        id: "primary",
        summary: "My calendar",
        time_zone: "UTC",
        primary: true,
        access_role: "owner",
      }],
      next_page_token: null,
    });
    api.createCalendarEvent.mockRejectedValue(
      new Error("Calendar could not confirm the event update; refresh before retrying"),
    );
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Schedule" }));
    fireEvent.change(screen.getByLabelText("Meeting title"), {
      target: { value: "Potentially created meeting" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review & create" }));
    const confirmButton = await screen.findByRole("button", { name: "Confirm and create" });
    await waitFor(() => expect(confirmButton.hasAttribute("disabled")).toBe(false));
    fireEvent.click(confirmButton);

    const refresh = await screen.findByRole("button", { name: "Refresh events" });
    await waitFor(() => expect(refresh.hasAttribute("disabled")).toBe(false));
    expect(api.createCalendarEvent).toHaveBeenCalledOnce();
    api.listCalendarEvents.mockResolvedValue({
      items: [event],
      next_page_token: null,
    });
    fireEvent.click(screen.getByRole("button", { name: "Refresh events" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.createCalendarEvent).toHaveBeenCalledOnce();
    expect(await screen.findByText("Project review")).toBeTruthy();
  });
});
