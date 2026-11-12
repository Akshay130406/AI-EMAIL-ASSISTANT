import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  CalendarDays,
  Check,
  Clock3,
  LoaderCircle,
  MapPin,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  Users,
  Video,
} from "lucide-react";
import { Button, Card, DemoNotice, PageHeading } from "../components/ui";
import {
  beginCalendarConnect,
  createCalendarEvent,
  deleteCalendarEvent,
  disconnectCalendar,
  findCalendarConflicts,
  getCalendarAvailability,
  getCalendarStatus,
  listCalendars,
  listCalendarEvents,
  requestMeetingAssistance,
  updateCalendarEvent,
} from "../services/api";
import type {
  CalendarAvailability,
  CalendarRecord,
  CalendarEventInput,
  CalendarEventRecord,
  CalendarStatus,
  MeetingAssistantResult,
} from "../types/api";

const demoMeetings = [
  {
    time: "10:30 – 11:00 AM",
    title: "Design critique",
    people: "Olivia Chen, Marcus Williams + 3",
    location: "Design room · Sample",
    color: "border-l-accent",
    summary:
      "Review the latest onboarding flow and agree on the key Q4 design milestones.",
  },
  {
    time: "2:00 – 2:45 PM",
    title: "Product weekly sync",
    people: "Priya Patel, Theo Brooks + 5",
    location: "Video call · Sample",
    color: "border-l-violet-400",
    summary:
      "A sample weekly sync to review project progress, blockers, and upcoming releases.",
  },
  {
    time: "Thu, 11:00 AM",
    title: "Partnership introduction",
    people: "Marcus Williams + 2",
    location: "Video call · Sample",
    color: "border-l-amber-400",
    summary:
      "An example partner introduction and discussion of possible next steps.",
  },
];

type EventFormState = {
  summary: string;
  description: string;
  start: string;
  end: string;
  attendees: string;
};

type EventReview =
  | {
      action: "create" | "update";
      input: CalendarEventInput;
      calendarId: string;
      requestId?: string;
      eventId?: string;
      conflicts: CalendarEventRecord[];
    }
  | { action: "delete"; event: CalendarEventRecord };

