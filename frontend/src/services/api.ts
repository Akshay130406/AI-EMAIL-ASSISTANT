import type {
  ConversationMessageRecord,
  ConversationRecord,
  AICopilotResult,
  AIEmailSummary,
  AIInsights,
  AIReplySuggestion,
  AIRewriteResponse,
  AIClassification,
  AITone,
  AIWriteResponse,
  AutomationKind,
  AutomationRecord,
  AnalyticsOverview,
  BackgroundJobRecord,
  CalendarAvailability,
  CalendarListResponse,
  CalendarEventInput,
  CalendarEventPage,
  CalendarEventRecord,
  CalendarStatus,
  DashboardOverview,
  DraftCreateRequest,
  DraftRecord,
  EmailRecord,
  HealthResponse,
  GmailStatus,
  GmailSyncResult,
  GmailDraftRequest,
  GmailSendStatus,
  PageResponse,
  SettingsPatchRequest,
  UserSettingsRecord,
  MeetingAssistantResult,
  NotificationPage,
  NotificationRecord,
} from "../types/api";
import type { AuthMeResponse } from "../types/auth";

const apiUrl = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8002").replace(
  /\/$/,
  "",
);
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export class APIError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "APIError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (
    csrfToken &&
    ["POST", "PATCH", "PUT", "DELETE"].includes((init?.method || "GET").toUpperCase())
  ) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${apiUrl}/api${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const error = (await response.json()) as { detail?: unknown };
      if (typeof error.detail === "string") message = error.detail;
    } catch {
      // Keep the status-based message for non-JSON responses.
    }
    throw new APIError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function getCurrentUser(): Promise<AuthMeResponse> {
  return request<AuthMeResponse>("/auth/me");
}

export async function logout(): Promise<void> {
  await request<void>("/auth/logout", { method: "POST" });
}

export function beginGoogleSignIn(): void {
  window.location.assign(`${apiUrl}/api/auth/google`);
}

function queryString(params: Record<string, string | number | boolean | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) query.set(key, String(value));
  }
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export function getDashboardOverview(): Promise<DashboardOverview> {
  return request<DashboardOverview>("/dashboard/overview");
}

export function getAnalyticsOverview(periodDays = 7): Promise<AnalyticsOverview> {
  return request(`/analytics/overview${queryString({ period_days: periodDays })}`);
}

export function classifyEmail(emailId: string): Promise<AIClassification> {
  return request(`/ai/classify/${encodeURIComponent(emailId)}`, { method: "POST" });
}

export function summarizeEmail(emailId: string): Promise<AIEmailSummary> {
  return request(`/ai/summarize/${encodeURIComponent(emailId)}`, { method: "POST" });
}

export function summarizeEmailThread(threadId: string): Promise<AIEmailSummary> {
  return request(`/ai/summarize-thread/${encodeURIComponent(threadId)}`, { method: "POST" });
}

export function writeEmail(payload: {
  action?: "generate" | "subject_lines";
  instructions: string;
  recipient?: string;
  subject?: string;
  body?: string;
  tone?: AITone;
}): Promise<AIWriteResponse> {
  return request("/ai/write", { method: "POST", body: JSON.stringify(payload) });
}

export function rewriteEmail(payload: {
  action: "rewrite" | "improve" | "shorten" | "expand";
  content: string;
  tone?: AITone;
  instructions?: string;
}): Promise<AIRewriteResponse> {
  return request("/ai/rewrite", { method: "POST", body: JSON.stringify(payload) });
}

export function suggestEmailReply(emailId: string): Promise<AIReplySuggestion> {
  return request(`/ai/reply-suggestion/${encodeURIComponent(emailId)}`, { method: "POST" });
}

export function askEmailCopilot(payload: {
  question: string;
  email_id?: string;
  thread_id?: string;
}): Promise<AICopilotResult> {
  return request("/ai/copilot", { method: "POST", body: JSON.stringify(payload) });
}

export function getAIInsights(): Promise<AIInsights> {
  return request("/ai/insights");
}

export function listEmails(params: {
  page?: number;
  page_size?: number;
  search?: string;
  unread?: boolean;
  sent?: boolean;
  starred?: boolean;
  priority?: boolean;
} = {}): Promise<PageResponse<EmailRecord>> {
  return request(`/emails${queryString(params)}`);
}

export function getEmail(emailId: string): Promise<EmailRecord> {
  return request(`/emails/${encodeURIComponent(emailId)}`);
}

