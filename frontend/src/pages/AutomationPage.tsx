import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BellRing,
  Check,
  Clock3,
  Flame,
  Mail,
  Play,
  RefreshCw,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Button, Card, DemoNotice, PageHeading } from "../components/ui";
import {
  cancelBackgroundJob,
  createAutomation,
  emergencyOffAutoReplies,
  getAutoReplyActivity,
  getAutoReplySettings,
  getGmailStatus,
  listAutomations,
  listBackgroundJobs,
  listNotifications,
  runAutomation,
  updateAutomation,
  updateAutoReplySettings,
  updateNotification,
} from "../services/api";
import type {
  AutomationKind,
  AutomationRecord,
  AutoReplyActivity,
  AutoReplySettings,
  BackgroundJobRecord,
  GmailStatus,
  NotificationRecord,
} from "../types/api";

const workflows: Array<{
  kind: AutomationKind;
  icon: typeof BellRing;
  name: string;
  description: string;
  trigger: string;
  action: string;
  interval: number;
  color: string;
}> = [
  {
    kind: "gmail_sync",
    icon: Mail,
    name: "Scheduled Gmail sync",
    description:
      "Queue a bounded read-only synchronization from your connected Gmail account.",
    trigger: "At the selected interval",
    action: "Sync inbox messages",
    interval: 60,
    color: "bg-rose-500/10 text-rose-600",
  },
  {
    kind: "daily_briefing",
    icon: Sparkles,
    name: "AI inbox briefing",
    description:
      "Prepare a Gemini briefing from synchronized Gmail messages. AI use is subject to configured per-user limits.",
    trigger: "At the selected interval",
    action: "Create a private briefing notification",
    interval: 1440,
    color: "bg-violet-500/10 text-violet-600",
  },
  {
    kind: "follow_up_reminder",
    icon: BellRing,
    name: "Follow-up review reminder",
    description:
      "Find older Gmail threads with no reply recorded in Mailmind. This cannot detect replies sent outside the app.",
    trigger: "At the selected interval",
    action: "Create a review reminder",
    interval: 1440,
    color: "bg-amber-500/10 text-amber-600",
  },
];

function intervalLabel(minutes: number): string {
  if (minutes % 1440 === 0) return `Every ${minutes / 1440} day(s)`;
  if (minutes % 60 === 0) return `Every ${minutes / 60} hour(s)`;
  return `Every ${minutes} minutes`;
}

function dateLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

