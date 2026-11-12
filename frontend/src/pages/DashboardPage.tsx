import { useEffect, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  CalendarClock,
  CalendarDays,
  Mail,
  Sparkles,
  Star,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Card, DemoNotice, PageHeading } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import {
  getAIInsights,
  getAnalyticsOverview,
  getCalendarStatus,
  getDashboardOverview,
  getGmailStatus,
  listCalendarEvents,
  listEmails,
} from "../services/api";
import type {
  AIInsights,
  AnalyticsOverview,
  CalendarEventRecord,
  CalendarStatus,
  DashboardOverview,
  EmailRecord,
  GmailStatus,
} from "../types/api";

function greetingName(displayName: string | null, email: string): string {
  if (displayName?.trim()) return displayName.trim().split(/\s+/)[0];
  return email.split("@")[0] || "there";
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(date);
}

export default function DashboardPage() {
  const { user } = useAuth();
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [gmail, setGmail] = useState<GmailStatus | null>(null);
  const [calendar, setCalendar] = useState<CalendarStatus | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null);
  const [insights, setInsights] = useState<AIInsights | null>(null);
  const [priorityEmails, setPriorityEmails] = useState<EmailRecord[]>([]);
  const [meetings, setMeetings] = useState<CalendarEventRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [coreError, setCoreError] = useState<string | null>(null);
  const [aiError, setAIError] = useState<string | null>(null);
  const [calendarError, setCalendarError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [dashboard, gmailStatus, calendarStatus, analyticsData, emailPage] =
          await Promise.all([
            getDashboardOverview(),
            getGmailStatus(),
            getCalendarStatus(),
            getAnalyticsOverview(7),
            listEmails({ page: 1, page_size: 5, priority: true, unread: true }),
          ]);
        if (!active) return;
        setOverview(dashboard);
        setGmail(gmailStatus);
        setCalendar(calendarStatus);
        setAnalytics(analyticsData);
        setPriorityEmails(emailPage.items);

        if (gmailStatus.connected) {
          try {
            setInsights(await getAIInsights());
            setAIError(null);
          } catch (reason) {
            setAIError(
              reason instanceof Error ? reason.message : "AI insights are unavailable.",
            );
          }
        } else {
          setInsights(null);
          setAIError(null);
        }

        if (calendarStatus.connected) {
          try {
            const eventPage = await listCalendarEvents({
              days: 7,
              time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
            });
            setMeetings(eventPage.items.slice(0, 3));
            setCalendarError(null);
          } catch (reason) {
            setCalendarError(
              reason instanceof Error ? reason.message : "Calendar events are unavailable.",
            );
          }
        } else {
          setMeetings([]);
          setCalendarError(null);
        }
      } catch (reason) {
        if (active) {
          setCoreError(
            reason instanceof Error ? reason.message : "Dashboard data could not be loaded.",
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  const cards = overview
    ? [
        { label: "Messages in selected data", value: overview.total_emails, icon: Mail },
        { label: "Unread", value: overview.unread_emails, icon: ArrowUpRight },
        { label: "Drafts", value: overview.drafts, icon: Sparkles },
        { label: "Upcoming meetings", value: calendar?.connected ? meetings.length : "—", icon: CalendarClock },
      ]
    : [];
  const maximum = Math.max(
    1,
    ...(analytics?.daily.map((item) => item.received + item.sent) ?? []),
  );
  const userName = user ? greetingName(user.display_name, user.email) : "there";
  const sourceNotice =
    analytics?.source === "gmail"
      ? gmail?.connected
        ? "Connected Gmail · synchronized data"
        : "Saved Gmail snapshot · connection inactive"
      : "Sample workspace · fictional data";

  return (
    <div>
      <PageHeading
        eyebrow={new Intl.DateTimeFormat(undefined, { dateStyle: "full" }).format(new Date())}
        title={`Good day, ${userName}`}
        description="A measured overview of your connected workspace."
        action={<DemoNotice>{sourceNotice}</DemoNotice>}
      />
      {coreError && (
        <p role="alert" className="mb-5 rounded-xl border border-rose-500/20 bg-rose-500/5 px-4 py-3 text-xs text-rose-700 dark:text-rose-300">
          {coreError}
        </p>
      )}
      {loading && <p role="status" className="mb-5 text-xs text-muted">Loading dashboard data…</p>}
      {overview && (
        <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {cards.map(({ label, value, icon: Icon }) => (
            <Card key={label} className="p-4 sm:p-5">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted">{label}</span>
                <Icon size={16} className="text-faint" />
              </div>
              <div className="mt-4 text-2xl font-semibold tracking-tight">{value}</div>
            </Card>
          ))}
        </div>
      )}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(310px,0.9fr)]">
        <div className="space-y-5">
          {insights && (
            <Card className="p-5 sm:p-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2"><Sparkles size={16} className="text-accent" /><h2 className="text-sm font-semibold">Gmail intelligence</h2></div>
                  <p className="mt-1 text-xs text-muted">Computed counts are separated from Gemini-generated interpretation.</p>
                </div>
                <span className="rounded-lg border border-accent/20 bg-accent/5 px-2.5 py-1 text-[10px] text-accent">AI-GENERATED · REVIEW</span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <div className="rounded-xl bg-soft p-3"><p className="text-[11px] text-muted">Unread · computed</p><p className="mt-1 text-xl font-semibold">{insights.computed.unread_emails}</p></div>
                <div className="rounded-xl bg-soft p-3"><p className="text-[11px] text-muted">Important unread · computed</p><p className="mt-1 text-xl font-semibold">{insights.computed.important_unread_emails}</p></div>
                <div className="rounded-xl bg-soft p-3"><p className="text-[11px] text-muted">Potential replies · model estimate</p><p className="mt-1 text-xl font-semibold">{insights.ai_generated.waiting_for_reply ?? "Unavailable"}</p></div>
              </div>
              {insights.ai_generated.briefing && <p className="mt-4 rounded-lg border border-line px-3 py-3 text-xs leading-5 text-subtle">{insights.ai_generated.briefing}</p>}
              {[...insights.ai_generated.urgent, ...insights.ai_generated.priorities, ...insights.ai_generated.deadlines].map((item, index) => {
                const source = insights.sources[item.source_index];
                const label = index < insights.ai_generated.urgent.length
                  ? "Potentially urgent"
                  : index < insights.ai_generated.urgent.length + insights.ai_generated.priorities.length
                    ? "Suggested priority"
                    : "Mentioned deadline";
                return (
                  <p key={`${item.source_index}-${index}`} className="mt-2 text-xs text-subtle">
                    <span className="font-medium text-accent">{label}:</span> {item.text}
                    {source ? ` — ${source.subject || source.sender}` : ""}
                    <span className="block text-[10px] text-muted">Evidence: “{item.evidence}”</span>
                  </p>
                );
              })}
              <Link to="/inbox" className="mt-4 inline-block text-xs font-medium text-accent hover:underline">Review Gmail messages</Link>
            </Card>
          )}
          {aiError && (
            <p role="alert" className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-xs text-amber-700">{aiError}</p>
          )}
          {!gmail?.connected && !loading && (
            <Card className="p-5">
              <div className="flex items-center gap-2"><Sparkles size={16} className="text-accent" /><h2 className="text-sm font-semibold">AI briefing</h2></div>
              <p className="mt-2 text-xs leading-5 text-muted">
                Grounded Gmail insights are unavailable until Gmail is connected and synchronized. No sample AI response is shown.
              </p>
              <Link to="/settings" className="mt-3 inline-block text-xs font-medium text-accent hover:underline">Connect Gmail in Settings</Link>
            </Card>
          )}
          {analytics && (
            <Card className="p-5 sm:p-6">
              <div className="flex items-start justify-between gap-3">
                <div><h2 className="text-sm font-semibold">Email activity</h2><p className="mt-1 text-xs text-muted">Received and sent records · last 7 days</p></div>
                <span className="rounded border border-line px-2 py-1 text-[9px] text-muted">{analytics.source === "gmail" ? "SYNCHRONIZED" : "SAMPLE"}</span>
              </div>
              {analytics.daily.every((item) => item.received + item.sent === 0) ? (
                <p className="mt-6 text-xs text-muted">No email activity recorded in this period.</p>
              ) : (
                <div className="mt-7 flex h-36 items-end gap-1.5 border-b border-line px-1 sm:gap-2">
                  {analytics.daily.map((item) => (
                    <div key={item.day} className="group relative flex h-full flex-1 items-end justify-center gap-0.5" title={`${item.day}: ${item.received} received, ${item.sent} sent`}>
                      <span className="w-[40%] rounded-t-sm bg-accent/75" style={{ height: `${(item.received / maximum) * 100}%` }} />
                      <span className="w-[40%] rounded-t-sm bg-violet-400/75" style={{ height: `${(item.sent / maximum) * 100}%` }} />
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-4 flex gap-5 text-[10px] text-muted">
                <span><i className="mr-1.5 inline-block size-2 rounded-sm bg-accent/75" />Received</span>
                <span><i className="mr-1.5 inline-block size-2 rounded-sm bg-violet-400/75" />Sent</span>
                <Link to="/analytics" className="ml-auto inline-flex items-center gap-1 text-accent hover:underline">Full analytics <ArrowRight size={12} /></Link>
              </div>
            </Card>
          )}
          <Card className="p-5 sm:p-6">
            <div className="mb-4 flex items-center justify-between">
              <div><h2 className="text-sm font-semibold">Priority inbox</h2><p className="mt-1 text-xs text-muted">Unread messages marked important or starred</p></div>
              <Link to="/inbox" className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline">View inbox <ArrowRight size={13} /></Link>
            </div>
            {priorityEmails.length === 0 ? (
              <p className="text-xs text-muted">No unread priority messages are available in the selected dataset.</p>
            ) : (
              <div className="divide-y divide-line">
                {priorityEmails.map((email) => (
                  <Link key={email.id} to="/inbox" className="flex items-center gap-3 py-3">
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-amber-500/10 text-amber-600"><Star size={14} /></span>
                    <span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium">{email.sender}</span><span className="mt-1 block truncate text-[11px] text-muted">{email.subject || "(no subject)"}</span></span>
                    <span className={`rounded px-2 py-1 text-[8px] ${email.source === "gmail" ? "bg-green-500/10 text-green-700" : "bg-soft text-muted"}`}>{email.source === "gmail" ? "GMAIL" : "SAMPLE"}</span>
                  </Link>
                ))}
              </div>
            )}
          </Card>
        </div>
        <div className="space-y-5">
          <Card className="p-5">
            <div className="flex items-center justify-between">
              <div><h2 className="text-sm font-semibold">Upcoming meetings</h2><p className="mt-1 text-xs text-muted">{calendar?.connected ? "Connected Google Calendar" : "Calendar is not connected"}</p></div>
              <Link to="/meetings" className="text-xs text-accent hover:underline">View all</Link>
            </div>
            {calendarError && <p role="alert" className="mt-3 text-xs text-rose-600">{calendarError}</p>}
            {meetings.length ? (
              <div className="mt-4 space-y-3">
                {meetings.map((event) => (
                  <div key={`${event.calendar_id}:${event.id}`} className="flex gap-3">
                    <div className="w-12 shrink-0 border-r-2 border-accent pl-2 text-[10px] font-medium text-muted">{formatTime(event.start)}</div>
                    <div className="min-w-0 pb-2"><p className="truncate text-xs font-medium">{event.summary}</p><p className="mt-1 truncate text-[10px] text-muted">{event.attendees.length ? `${event.attendees.length} attendee(s)` : "No attendees listed"}</p></div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-4 rounded-lg bg-soft px-3 py-3 text-[10px] leading-4 text-muted">
                <CalendarDays size={13} className="mr-1.5 inline" />
                {calendar?.connected ? "No upcoming meetings in the next 7 days." : "No real calendar data is shown. Connect Calendar to load your events."}
              </div>
            )}
          </Card>
          <Card className="p-5">
            <div className="flex items-center gap-2"><Mail size={15} className="text-accent" /><h2 className="text-sm font-semibold">Inbox health</h2></div>
            {overview && (
              <div className="mt-4 space-y-3">
                {[
                  ["Unread", overview.unread_emails],
                  ["Starred", overview.starred_emails],
                  ["Priority", overview.priority_emails],
                ].map(([label, count]) => (
                  <div key={label}>
                    <div className="mb-1.5 flex justify-between text-[10px]"><span className="text-muted">{label}</span><span className="font-medium">{count}</span></div>
                    <div className="h-1.5 rounded-full bg-soft"><div className="h-1.5 rounded-full bg-accent" style={{ width: `${overview.total_emails ? Math.min(100, (Number(count) / overview.total_emails) * 100) : 0}%` }} /></div>
                  </div>
                ))}
              </div>
            )}
            <p className="mt-4 text-[10px] text-faint">Computed counts · {sourceNotice}</p>
          </Card>
        </div>
      </div>
    </div>
  );
}