export function updateEmail(
  emailId: string,
  changes: Partial<Pick<EmailRecord, "is_read" | "is_starred" | "is_priority">>,
): Promise<EmailRecord> {
  return request(`/emails/${encodeURIComponent(emailId)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function getGmailStatus(): Promise<GmailStatus> {
  return request<GmailStatus>("/integrations/gmail/status");
}

export async function beginGmailConnect(): Promise<void> {
  const result = await request<{ authorization_url: string }>(
    "/integrations/gmail/connect",
    { method: "POST" },
  );
  window.location.assign(result.authorization_url);
}

export async function beginGmailComposeConnect(): Promise<void> {
  const result = await request<{ authorization_url: string }>(
    "/integrations/gmail/compose/connect",
    { method: "POST" },
  );
  window.location.assign(result.authorization_url);
}

export function listGmailDrafts(params: {
  page?: number;
  page_size?: number;
} = {}): Promise<PageResponse<DraftRecord>> {
  return request(`/integrations/gmail/drafts${queryString(params)}`);
}

export function createGmailDraft(payload: GmailDraftRequest): Promise<DraftRecord> {
  return request("/integrations/gmail/drafts", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateGmailDraft(
  draftId: string,
  payload: GmailDraftRequest,
): Promise<DraftRecord> {
  return request(`/integrations/gmail/drafts/${encodeURIComponent(draftId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteGmailDraft(draftId: string): Promise<void> {
  return request(`/integrations/gmail/drafts/${encodeURIComponent(draftId)}`, {
    method: "DELETE",
  });
}

export function sendGmailDraft(draftId: string): Promise<GmailSendStatus> {
  return request(`/integrations/gmail/drafts/${encodeURIComponent(draftId)}/send`, {
    method: "POST",
    body: JSON.stringify({ confirm: true }),
  });
}

export function syncGmail(): Promise<GmailSyncResult> {
  return request<GmailSyncResult>("/integrations/gmail/sync", { method: "POST" });
}

export function disconnectGmail(): Promise<void> {
  return request<void>("/integrations/gmail/disconnect", { method: "DELETE" });
}

export function getCalendarStatus(): Promise<CalendarStatus> {
  return request<CalendarStatus>("/integrations/calendar/status");
}

export async function beginCalendarConnect(): Promise<void> {
  const result = await request<{ authorization_url: string }>(
    "/integrations/calendar/connect",
    { method: "POST" },
  );
  window.location.assign(result.authorization_url);
}

export function disconnectCalendar(): Promise<void> {
  return request<void>("/integrations/calendar/disconnect", { method: "DELETE" });
}

export function listCalendarEvents(params: {
  calendar_id?: string;
  days?: number;
  page_token?: string;
  time_zone?: string;
} = {}): Promise<CalendarEventPage> {
  return request(`/integrations/calendar/events/upcoming${queryString(params)}`);
}

export function listCalendars(params: {
  page_token?: string;
} = {}): Promise<CalendarListResponse> {
  return request(`/integrations/calendar/calendars${queryString(params)}`);
}

export function getCalendarEvent(
  eventId: string,
  calendarId = "primary",
): Promise<CalendarEventRecord> {
  return request(
    `/integrations/calendar/events/${encodeURIComponent(eventId)}${queryString({ calendar_id: calendarId })}`,
  );
}

export function findCalendarConflicts(
  payload: Pick<CalendarEventInput, "start" | "end" | "time_zone"> & {
    exclude_event_id?: string;
  },
  calendarId = "primary",
): Promise<{ conflicts: CalendarEventRecord[]; calendar_id: string }> {
  return request(`/integrations/calendar/events/conflicts${queryString({ calendar_id: calendarId })}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCalendarAvailability(payload: {
  date: string;
  time_zone: string;
  duration_minutes: number;
}, calendarId = "primary"): Promise<CalendarAvailability> {
  return request(`/integrations/calendar/availability${queryString({ calendar_id: calendarId })}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createCalendarEvent(
  payload: CalendarEventInput & { request_id: string },
  calendarId = "primary",
): Promise<CalendarEventRecord> {
  return request(`/integrations/calendar/events${queryString({ calendar_id: calendarId })}`, {
    method: "POST",
    body: JSON.stringify({ ...payload, confirm: true }),
  });
}

export function updateCalendarEvent(
  eventId: string,
  payload: CalendarEventInput,
  calendarId = "primary",
): Promise<CalendarEventRecord> {
  return request(`/integrations/calendar/events/${encodeURIComponent(eventId)}${queryString({ calendar_id: calendarId })}`, {
    method: "PUT",
    body: JSON.stringify({ ...payload, confirm: true }),
  });
}

export function deleteCalendarEvent(eventId: string, calendarId = "primary"): Promise<void> {
  return request(`/integrations/calendar/events/${encodeURIComponent(eventId)}${queryString({ calendar_id: calendarId })}`, {
    method: "DELETE",
    body: JSON.stringify({ confirm: true }),
  });
}

export function requestMeetingAssistance(payload: {
  operation: "agenda" | "summary" | "extract";
  event_id?: string;
  calendar_id?: string;
  email_ids?: string[];
  question?: string;
}): Promise<MeetingAssistantResult> {
  return request("/integrations/calendar/assistant", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listAutomations(): Promise<AutomationRecord[]> {
  return request("/automations");
}

export function createAutomation(payload: {
  kind: AutomationKind;
  interval_minutes: number;
  enabled: boolean;
}): Promise<AutomationRecord> {
  return request("/automations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateAutomation(
  automationId: string,
  changes: Partial<Pick<AutomationRecord, "enabled" | "interval_minutes">>,
): Promise<AutomationRecord> {
  return request(`/automations/${encodeURIComponent(automationId)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function deleteAutomation(automationId: string): Promise<void> {
  return request(`/automations/${encodeURIComponent(automationId)}`, {
    method: "DELETE",
  });
}

export function runAutomation(automationId: string): Promise<BackgroundJobRecord> {
  return request(`/automations/${encodeURIComponent(automationId)}/run`, {
    method: "POST",
  });
}

export function listBackgroundJobs(params: {
  page?: number;
  page_size?: number;
} = {}): Promise<PageResponse<BackgroundJobRecord>> {
  return request(`/jobs${queryString(params)}`);
}

export function cancelBackgroundJob(jobId: string): Promise<BackgroundJobRecord> {
  return request(`/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}

export function listNotifications(params: {
  page?: number;
  page_size?: number;
} = {}): Promise<NotificationPage> {
  return request(`/notifications${queryString(params)}`);
}

export function updateNotification(
  notificationId: string,
  read: boolean,
): Promise<NotificationRecord> {
  return request(`/notifications/${encodeURIComponent(notificationId)}`, {
    method: "PATCH",
    body: JSON.stringify({ read }),
  });
}

export function getEmailThread(emailId: string): Promise<{ messages: EmailRecord[] }> {
  return request<{ messages: EmailRecord[] }>(`/emails/${encodeURIComponent(emailId)}/thread`);
}

export function listDrafts(params: {
  page?: number;
  page_size?: number;
} = {}): Promise<PageResponse<DraftRecord>> {
  return request(`/drafts${queryString(params)}`);
}

export function createDraft(
  draft: DraftCreateRequest,
): Promise<DraftRecord> {
  return request("/drafts", { method: "POST", body: JSON.stringify(draft) });
}

export function getDraft(draftId: string): Promise<DraftRecord> {
  return request(`/drafts/${encodeURIComponent(draftId)}`);
}

export function updateDraft(
  draftId: string,
  changes: Partial<Pick<DraftRecord, "recipient" | "subject" | "body" | "status">>,
): Promise<DraftRecord> {
  return request(`/drafts/${encodeURIComponent(draftId)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function deleteDraft(draftId: string): Promise<void> {
  return request(`/drafts/${encodeURIComponent(draftId)}`, { method: "DELETE" });
}

export function listConversations(params: {
  page?: number;
  page_size?: number;
} = {}): Promise<PageResponse<ConversationRecord>> {
  return request(`/conversations${queryString(params)}`);
}

export function createConversation(title = "New conversation"): Promise<ConversationRecord> {
  return request("/conversations", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export function listConversationMessages(
  conversationId: string,
  params: { page?: number; page_size?: number } = {},
): Promise<PageResponse<ConversationMessageRecord>> {
  return request(
    `/conversations/${encodeURIComponent(conversationId)}/messages${queryString(params)}`,
  );
}

export function createConversationMessage(
  conversationId: string,
  message: { role: "user" | "assistant"; content: string },
): Promise<ConversationMessageRecord> {
  return request(
    `/conversations/${encodeURIComponent(conversationId)}/messages`,
    { method: "POST", body: JSON.stringify(message) },
  );
}

export function getSettings(): Promise<UserSettingsRecord> {
  return request("/settings");
}

export function updateSettings(
  changes: SettingsPatchRequest,
): Promise<UserSettingsRecord> {
  return request("/settings", { method: "PATCH", body: JSON.stringify(changes) });
}
