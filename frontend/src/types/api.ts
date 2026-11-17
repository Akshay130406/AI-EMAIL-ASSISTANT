export interface HealthResponse {
  status: "ok";
}

export interface PageResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Timestamped {
  id: string;
  created_at: string;
  updated_at: string;
}

export interface EmailRecord extends Timestamped {
  user_id: string;
  external_message_id: string | null;
  thread_id: string | null;
  source: "sample" | "gmail";
  sender: string;
  recipients: string[];
  subject: string;
  body: string | null;
  html_body: string | null;
  preview: string | null;
  is_read: boolean;
  is_sent: boolean;
  is_starred: boolean;
  is_priority: boolean;
  received_at: string | null;
}

export interface GmailStatus {
  connected: boolean;
  email: string | null;
  status: "connected" | "disconnected" | "pending" | "not_connected";
  last_synced_at: string | null;
  requires_reconnect: boolean;
  compose_enabled: boolean;
}

export interface GmailSyncResult {
  synced: number;
  incremental: boolean;
}

export interface AutoReplySettings {
  enabled: boolean;
  automatic_sending_enabled: boolean;
  mode: "off" | "draft" | "automatic_send";
  interval_minutes: number;
  daily_limit: number;
  reply_required_only: boolean;
  exclude_sensitive: boolean;
  allowed_senders: string[];
  blocked_senders: string[];
  include_keywords: string[];
  exclude_keywords: string[];
  next_run_at: string | null;
  gmail_connected: boolean;
  compose_enabled: boolean;
}

export interface AutoReplyActivity {
  id: string;
  email_id: string;
  email_subject: string;
  email_sender: string;
  status: "processing" | "draft_created" | "sent" | "skipped" | "failed" | "unknown";
  reason_code: string | null;
  gmail_draft_id: string | null;
  gmail_message_id: string | null;
  created_at: string;
}

export interface AutoReplyActivityPage {
  items: AutoReplyActivity[];
  total: number;
  page: number;
  page_size: number;
}

export interface DraftRecord extends Timestamped {
  user_id: string;
  recipient: string | null;
  subject: string;
  body: string;
  status: "draft" | "ready" | "archived";
  recipients: string[];
  cc: string[];
  bcc: string[];
  gmail_draft_id: string | null;
  gmail_message_id: string | null;
  send_status: "not_sent" | "sending" | "sent" | "unknown" | "failed";
}

export interface GmailDraftRequest {
  recipients: string[];
  cc: string[];
  bcc: string[];
  subject: string;
  body: string;
}

export interface GmailSendStatus {
  draft_id: string;
  status: "not_sent" | "sending" | "sent" | "unknown" | "failed";
  gmail_message_id: string | null;
}

export interface DraftCreateRequest {
  recipient?: string | null;
  subject?: string;
  body?: string;
  status?: DraftRecord["status"];
}