function localInputDate(value: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value}T00:00`;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function displayDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function displayDateInZone(value: string, zone: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: zone,
      }).format(date);
}

function isUncertainCalendarWrite(error: unknown): boolean {
  if (typeof error !== "object" || error === null || !("status" in error)) {
    return true;
  }
  return typeof error.status !== "number" || error.status >= 500;
}

function localDateString(date: Date): string {
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function emptyForm(): EventFormState {
  const start = new Date(Date.now() + 30 * 60 * 1000);
  start.setMinutes(Math.ceil(start.getMinutes() / 15) * 15, 0, 0);
  const end = new Date(start.getTime() + 30 * 60 * 1000);
  return {
    summary: "",
    description: "",
    start: localInputDate(start.toISOString()),
    end: localInputDate(end.toISOString()),
    attendees: "",
  };
}

function eventForm(event: CalendarEventRecord): EventFormState {
  return {
    summary: event.summary,
    description: event.description,
    start: localInputDate(event.start),
    end: localInputDate(event.end),
    attendees: event.attendees.join(", "),
  };
}

export default function MeetingsPage() {
  const [calendar, setCalendar] = useState<CalendarStatus | null>(null);
  const [calendars, setCalendars] = useState<CalendarRecord[]>([]);
  const [selectedCalendarId, setSelectedCalendarId] = useState("primary");
  const [statusLoading, setStatusLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [events, setEvents] = useState<CalendarEventRecord[]>([]);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [form, setForm] = useState<EventFormState>(emptyForm);
  const [formOpen, setFormOpen] = useState(false);
  const [editingEvent, setEditingEvent] = useState<CalendarEventRecord | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [oauthMessage, setOauthMessage] = useState<string | null>(null);
  const [availabilityDate, setAvailabilityDate] = useState(() =>
    localDateString(new Date()),
  );
  const [availability, setAvailability] = useState<CalendarAvailability | null>(
    null,
  );
  const [availabilityError, setAvailabilityError] = useState<string | null>(
    null,
  );
  const [assistantEvent, setAssistantEvent] =
    useState<CalendarEventRecord | null>(null);
  const [assistantResult, setAssistantResult] =
    useState<MeetingAssistantResult | null>(null);
  const [assistantError, setAssistantError] = useState<string | null>(null);
  const [eventReview, setEventReview] = useState<EventReview | null>(null);
  const [eventWriteUncertain, setEventWriteUncertain] = useState(false);

  const timeZone = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    [],
  );

  async function loadEvents(
    pageToken?: string,
    calendarId = selectedCalendarId,
  ): Promise<boolean> {
    setLoadingEvents(true);
    setError(null);
    try {
      const result = await listCalendarEvents({
        calendar_id: calendarId,
        days: 90,
        page_token: pageToken,
        time_zone: timeZone,
      });
      setEvents((existing) =>
        pageToken ? [...existing, ...result.items] : result.items,
      );
      setNextPageToken(result.next_page_token);
      return true;
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Calendar events could not be loaded.",
      );
      return false;
    } finally {
      setLoadingEvents(false);
    }
  }

  async function reconcileUncertainEventWrite() {
    if (await loadEvents()) {
      setEventReview(null);
      setEventWriteUncertain(false);
      setFormOpen(false);
      setEditingEvent(null);
    }
  }

  async function refreshCalendar() {
    setStatusLoading(true);
    try {
      const result = await getCalendarStatus();
      setCalendar(result);
      if (result.connected) {
        const calendarResult = await listCalendars();
        setCalendars(calendarResult.items);
        const primary = calendarResult.items.find((item) => item.primary);
        const calendarId = primary?.id ?? calendarResult.items[0]?.id ?? "primary";
        setSelectedCalendarId(calendarId);
        await loadEvents(undefined, calendarId);
      }
      else {
        setCalendars([]);
        setEvents([]);
        setNextPageToken(null);
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Calendar connection status could not be loaded.",
      );
    } finally {
      setStatusLoading(false);
    }
  }

  useEffect(() => {
    void refreshCalendar();
    const params = new URLSearchParams(window.location.search);
    if (params.get("calendar") === "connected") {
      setOauthMessage("Google Calendar connected. Your events are loading.");
    } else {
      const oauthError = params.get("calendar_error");
      const messages: Record<string, string> = {
        not_configured: "Calendar integration is not configured on the backend.",
        cancelled: "Calendar connection was cancelled.",
        provider_error: "Google could not authorize Calendar access.",
        authorization_failed:
          "Calendar authorization failed. Check the selected account and granted permissions.",
      };
      setOauthMessage(oauthError ? messages[oauthError] ?? "Calendar authorization failed." : null);
    }
  }, []);

  function openCreateForm() {
    setEditingEvent(null);
    setForm(emptyForm());
    setFormOpen(true);
    setError(null);
    setNotice(null);
  }

  function openEditForm(event: CalendarEventRecord) {
    setEditingEvent(event);
    setForm(eventForm(event));
    setFormOpen(true);
    setError(null);
    setNotice(null);
  }

  function makeInput(): CalendarEventInput | null {
    const start = new Date(form.start);
    const end = new Date(form.end);
    if (
      !form.summary.trim() ||
      Number.isNaN(start.getTime()) ||
      Number.isNaN(end.getTime()) ||
      end <= start
    ) {
      setError("Enter a title and a valid end time after the start time.");
      return null;
    }
    return {
      summary: form.summary.trim(),
      description: form.description,
      start: start.toISOString(),
      end: end.toISOString(),
      time_zone: timeZone,
      attendees: form.attendees
        .split(",")
        .map((attendee) => attendee.trim())
        .filter(Boolean),
    };
  }

  async function saveEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = makeInput();
    if (!input) return;
    setBusy(true);
    setError(null);
    try {
      const conflictResult = await findCalendarConflicts({
        start: input.start,
        end: input.end,
        time_zone: input.time_zone,
        exclude_event_id: editingEvent?.id,
      }, selectedCalendarId);
      setEventWriteUncertain(false);
      setEventReview({
        action: editingEvent ? "update" : "create",
        input,
        calendarId: selectedCalendarId,
        requestId: editingEvent ? undefined : crypto.randomUUID(),
        eventId: editingEvent?.id,
        conflicts: conflictResult.conflicts,
      });
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Calendar event could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function confirmEventWrite() {
    if (!eventReview || eventReview.action === "delete") return;
    setBusy(true);
    setError(null);
    try {
      if (eventReview.action === "update" && eventReview.eventId) {
        await updateCalendarEvent(
          eventReview.eventId,
          eventReview.input,
          eventReview.calendarId,
        );
        setNotice("Calendar event updated.");
      } else if (eventReview.action === "create") {
        await createCalendarEvent(
          {
            ...eventReview.input,
            request_id: eventReview.requestId ?? crypto.randomUUID(),
          },
          eventReview.calendarId,
        );
        setNotice("Calendar event created.");
      }
      setEventReview(null);
      setFormOpen(false);
      setEditingEvent(null);
      await loadEvents();
    } catch (reason) {
      if (isUncertainCalendarWrite(reason)) setEventWriteUncertain(true);
      setError(
        reason instanceof Error
          ? reason.message
          : "Calendar event could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function removeEvent(event: CalendarEventRecord) {
    setEventWriteUncertain(false);
    setEventReview({ action: "delete", event });
  }

  async function confirmEventDelete() {
    if (!eventReview || eventReview.action !== "delete") return;
    const event = eventReview.event;
    setBusy(true);
    setError(null);
    try {
      await deleteCalendarEvent(event.id, event.calendar_id);
      setNotice("Calendar event deleted.");
      setAssistantEvent(null);
      setEventReview(null);
      await loadEvents();
    } catch (reason) {
      if (isUncertainCalendarWrite(reason)) setEventWriteUncertain(true);
      setError(
        reason instanceof Error
          ? reason.message
          : "Calendar event could not be deleted.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function checkAvailability() {
    setAvailability(null);
    setAvailabilityError(null);
    setBusy(true);
    try {
      setAvailability(
        await getCalendarAvailability({
          date: availabilityDate,
          time_zone: timeZone,
          duration_minutes: 30,
        }, selectedCalendarId),
      );
    } catch (reason) {
      setAvailabilityError(
        reason instanceof Error
          ? reason.message
          : "Availability could not be checked.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function prepareMeeting(event: CalendarEventRecord) {
    setAssistantEvent(event);
    setAssistantResult(null);
    setAssistantError(null);
    setBusy(true);
    try {
      setAssistantResult(
        await requestMeetingAssistance({
          operation: "agenda",
          event_id: event.id,
          calendar_id: event.calendar_id,
          question: "Summarize this meeting and suggest a concise preparation agenda.",
        }),
      );
    } catch (reason) {
      setAssistantError(
        reason instanceof Error
          ? reason.message
          : "Meeting preparation could not be generated.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleConnect() {
    setBusy(true);
    setError(null);
    try {
      await beginCalendarConnect();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Calendar authorization could not be started.",
      );
      setBusy(false);
    }
  }

  async function handleDisconnect() {
    if (
      !window.confirm(
        "Disconnect Google Calendar? Existing events will remain in Google Calendar.",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await disconnectCalendar();
      setNotice("Google Calendar disconnected.");
      await refreshCalendar();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Google Calendar could not be disconnected.",
      );
    } finally {
      setBusy(false);
    }
  }

  const connected = calendar?.connected === true;
  const canWriteCalendar = (calendarId: string) =>
    calendars.some(
      (item) =>
        item.id === calendarId &&
        (item.access_role === "owner" || item.access_role === "writer"),
    );

  return (
    <div>
      <PageHeading
        eyebrow="Meeting assistant"
        title="Make room for good work."
        description="Plan your day and prepare for conversations."
        action={
          statusLoading ? (
            <DemoNotice>Checking calendar connection…</DemoNotice>
          ) : connected ? (
            <>
              <span className="rounded-md bg-green-500/10 px-2 py-1 text-[10px] text-green-700 dark:text-green-400">
                Google Calendar{calendar?.email ? ` · ${calendar.email}` : ""}
              </span>
              <Button
                variant="primary"
                onClick={openCreateForm}
                disabled={!canWriteCalendar(selectedCalendarId)}
              >
                <Plus size={14} /> Schedule
              </Button>
            </>
          ) : (
            <>
              <DemoNotice>
                {calendar?.requires_reconnect
                  ? "Reconnect required · sample schedule"
                  : "Sample schedule · not synced"}
              </DemoNotice>
              <Button
                variant="primary"
                disabled={statusLoading || busy}
                onClick={handleConnect}
              >
                <CalendarDays size={14} />
                {calendar?.requires_reconnect ? "Reconnect Calendar" : "Connect Calendar"}
              </Button>
            </>
          )
        }
      />
      {oauthMessage && (
        <p role="status" className="mb-4 rounded-xl border border-accent/20 bg-accent/5 px-4 py-3 text-xs leading-5 text-accent">
          {oauthMessage}
        </p>
      )}
      {error && (
        <p role="alert" className="mb-4 rounded-xl border border-rose-500/20 bg-rose-500/5 px-4 py-3 text-xs leading-5 text-rose-700 dark:text-rose-300">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mb-4 rounded-xl border border-green-500/20 bg-green-500/5 px-4 py-3 text-xs leading-5 text-green-700 dark:text-green-400">
          {notice}
        </p>
      )}
      {formOpen && connected && (
        <Card className="mb-5 p-5">
          <div className="mb-4">
            <h2 className="text-sm font-semibold">
              {editingEvent ? "Edit calendar event" : "Create calendar event"}
            </h2>
            <p className="mt-1 text-[11px] text-muted">
              Review the event before saving. Google may notify listed attendees.
            </p>
          </div>
          <form onSubmit={saveEvent} className="grid gap-3 sm:grid-cols-2">
            <label className="text-[11px] text-muted">
              Meeting title
              <input
                required
                maxLength={250}
                value={form.summary}
                onChange={(event) =>
                  setForm({ ...form, summary: event.target.value })
                }
                className="input mt-1.5 h-10 w-full px-3 text-xs"
              />
            </label>
            <label className="text-[11px] text-muted">
              Attendee emails (comma-separated)
              <input
                value={form.attendees}
                onChange={(event) =>
                  setForm({ ...form, attendees: event.target.value })
                }
                className="input mt-1.5 h-10 w-full px-3 text-xs"
                placeholder="name@example.com"
              />
            </label>
            <label className="text-[11px] text-muted">
              Starts
              <input
                required
                type="datetime-local"
                value={form.start}
                onChange={(event) =>
                  setForm({ ...form, start: event.target.value })
                }
                className="input mt-1.5 h-10 w-full px-3 text-xs"
              />
            </label>
            <label className="text-[11px] text-muted">
              Ends
              <input
                required
                type="datetime-local"
                value={form.end}
                onChange={(event) =>
                  setForm({ ...form, end: event.target.value })
                }
                className="input mt-1.5 h-10 w-full px-3 text-xs"
              />
            </label>
            <label className="text-[11px] text-muted sm:col-span-2">
              Description
              <textarea
                maxLength={10000}
                value={form.description}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
                className="input mt-1.5 min-h-20 w-full px-3 py-2 text-xs"
              />
            </label>
            <div className="flex items-center gap-2 text-[10px] text-muted sm:col-span-2">
              <Clock3 size={13} /> Time zone: {timeZone}
            </div>
            <div className="flex gap-2 sm:col-span-2">
              <Button variant="primary" type="submit" disabled={busy}>
                {busy ? <LoaderCircle size={14} className="animate-spin" /> : <Check size={14} />}
                {editingEvent ? "Review & update" : "Review & create"}
              </Button>
              <Button
                type="button"
                disabled={busy}
                onClick={() => {
                  setFormOpen(false);
                  setEditingEvent(null);
                }}
              >
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(300px,0.8fr)]">
        <div className="space-y-3">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold">Upcoming meetings</h2>
              <p className="mt-1 text-xs text-muted">
                {connected
                  ? "Events from your connected Google Calendar"
                  : "Illustrative sample schedule; not synchronized"}
              </p>
              {connected && calendars.length > 0 && (
                <label className="mt-3 flex max-w-sm items-center gap-2 text-[10px] text-muted">
                  Calendar
                  <select
                    aria-label="Select calendar"
                    value={selectedCalendarId}
                    disabled={loadingEvents || busy}
                    onChange={(change) => {
                      const calendarId = change.target.value;
                      setSelectedCalendarId(calendarId);
                      setEvents([]);
                      setNextPageToken(null);
                      setAvailability(null);
                      setAvailabilityError(null);
                      void loadEvents(undefined, calendarId);
                    }}
                    className="input h-8 min-w-0 flex-1 px-2 text-xs"
                  >
                    {calendars.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.summary}{item.primary ? " (primary)" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {connected && calendars.length > 0 && !canWriteCalendar(selectedCalendarId) && (
                <p className="mt-2 text-[10px] text-muted">
                  This calendar is read-only for your Google account.
                </p>
              )}
            </div>
            {connected && (
              <Button disabled={loadingEvents || busy} onClick={() => void loadEvents()}>
                {loadingEvents ? "Refreshing…" : "Refresh"}
              </Button>
            )}
          </div>
          {connected ? (
            <>
              {loadingEvents && events.length === 0 && (
                <Card className="p-5 text-xs text-muted">Loading calendar events…</Card>
              )}
              {!loadingEvents && events.length === 0 && !error && (
                <Card className="p-6 text-center">
                  <CalendarDays size={20} className="mx-auto text-muted" />
                  <h3 className="mt-3 text-sm font-semibold">No upcoming events</h3>
                  <p className="mt-1 text-xs text-muted">
                    Your connected calendar has no events in the next 90 days.
                  </p>
                </Card>
              )}
              {events.map((event) => (
                <Card key={`${event.calendar_id}:${event.id}`} className="border-l-[3px] border-l-accent p-4 sm:p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 text-[10px] text-muted">
                        <Clock3 size={12} />
                        {displayDate(event.start)} – {displayDate(event.end)}
                      </div>
                      <h3 className="mt-2 text-sm font-semibold">{event.summary}</h3>
                    </div>
                    <span className="rounded-md bg-green-500/10 px-2 py-1 text-[9px] text-green-700 dark:text-green-400">
                      GOOGLE CALENDAR
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-[10px] text-muted">
                    <span className="flex items-center gap-1.5">
                      <Users size={12} /> {event.attendees.length ? event.attendees.join(", ") : "No attendees listed"}
                    </span>
                    {event.html_link && (
                      <a
                        href={event.html_link}
                        target="_blank"
                        rel="noreferrer"
                        className="flex items-center gap-1.5 text-accent"
                      >
                        <Video size={12} /> Open in Google Calendar
                      </a>
                    )}
                  </div>
                  {event.description && (
                    <p className="mt-3 whitespace-pre-wrap text-[11px] leading-5 text-subtle">
                      {event.description}
                    </p>
                  )}
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button disabled={busy} onClick={() => void prepareMeeting(event)}>
                      <Sparkles size={13} /> Prepare with AI
                    </Button>
                    <Button
                      disabled={busy || !canWriteCalendar(event.calendar_id) || /^\d{4}-\d{2}-\d{2}$/.test(event.start)}
                      onClick={() => openEditForm(event)}
                    >
                      <Pencil size={13} /> Edit
                    </Button>
                    <Button
                      disabled={busy || !canWriteCalendar(event.calendar_id)}
                      onClick={() => void removeEvent(event)}
                    >
                      <Trash2 size={13} /> Delete
                    </Button>
                  </div>
                  { /^\d{4}-\d{2}-\d{2}$/.test(event.start) && (
                    <p className="mt-2 text-[10px] text-muted">
                      This all-day event is displayed read-only; timed-event editing is not applied to it.
                    </p>
                  )}
                  {assistantEvent?.id === event.id && (
                    <div className="mt-4 rounded-lg border border-accent/20 bg-accent/5 p-3">
                      <p className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-accent">
                        AI-generated meeting preparation
                      </p>
                      {assistantError && <p role="alert" className="text-xs text-rose-600">{assistantError}</p>}
                      {!assistantResult && !assistantError && (
                        <p className="text-xs text-muted">Preparing meeting notes…</p>
                      )}
                      {assistantResult && (
                        <div className="space-y-2 text-[11px] leading-5 text-subtle">
                          {assistantResult.summary && <p>{assistantResult.summary}</p>}
                          {assistantResult.agenda.length > 0 && (
                            <ul className="list-disc space-y-1 pl-4">
                              {assistantResult.agenda.map((item, index) => <li key={`${index}:${item}`}>{item}</li>)}
                            </ul>
                          )}
                          {assistantResult.suggested_times.length > 0 && (
                            <p>
                              Suggested times mentioned in context: {assistantResult.suggested_times.join(", ")}.
                              Calendar availability and attendee availability are not confirmed.
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </Card>
              ))}
              {nextPageToken && (
                <Button
                  className="w-full justify-center"
                  disabled={loadingEvents || busy}
                  onClick={() => void loadEvents(nextPageToken)}
                >
                  {loadingEvents ? "Loading…" : "Load more events"}
                </Button>
              )}
            </>
          ) : (
            demoMeetings.map((meeting) => (
              <Card key={meeting.title} className={`border-l-[3px] ${meeting.color} p-4 sm:p-5`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2 text-[10px] text-muted">
                      <Clock3 size={12} /> {meeting.time}
                    </div>
                    <h3 className="mt-2 text-sm font-semibold">{meeting.title}</h3>
                  </div>
                  <span className="rounded-md bg-soft px-2 py-1 text-[9px] text-muted">SAMPLE</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-[10px] text-muted">
                  <span className="flex items-center gap-1.5"><Users size={12} />{meeting.people}</span>
                  <span className="flex items-center gap-1.5"><Video size={12} />{meeting.location}</span>
                </div>
                <div className="mt-4 rounded-lg bg-soft/70 p-3">
                  <p className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-faint">Demo meeting brief</p>
                  <p className="text-[11px] leading-5 text-subtle">{meeting.summary}</p>
                </div>
              </Card>
            ))
          )}
        </div>

        <div className="space-y-5">
          <Card className="p-5">
            <div className="flex items-center gap-2">
              <CalendarDays size={16} className="text-accent" />
              <h2 className="text-sm font-semibold">Availability</h2>
            </div>
            {connected ? (
              <>
                <p className="mt-1 text-xs text-muted">
                  Free slots from the selected calendar only; attendee availability is not checked.
                </p>
                <div className="mt-4 flex gap-2">
                  <input
                    aria-label="Availability date"
                    type="date"
                    value={availabilityDate}
                    onChange={(event) => setAvailabilityDate(event.target.value)}
                    className="input h-9 min-w-0 flex-1 px-2 text-xs"
                  />
                  <Button disabled={busy} onClick={() => void checkAvailability()}>
                    {busy ? "Checking…" : "Find"}
                  </Button>
                </div>
                {availabilityError && <p role="alert" className="mt-3 text-xs text-rose-600">{availabilityError}</p>}
                {availability && (
                  <div className="mt-4 space-y-2">
                    {availability.slots.length ? availability.slots.map((slot) => (
                      <div key={slot.start} className="flex items-center gap-2 text-[10px]">
                        <span className="size-2 rounded-full bg-green-500" />
                        <span>{displayDate(slot.start)} – {displayDate(slot.end)}</span>
                      </div>
                    )) : (
                      <p className="text-xs text-muted">No 30-minute openings found in configured work hours.</p>
                    )}
                    <p className="border-t border-line pt-2 text-[9px] leading-4 text-muted">
                      Availability scope: connected user&apos;s calendar only.
                    </p>
                  </div>
                )}
              </>
            ) : (
              <>
                <p className="mt-1 text-xs text-muted">Illustrative working hours · not synced</p>
                <div className="mt-5 space-y-3">
                  {[
                    ["9:00 AM", "Available", "bg-green-500"],
                    ["10:30 AM", "Design critique", "bg-accent"],
                    ["11:30 AM", "Available", "bg-green-500"],
                    ["2:00 PM", "Product sync", "bg-violet-400"],
                    ["3:00 PM", "Available", "bg-green-500"],
                  ].map(([hour, label, color]) => (
                    <div key={hour} className="flex items-center gap-3 text-[10px]">
                      <span className="w-14 shrink-0 text-muted">{hour}</span>
                      <span className="h-5 w-1 rounded-full bg-line"><span className={`block h-full rounded-full ${color}`} /></span>
                      <span className={label === "Available" ? "text-green-700 dark:text-green-400" : "text-subtle"}>{label}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 flex items-center gap-2 rounded-lg border border-dashed border-line p-3 text-[10px] leading-4 text-muted">
                  <MapPin size={13} className="shrink-0" />
                  Sample availability. Connect Google Calendar to check your own calendar.
                </div>
              </>
            )}
          </Card>
          {!connected && (
            <Card className="p-5">
              <h2 className="text-sm font-semibold">Meeting preparation</h2>
              <p className="mt-2 text-xs leading-5 text-muted">
                Sample summaries are examples only.                 {calendar?.requires_reconnect ? "Reconnect Calendar" : "Connect Calendar"} to load your real events and request Gemini-generated preparation.
              </p>
              <Button
                className="mt-4 w-full justify-center"
                variant="primary"
                disabled={busy || statusLoading}
                onClick={handleConnect}
              >
                <CalendarDays size={14} /> Connect Google Calendar
              </Button>
            </Card>
          )}
          {connected && (
            <Button className="w-full justify-center" disabled={busy} onClick={handleDisconnect}>
              Disconnect Calendar
            </Button>
          )}
        </div>
      </div>
      {eventReview && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="calendar-event-review-title"
            className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-line bg-panel p-5 shadow-xl"
          >
            <h2 id="calendar-event-review-title" className="text-base font-semibold">
              {eventReview.action === "delete"
                ? "Review event deletion"
                : `Review before ${eventReview.action === "create" ? "creating" : "updating"}`}
            </h2>
            <p className="mt-1 text-xs text-muted">
              {eventReview.action === "delete"
                ? "This event will be permanently deleted from Google Calendar."
                : "Confirm these exact details before Google Calendar is changed."}
            </p>
            <dl className="mt-4 space-y-3 text-xs">
              {eventReview.action === "delete" ? (
                <>
                  <div><dt className="font-semibold text-muted">Title</dt><dd className="mt-1">{eventReview.event.summary}</dd></div>
                  <div><dt className="font-semibold text-muted">Starts</dt><dd className="mt-1">{displayDateInZone(eventReview.event.start, eventReview.event.time_zone ?? timeZone)}</dd></div>
                  <div><dt className="font-semibold text-muted">Ends</dt><dd className="mt-1">{displayDateInZone(eventReview.event.end, eventReview.event.time_zone ?? timeZone)}</dd></div>
                  <div><dt className="font-semibold text-muted">Time zone</dt><dd className="mt-1">{eventReview.event.time_zone ?? timeZone}</dd></div>
                  <div><dt className="font-semibold text-muted">Attendees</dt><dd className="mt-1 break-words">{eventReview.event.attendees.join(", ") || "None"}</dd></div>
                  {eventReview.event.description && <div><dt className="font-semibold text-muted">Description</dt><dd className="mt-1 whitespace-pre-wrap">{eventReview.event.description}</dd></div>}
                </>
              ) : (
                <>
                  <div><dt className="font-semibold text-muted">Title</dt><dd className="mt-1">{eventReview.input.summary}</dd></div>
                  <div><dt className="font-semibold text-muted">Starts</dt><dd className="mt-1">{displayDateInZone(eventReview.input.start, eventReview.input.time_zone)}</dd></div>
                  <div><dt className="font-semibold text-muted">Ends</dt><dd className="mt-1">{displayDateInZone(eventReview.input.end, eventReview.input.time_zone)}</dd></div>
                  <div><dt className="font-semibold text-muted">Time zone</dt><dd className="mt-1">{eventReview.input.time_zone}</dd></div>
                  <div><dt className="font-semibold text-muted">Attendees</dt><dd className="mt-1 break-words">{eventReview.input.attendees.join(", ") || "None"}</dd></div>
                  {eventReview.input.description && <div><dt className="font-semibold text-muted">Description</dt><dd className="mt-1 whitespace-pre-wrap">{eventReview.input.description}</dd></div>}
                  <div>
                    <dt className="font-semibold text-muted">Scheduling conflicts</dt>
                    <dd className="mt-1">
                      {eventReview.conflicts.length
                        ? eventReview.conflicts.map((item) => `${item.summary} (${displayDateInZone(item.start, item.time_zone ?? eventReview.input.time_zone)})`).join("; ")
                        : "None found on this calendar"}
                    </dd>
                  </div>
                </>
              )}
            </dl>
            {(eventReview.action === "delete"
              ? eventReview.event.attendees.length > 0
              : eventReview.input.attendees.length > 0) && (
              <p className="mt-3 text-[10px] leading-5 text-muted">
                Google may notify listed attendees about this change.
              </p>
            )}
            {eventWriteUncertain && (
              <p role="alert" className="mt-3 text-xs leading-5 text-rose-600">
                Google&apos;s response was uncertain. Do not retry this write yet; reload the selected calendar to check its current state.
              </p>
            )}
            <div className="mt-5 flex justify-end gap-2">
              {!eventWriteUncertain && (
                <Button disabled={busy} onClick={() => setEventReview(null)}>Cancel</Button>
              )}
              {eventWriteUncertain ? (
                <Button
                  variant="primary"
                  disabled={busy}
                  onClick={() => void reconcileUncertainEventWrite()}
                >
                  {busy ? "Refreshing…" : "Refresh events"}
                </Button>
              ) : (
                <Button
                  variant="primary"
                  disabled={
                    busy ||
                    (eventReview.action === "delete"
                      ? !canWriteCalendar(eventReview.event.calendar_id)
                      : !canWriteCalendar(eventReview.calendarId))
                  }
                  onClick={() => void (eventReview.action === "delete"
                    ? confirmEventDelete()
                    : confirmEventWrite())}
                >
                  {busy ? "Working…" : eventReview.action === "delete"
                    ? "Confirm delete"
                    : eventReview.action === "create"
                      ? "Confirm and create"
                      : "Confirm and update"}
                </Button>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