export default function AutomationPage() {
  const [gmail, setGmail] = useState<GmailStatus | null>(null);
  const [automations, setAutomations] = useState<AutomationRecord[]>([]);
  const [jobs, setJobs] = useState<BackgroundJobRecord[]>([]);
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [autoReplySettings, setAutoReplySettings] = useState<AutoReplySettings | null>(null);
  const [autoReplyActivity, setAutoReplyActivity] = useState<AutoReplyActivity[]>([]);
  const [autoReplyRules, setAutoReplyRules] = useState({
    allowed_senders: "", blocked_senders: "", include_keywords: "", exclude_keywords: "",
  });
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const rulesByKind = useMemo(
    () => new Map(automations.map((rule) => [rule.kind, rule])),
    [automations],
  );

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [gmailStatus, rules, jobPage, notificationPage, replySettings, replyActivity] = await Promise.all([
        getGmailStatus(),
        listAutomations(),
        listBackgroundJobs({ page_size: 10 }),
        listNotifications({ page_size: 10 }),
        getAutoReplySettings(),
        getAutoReplyActivity(10),
      ]);
      setGmail(gmailStatus);
      setAutomations(rules);
      setJobs(jobPage.items);
      setNotifications(notificationPage.items);
      setUnreadCount(notificationPage.unread_count);
      setAutoReplySettings(replySettings);
      setAutoReplyActivity(replyActivity.items);
      setAutoReplyRules({
        allowed_senders: replySettings.allowed_senders.join(", "),
        blocked_senders: replySettings.blocked_senders.join(", "),
        include_keywords: replySettings.include_keywords.join(", "),
        exclude_keywords: replySettings.exclude_keywords.join(", "),
      });
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Automations and notifications could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function toggleWorkflow(
    kind: AutomationKind,
    interval: number,
  ) {
    const rule = rulesByKind.get(kind);
    setBusy(kind);
    setError(null);
    setNotice(null);
    try {
      if (rule) {
        const updated = await updateAutomation(rule.id, {
          enabled: !rule.enabled,
        });
        setAutomations((current) =>
          current.map((item) => (item.id === updated.id ? updated : item)),
        );
        setNotice(
          `${workflows.find((item) => item.kind === kind)?.name} ${updated.enabled ? "enabled" : "paused"}.`,
        );
      } else {
        const created = await createAutomation({
          kind,
          interval_minutes: interval,
          enabled: true,
        });
        setAutomations((current) => [...current, created]);
        setNotice(`${workflows.find((item) => item.kind === kind)?.name} enabled.`);
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The automation setting could not be saved.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function runWorkflow(rule: AutomationRecord) {
    if (!gmail?.connected) {
      setError("Connect Gmail before queueing inbox automations.");
      return;
    }
    setBusy(rule.kind);
    setError(null);
    setNotice(null);
    try {
      const job = await runAutomation(rule.id);
      setNotice(`Job queued (${job.id}). It will run when the background worker is available.`);
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The automation could not be queued.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function changeInterval(rule: AutomationRecord, interval: number) {
    setBusy(rule.kind);
    setError(null);
    try {
      const updated = await updateAutomation(rule.id, {
        interval_minutes: interval,
      });
      setAutomations((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotice("Automation schedule updated.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The schedule could not be updated.");
    } finally {
      setBusy(null);
    }
  }

  async function cancelJob(job: BackgroundJobRecord) {
    setBusy(job.id);
    setError(null);
    try {
      const result = await cancelBackgroundJob(job.id);
      setJobs((current) =>
        current.map((item) => (item.id === result.id ? result : item)),
      );
      setNotice("Queued job cancelled.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The job could not be cancelled.");
    } finally {
      setBusy(null);
    }
  }

  async function markNotification(notification: NotificationRecord) {
    setBusy(notification.id);
    setError(null);
    try {
      const updated = await updateNotification(notification.id, !notification.read_at);
      setNotifications((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setUnreadCount((count) => Math.max(0, count + (updated.read_at ? -1 : 1)));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Notification state could not be updated.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function updateReplySettings(patch: Parameters<typeof updateAutoReplySettings>[0], label: string) {
    setBusy("auto-reply");
    setError(null);
    setNotice(null);
    try {
      const updated = await updateAutoReplySettings(patch);
      setAutoReplySettings(updated);
      setNotice(label);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Automatic reply settings could not be saved.");
    } finally {
      setBusy(null);
    }
  }

  async function toggleAutoReplies() {
    if (!autoReplySettings) return;
    const enable = !autoReplySettings.enabled;
    if (enable && !window.confirm("Enable automatic replies in draft-only mode? Gemini will create Gmail drafts for matching new emails. Nothing will be sent.")) return;
    await updateReplySettings({ enabled: enable }, enable ? "Automatic replies enabled in draft-only mode." : "Automatic replies paused.");
  }

  async function toggleAutomaticSending() {
    if (!autoReplySettings) return;
    const enable = !autoReplySettings.automatic_sending_enabled;
    if (enable && !window.confirm(`Enable automatic sending? Mailmind may send Gemini-generated replies to matching senders, up to ${autoReplySettings.daily_limit} per day. Sensitive emails remain excluded. You can turn this off at any time.`)) return;
    await updateReplySettings({
      automatic_sending_enabled: enable,
      ...(enable ? { confirm_automatic_sending: true } : {}),
    }, enable ? "Automatic sending enabled by your confirmation." : "Automatic sending disabled. Draft mode remains available.");
  }

  async function saveAutoReplyRules() {
    const split = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);
    await updateReplySettings({
      allowed_senders: split(autoReplyRules.allowed_senders),
      blocked_senders: split(autoReplyRules.blocked_senders),
      include_keywords: split(autoReplyRules.include_keywords),
      exclude_keywords: split(autoReplyRules.exclude_keywords),
    }, "Automatic reply rules saved.");
  }

  async function emergencyStopAutoReplies() {
    setBusy("auto-reply");
    setError(null);
    try {
      const updated = await emergencyOffAutoReplies();
      setAutoReplySettings(updated);
      setNotice("Emergency OFF is active. Automatic replies and sending are disabled.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Emergency OFF could not be confirmed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <PageHeading
        eyebrow="Automation"
        title="Make the routine feel lighter."
        description="Schedule bounded inbox jobs and review their durable status."
        action={
          <div className="flex items-center gap-2">
            <DemoNotice>
              {gmail?.connected ? "Connected Gmail · read-only" : "Gmail connection required"}
            </DemoNotice>
            <Button disabled={loading} onClick={() => void refresh()}>
              <RefreshCw size={14} /> Refresh
            </Button>
          </div>
        }
      />
      {error && (
        <p role="alert" className="mb-4 rounded-xl border border-rose-500/20 bg-rose-500/5 px-4 py-3 text-xs leading-5 text-rose-700 dark:text-rose-300">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mb-4 rounded-xl border border-accent/20 bg-accent/5 px-4 py-3 text-xs leading-5 text-accent">
          {notice}
        </p>
      )}
      {!gmail?.connected && !loading && (
        <p className="mb-4 rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-xs leading-5 text-amber-700 dark:text-amber-300">
          Connect Gmail in <Link to="/settings" className="font-medium underline">Settings</Link> before enabling or running inbox automations. Jobs never write to Gmail.
        </p>
      )}
      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        {[
          { icon: Zap, label: "Configured automations", value: String(automations.length) },
          { icon: Check, label: "Enabled", value: String(automations.filter((item) => item.enabled).length) },
          { icon: BellRing, label: "Unread notifications", value: String(unreadCount) },
        ].map(({ icon: Icon, label, value }) => (
          <Card key={label} className="flex items-center gap-3 p-4">
            <span className="grid size-9 place-items-center rounded-xl bg-soft text-accent"><Icon size={16} /></span>
            <span><span className="block text-lg font-semibold">{value}</span><span className="block text-[10px] text-muted">{label}</span></span>
          </Card>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {workflows.map(({ kind, icon: Icon, name, description, trigger, action, interval, color }) => {
          const rule = rulesByKind.get(kind);
          return (
            <Card key={kind} className="p-5">
              <div className="flex items-start gap-3">
                <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${color}`}><Icon size={18} /></span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="text-sm font-semibold">{name}</h2>
                    <button
                      role="switch"
                      aria-checked={Boolean(rule?.enabled)}
                      aria-label={`${rule?.enabled ? "Disable" : "Enable"} ${name}`}
                      disabled={loading || busy === kind}
                      onClick={() => void toggleWorkflow(kind, interval)}
                      className={`relative h-5 w-9 rounded-full transition disabled:opacity-50 ${rule?.enabled ? "bg-accent" : "bg-slate-300 dark:bg-slate-700"}`}
                    >
                      <span className={`absolute top-0.5 size-4 rounded-full bg-white shadow transition-all ${rule?.enabled ? "left-[18px]" : "left-0.5"}`} />
                    </button>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-muted">{description}</p>
                </div>
              </div>
              <div className="mt-5 flex flex-wrap items-center gap-2 rounded-xl bg-soft/70 p-3 text-[10px]">
                <span className="text-muted">{trigger}</span><ArrowRight size={13} className="text-faint" /><span className="font-medium text-subtle">{action}</span>
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                <span className="text-[10px] text-muted">
                  {rule
                    ? `${intervalLabel(rule.interval_minutes)} · next ${dateLabel(rule.next_run_at)}`
                    : `Not configured · default ${intervalLabel(interval)}`}
                </span>
                {rule && (
                  <div className="flex items-center gap-2">
                    <label className="sr-only" htmlFor={`interval-${kind}`}>Schedule for {name}</label>
                    <select
                      id={`interval-${kind}`}
                      aria-label={`${name} interval`}
                      value={rule.interval_minutes}
                      disabled={busy !== null}
                      onChange={(event) => void changeInterval(rule, Number(event.target.value))}
                      className="input h-8 px-2 text-[10px]"
                    >
                      <option value={15}>Every 15 minutes</option>
                      <option value={60}>Every hour</option>
                      <option value={240}>Every 4 hours</option>
                      <option value={1440}>Daily</option>
                      <option value={10080}>Weekly</option>
                    </select>
                    <Button
                      disabled={busy !== null || !rule.enabled || !gmail?.connected}
                      onClick={() => void runWorkflow(rule)}
                    >
                      <Play size={12} /> Run now
                    </Button>
                  </div>
                )}
              </div>
              {rule?.last_run_at && (
                <p className="mt-2 text-[10px] text-muted">Last run: {dateLabel(rule.last_run_at)}</p>
              )}
            </Card>
          );
        })}
      </div>
      <Card className="mt-5 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Gemini automatic replies</h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-muted">Off by default. Draft mode creates editable Gmail drafts. Automatic sending is a separate opt-in and requires a second explicit confirmation. New messages are checked by the background worker at the configured interval.</p>
          </div>
          <span className={`rounded px-2 py-1 text-[10px] font-semibold uppercase ${autoReplySettings?.mode === "automatic_send" ? "bg-rose-500/10 text-rose-600" : autoReplySettings?.mode === "draft" ? "bg-amber-500/10 text-amber-700" : "bg-soft text-muted"}`}>{autoReplySettings?.mode.replace("_", " ") ?? "loading"}</span>
        </div>
        {autoReplySettings && <>
          {(!autoReplySettings.gmail_connected || !autoReplySettings.compose_enabled) && <p className="mt-3 rounded-lg bg-amber-500/10 p-3 text-[11px] text-amber-800">Connect Gmail and enable Gmail draft access in Settings to run this feature.</p>}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button disabled={busy !== null || !autoReplySettings.gmail_connected || !autoReplySettings.compose_enabled} onClick={() => void toggleAutoReplies()}>{autoReplySettings.enabled ? "Pause automatic replies" : "Enable draft mode"}</Button>
            <Button disabled={busy !== null || !autoReplySettings.enabled || !autoReplySettings.compose_enabled} onClick={() => void toggleAutomaticSending()}>{autoReplySettings.automatic_sending_enabled ? "Disable automatic sending" : "Enable automatic sending…"}</Button>
            <Button disabled={busy !== null || (!autoReplySettings.enabled && !autoReplySettings.automatic_sending_enabled)} onClick={() => void emergencyStopAutoReplies()}><Flame size={13} /> Emergency OFF</Button>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <label className="text-[10px] text-muted">Check interval<select className="input mt-1 h-9 w-full text-xs" value={autoReplySettings.interval_minutes} disabled={busy !== null} onChange={(event) => void updateReplySettings({ interval_minutes: Number(event.target.value) }, "Reply check interval updated.")}><option value={15}>Every 15 minutes</option><option value={30}>Every 30 minutes</option><option value={60}>Every hour</option><option value={240}>Every 4 hours</option><option value={1440}>Daily</option></select></label>
            <label className="text-[10px] text-muted">Maximum sent per day<input className="input mt-1 h-9 w-full text-xs" type="number" min={1} max={50} value={autoReplySettings.daily_limit} disabled={busy !== null} onChange={(event) => setAutoReplySettings({ ...autoReplySettings, daily_limit: Number(event.target.value) })} onBlur={() => void updateReplySettings({ daily_limit: Math.max(1, Math.min(50, autoReplySettings.daily_limit || 1)) }, "Daily sending limit updated.")} /></label>
            <label className="flex items-center gap-2 pt-5 text-[11px] text-subtle"><input type="checkbox" checked={autoReplySettings.reply_required_only} onChange={(event) => void updateReplySettings({ reply_required_only: event.target.checked }, "Reply-required filter updated.")} />Reply only when Gemini identifies a response is needed</label>
            <p className="flex items-center gap-2 text-[11px] text-subtle"><span aria-hidden="true">🔒</span>Sensitive text and messages with attachments are always excluded</p>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {([
              ["allowed_senders", "Only these senders (optional)", "person@example.com, @company.com"],
              ["blocked_senders", "Never reply to these senders", "noreply@example.com, @lists.example.com"],
              ["include_keywords", "Require one of these keywords (optional)", "meeting, availability"],
              ["exclude_keywords", "Never reply when these keywords appear", "unsubscribe, confidential"],
            ] as const).map(([key, label, placeholder]) => <label key={key} className="text-[10px] text-muted">{label}<input className="input mt-1 h-9 w-full text-xs" value={autoReplyRules[key]} placeholder={placeholder} onChange={(event) => setAutoReplyRules({ ...autoReplyRules, [key]: event.target.value })} /></label>)}
          </div>
          <Button className="mt-3" disabled={busy !== null} onClick={() => void saveAutoReplyRules()}>Save reply rules</Button>
          <div className="mt-5 border-t border-line pt-4">
            <h3 className="text-xs font-semibold">Reply activity · latest {autoReplyActivity.length}</h3>
            {autoReplyActivity.length === 0 ? <p className="mt-2 text-[10px] text-muted">No automatic reply activity yet.</p> : <div className="mt-2 space-y-2">{autoReplyActivity.map((activity) => <div key={activity.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line p-3"><div className="min-w-0"><p className="truncate text-[11px] font-medium">{activity.email_subject || "(no subject)"}</p><p className="truncate text-[10px] text-muted">{activity.email_sender} · {dateLabel(activity.created_at)}</p></div><span className="rounded bg-soft px-2 py-1 text-[9px] uppercase">{activity.status.replaceAll("_", " ")}{activity.reason_code ? ` · ${activity.reason_code.replaceAll("_", " ")}` : ""}</span></div>)}</div>}
          </div>
        </>}
      </Card>
      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <Card className="p-5">
          <div className="mb-3 flex items-center justify-between">
            <div><h2 className="text-sm font-semibold">Background jobs</h2><p className="mt-1 text-[10px] text-muted">Persistent queue status · latest 10</p></div>
            {loading && <Clock3 size={14} className="animate-pulse text-muted" />}
          </div>
          {jobs.length === 0 ? (
            <p className="text-xs text-muted">No background jobs have been queued.</p>
          ) : (
            <div className="space-y-2">
              {jobs.map((job) => (
                <div key={job.id} className="rounded-lg border border-line p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-medium">{job.job_type.replaceAll("_", " ")}</span>
                    <span className={`rounded px-2 py-1 text-[9px] uppercase ${job.status === "failed" ? "bg-rose-500/10 text-rose-600" : job.status === "succeeded" ? "bg-green-500/10 text-green-700" : "bg-soft text-muted"}`}>
                      {job.status}
                    </span>
                  </div>
                  <p className="mt-1 text-[10px] text-muted">
                    {dateLabel(job.created_at)} · attempt {job.attempts}/{job.max_attempts}
                    {job.last_error_code ? ` · ${job.last_error_code}` : ""}
                  </p>
                  {job.result_summary && <p className="mt-1 text-[10px] leading-4 text-subtle">{job.result_summary}</p>}
                  {job.status === "queued" && (
                    <button
                      disabled={busy === job.id}
                      onClick={() => void cancelJob(job)}
                      className="mt-2 inline-flex items-center gap-1 text-[10px] text-muted hover:text-rose-600"
                    >
                      <X size={12} /> Cancel queued job
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card className="p-5">
          <div className="mb-3 flex items-center justify-between">
            <div><h2 className="text-sm font-semibold">Notifications</h2><p className="mt-1 text-[10px] text-muted">{unreadCount} unread · latest 10</p></div>
            <BellRing size={14} className="text-accent" />
          </div>
          {notifications.length === 0 ? (
            <p className="text-xs text-muted">Job results and reminders will appear here.</p>
          ) : (
            <div className="space-y-2">
              {notifications.map((notification) => (
                <div key={notification.id} className={`rounded-lg border p-3 ${notification.read_at ? "border-line" : "border-accent/30 bg-accent/5"}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div><h3 className="text-xs font-medium">{notification.title}</h3><p className="mt-1 text-[10px] leading-4 text-subtle">{notification.message}</p><p className="mt-1 text-[9px] text-muted">{dateLabel(notification.created_at)}</p></div>
                    <button
                      disabled={busy === notification.id}
                      onClick={() => void markNotification(notification)}
                      aria-label={notification.read_at ? "Mark notification unread" : "Mark notification read"}
                      className="shrink-0 rounded p-1 text-muted hover:text-accent"
                    >
                      <Check size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
      <p className="mt-5 rounded-xl border border-dashed border-line p-4 text-[11px] leading-5 text-muted">
        Scheduled jobs and automatic reply cycles are processed by the separate database-backed worker. Reply automation is off until explicitly enabled. Sending remains separately disabled unless you confirm automatic sending. Sensitive exclusions, duplicate prevention, daily caps and activity records apply.
      </p>
    </div>
  );
}