export interface ConversationRecord {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationMessageRecord {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
}

export interface NotificationPreferences {
  inbox_reminders: boolean;
  writing_suggestions: boolean;
  product_updates: boolean;
}

export interface AIPreferences {
  default_tone: "professional" | "friendly" | "formal" | "concise";
  always_review_drafts: boolean;
}

export interface UserSettingsRecord {
  id: string;
  user_id: string;
  theme: "light" | "dark" | "system";
  notification_preferences: NotificationPreferences;
  ai_preferences: AIPreferences;
  created_at: string;
  updated_at: string;
}

export interface SettingsPatchRequest {
  theme?: UserSettingsRecord["theme"];
  notification_preferences?: Partial<NotificationPreferences>;
  ai_preferences?: Partial<AIPreferences>;
}

export interface DashboardOverview {
  total_emails: number;
  unread_emails: number;
  starred_emails: number;
  priority_emails: number;
  drafts: number;
  conversations: number;
}

export type AITone =
  | "Professional"
  | "Friendly"
  | "Formal"
  | "Concise"
  | "Persuasive"
  | "Appreciative";

export interface EvidenceItem {
  text: string;
  evidence: string;
}

export interface DeadlineEvidence {
  date_text: string;
  evidence: string;
}

export interface AIClassification {
  category:
    | "Important"
    | "Work"
    | "Personal"
    | "Promotions"
    | "Social"
    | "Finance"
    | "Updates"
    | "Other";
  priority: "High" | "Medium" | "Low";
  urgency: "High" | "Medium" | "Low" | "Unclear";
  response_required: boolean | null;
  deadlines: DeadlineEvidence[];
  confidence: number;
  explanation: string;
}

export interface AIEmailSummary {
  summary: string;
  important_points: EvidenceItem[];
  action_items: EvidenceItem[];
  deadlines: DeadlineEvidence[];
  people_or_organizations: EvidenceItem[];
  questions_requiring_response: EvidenceItem[];
}

export interface AIWriteResponse {
  subject: string;
  body: string;
  subject_suggestions: string[];
}

export interface AIRewriteResponse {
  content: string;
}

export interface AIReplySuggestion {
  subject: string;
  body: string;
}

export interface AICopilotResult {
  answer: string;
  sources: Array<{ email_id: string; subject: string; sender: string }>;
}

export interface AIInsightItem {
  text: string;
  source_index: number;
  evidence: string;
}

export interface AIInsights {
  computed: {
    unread_emails: number;
    important_unread_emails: number;
    starred_emails: number;
  };
  ai_generated: {
    waiting_for_reply: number | null;
    briefing: string | null;
    priorities: AIInsightItem[];
    urgent: AIInsightItem[];
    deadlines: AIInsightItem[];
  };
  sources: Array<{ email_id: string; subject: string; sender: string }>;
  generated_at: string | null;
}

export interface CalendarStatus {
  connected: boolean;
  status: "connected" | "disconnected" | "not_connected";
  email: string | null;
  requires_reconnect: boolean;
}

export interface CalendarRecord {
  id: string;
  summary: string;
  time_zone: string | null;
  primary: boolean;
  access_role: string | null;
}

export interface CalendarListResponse {
  items: CalendarRecord[];
  next_page_token: string | null;
}

export interface CalendarEventRecord {
  id: string;
  calendar_id: string;
  summary: string;
  description: string;
  start: string;
  end: string;
  time_zone: string | null;
  attendees: string[];
  html_link: string | null;
  status: string | null;
}

export interface CalendarEventPage {
  items: CalendarEventRecord[];
  next_page_token: string | null;
}

export interface CalendarEventInput {
  summary: string;
  description: string;
  start: string;
  end: string;
  time_zone: string;
  attendees: string[];
}

export interface CalendarAvailability {
  time_zone: string;
  availability_scope: "connected_user_calendar_only";
  slots: Array<{
    start: string;
    end: string;
    time_zone: string;
    calendar_free: boolean;
  }>;
}

export interface MeetingAssistantResult {
  title: string;
  summary: string;
  agenda: string[];
  attendees: string[];
  suggested_times: string[];
  source_email_ids: string[];
  calendar_availability_confirmed: false;
}

export type AutomationKind =
  | "gmail_sync"
  | "daily_briefing"
  | "follow_up_reminder";

export interface AutomationRecord {
  id: string;
  kind: AutomationKind;
  enabled: boolean;
  interval_minutes: number;
  next_run_at: string;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface BackgroundJobRecord {
  id: string;
  automation_id: string | null;
  job_type: AutomationKind;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  attempts: number;
  max_attempts: number;
  available_at: string;
  started_at: string | null;
  finished_at: string | null;
  last_error_code: string | null;
  result_summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotificationRecord {
  id: string;
  source_job_id: string | null;
  kind: AutomationKind | "job";
  title: string;
  message: string;
  data: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

export interface NotificationPage {
  items: NotificationRecord[];
  total: number;
  unread_count: number;
  page: number;
  page_size: number;
}

export interface AnalyticsOverview {
  source: "gmail" | "sample";
  period_days: number;
  total_received: number;
  total_sent: number;
  unread: number;
  starred: number;
  priority: number;
  daily: Array<{ day: string; received: number; sent: number }>;
  generated_at: string;
}
