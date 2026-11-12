import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Bell, CalendarDays, Check, ChevronRight, CircleHelp, Eye, EyeOff, KeyRound, Languages,
  Link2, Mail, Moon, ShieldCheck, Sparkles, Sun, UserRound,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Button, Card, DemoNotice, PageHeading } from "../components/ui";
import { useTheme } from "../contexts/ThemeContext";
import {
  beginGmailComposeConnect,
  beginGmailConnect,
  beginCalendarConnect,
  disconnectCalendar,
  disconnectGmail,
  getCalendarStatus,
  getGmailStatus,
  syncGmail,
} from "../services/api";
import type { CalendarStatus, GmailStatus } from "../types/api";

function PreferenceRow({
  icon: Icon,
  title,
  description,
  control,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  control: ReactNode;
}) {
  return <div className="flex flex-wrap items-center gap-3 border-b border-line py-4 last:border-0"><span className="grid size-8 shrink-0 place-items-center rounded-lg bg-soft text-muted"><Icon size={15} /></span><span className="min-w-[180px] flex-1"><span className="block text-xs font-medium">{title}</span><span className="mt-1 block text-[10px] leading-4 text-muted">{description}</span></span>{control}</div>;
}

function Toggle({ label, initial = true }: { label: string; initial?: boolean }) {
  const [checked, setChecked] = useState(initial);
  return <button role="switch" aria-checked={checked} aria-label={label} onClick={() => setChecked((value) => !value)} className={`relative h-5 w-9 shrink-0 rounded-full transition ${checked ? "bg-accent" : "bg-slate-300 dark:bg-slate-700"}`}><span className={`absolute top-0.5 size-4 rounded-full bg-white shadow transition-all ${checked ? "left-[18px]" : "left-0.5"}`} /></button>;
}

const integrations: { label: string; icon: LucideIcon }[] = [
  { label: "Google / Gmail", icon: Mail },
  { label: "Google Calendar", icon: CalendarDays },
  { label: "Gemini", icon: Sparkles },
];

export default function SettingsPage() {
  const { theme, toggleTheme } = useTheme();
  const [saved, setSaved] = useState(false);
  const [searchParams] = useSearchParams();
  const [gmail, setGmail] = useState<GmailStatus | null>(null);
  const [gmailLoading, setGmailLoading] = useState(true);
  const [gmailBusy, setGmailBusy] = useState(false);
  const [gmailError, setGmailError] = useState<string | null>(null);
  const [gmailNotice, setGmailNotice] = useState<string | null>(null);
  const [oauthMessage, setOauthMessage] = useState<string | null>(null);
  const [calendar, setCalendar] = useState<CalendarStatus | null>(null);
  const [calendarLoading, setCalendarLoading] = useState(true);
  const [calendarBusy, setCalendarBusy] = useState(false);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [calendarNotice, setCalendarNotice] = useState<string | null>(null);
  const [calendarOauthMessage, setCalendarOauthMessage] = useState<string | null>(null);

  async function refreshGmailStatus() {
    setGmailLoading(true);
    try {
      setGmail(await getGmailStatus());
      setGmailError(null);
    } catch (reason) {
      setGmailError(reason instanceof Error ? reason.message : "Gmail status could not be loaded.");
    } finally {
      setGmailLoading(false);
    }
  }

  async function refreshCalendarStatus() {
    setCalendarLoading(true);
    try {
      setCalendar(await getCalendarStatus());
      setCalendarError(null);
    } catch (reason) {
      setCalendarError(
        reason instanceof Error
          ? reason.message
          : "Calendar status could not be loaded.",
      );
    } finally {
      setCalendarLoading(false);
    }
  }

  useEffect(() => {
    void refreshGmailStatus();
    void refreshCalendarStatus();
    const error = searchParams.get("gmail_error");
    if (searchParams.get("gmail") === "connected") {
      setOauthMessage("Gmail connected. Synchronize to load your read-only inbox.");
    } else if (searchParams.get("gmail") === "compose_connected") {
      setOauthMessage("Gmail draft access enabled. Messages are sent only after explicit confirmation.");
    } else if (error) {
      const messages: Record<string, string> = {
        not_configured: "Gmail integration is not configured on the backend.",
        cancelled: "Gmail connection was cancelled.",
        provider_error: "Google could not authorize Gmail access.",
        authorization_failed: "Gmail authorization failed. Check the selected account and granted permissions.",
      };
      setOauthMessage(messages[error] ?? "Gmail authorization failed.");
    } else {
      setOauthMessage(null);
    }
    if (searchParams.get("calendar") === "connected") {
      setCalendarOauthMessage("Google Calendar connected.");
    } else {
      const error = searchParams.get("calendar_error");
      const messages: Record<string, string> = {
        not_configured: "Calendar integration is not configured on the backend.",
        cancelled: "Calendar connection was cancelled.",
        provider_error: "Google could not authorize Calendar access.",
        authorization_failed:
          "Calendar authorization failed. Check the selected account and granted permissions.",
      };
      setCalendarOauthMessage(error ? messages[error] ?? "Calendar authorization failed." : null);
    }
  }, [searchParams]);

  async function handleGmailSync() {
    setGmailBusy(true);
    setGmailError(null);
    setGmailNotice(null);
    try {
      const result = await syncGmail();
      setGmailNotice(`${result.synced} Gmail message${result.synced === 1 ? "" : "s"} synchronized.`);
      await refreshGmailStatus();
    } catch (reason) {
      setGmailError(reason instanceof Error ? reason.message : "Gmail synchronization failed.");
      await refreshGmailStatus();
    } finally {
      setGmailBusy(false);
    }
  }

  async function handleGmailConnect() {
    setGmailBusy(true);
    setGmailError(null);
    try {
      await beginGmailConnect();
    } catch (reason) {
      setGmailError(reason instanceof Error ? reason.message : "Gmail authorization could not be started.");
      setGmailBusy(false);
    }
  }

  async function handleGmailDisconnect() {
    setGmailBusy(true);
    setGmailError(null);
    try {
      await disconnectGmail();
      setGmailNotice("Gmail disconnected. Cached messages remain available and separate from sample data.");
      await refreshGmailStatus();
    } catch (reason) {
      setGmailError(reason instanceof Error ? reason.message : "Gmail could not be disconnected.");
    } finally {
      setGmailBusy(false);
    }
  }

  async function handleGmailComposeConnect() {
    setGmailBusy(true);
    setGmailError(null);
    try {
      await beginGmailComposeConnect();
    } catch (reason) {
      setGmailError(reason instanceof Error ? reason.message : "Gmail draft access could not be enabled.");
      setGmailBusy(false);
    }
  }

  async function handleCalendarConnect() {
    setCalendarBusy(true);
    setCalendarError(null);
    try {
      await beginCalendarConnect();
    } catch (reason) {
      setCalendarError(
        reason instanceof Error
          ? reason.message
          : "Calendar authorization could not be started.",
      );
      setCalendarBusy(false);
    }
  }

  async function handleCalendarDisconnect() {
    if (
      !window.confirm(
        "Disconnect Google Calendar? Existing events will remain in Google Calendar.",
      )
    ) {
      return;
    }
    setCalendarBusy(true);
    setCalendarError(null);
    try {
      await disconnectCalendar();
      setCalendarNotice("Google Calendar disconnected.");
      await refreshCalendarStatus();
    } catch (reason) {
      setCalendarError(
        reason instanceof Error
          ? reason.message
          : "Calendar could not be disconnected.",
      );
    } finally {
      setCalendarBusy(false);
    }
  }

  return (
    <div>
      <PageHeading eyebrow="Preferences" title="Make Mailmind yours." description="Manage workspace preferences and connected accounts." action={<DemoNotice>Gmail inbox access remains read-only</DemoNotice>} />
      {saved && <p role="status" className="mb-4 rounded-xl border border-green-500/20 bg-green-500/5 px-4 py-3 text-xs text-green-700 dark:text-green-400">Settings preview updated. Nothing was sent or saved to an account.</p>}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(280px,0.7fr)]">
        <div className="space-y-5">
          <Card className="p-5 sm:p-6"><div className="mb-1 flex items-center gap-2"><UserRound size={16} className="text-accent" /><h2 className="text-sm font-semibold">Profile preferences</h2></div><p className="text-[11px] text-muted">Example profile details are local display values.</p><div className="mt-5 grid gap-4 sm:grid-cols-2"><label className="text-[10px] font-medium text-muted">Display name<input defaultValue="Jordan Davis" className="input mt-1.5 h-10 w-full px-3 text-xs" /></label><label className="text-[10px] font-medium text-muted">Email address<input value="jordan@example.test" readOnly className="input mt-1.5 h-10 w-full px-3 text-xs" /></label><label className="text-[10px] font-medium text-muted">Language<select defaultValue="English" className="input mt-1.5 h-10 w-full px-3 text-xs"><option>English</option><option>Español</option><option>Français</option></select></label><label className="text-[10px] font-medium text-muted">Time zone<select defaultValue="Pacific Time" className="input mt-1.5 h-10 w-full px-3 text-xs"><option>Pacific Time</option><option>Eastern Time</option><option>UTC</option></select></label></div></Card>
          <Card className="p-5 sm:p-6"><div className="mb-2 flex items-center gap-2"><Bell size={16} className="text-accent" /><h2 className="text-sm font-semibold">Notifications</h2></div><PreferenceRow icon={Mail} title="Inbox reminders" description="Show a local reminder for messages awaiting a reply." control={<Toggle label="Inbox reminders" />} /><PreferenceRow icon={Sparkles} title="Writing suggestions" description="Display local writing tips in the demo workspace." control={<Toggle label="Writing suggestions" />} /><PreferenceRow icon={Bell} title="Product updates" description="Receive notices about new workspace capabilities." control={<Toggle label="Product updates" initial={false} />} /></Card>
          <Card className="p-5 sm:p-6"><div className="mb-2 flex items-center gap-2"><Sparkles size={16} className="text-accent" /><h2 className="text-sm font-semibold">AI preferences</h2></div><PreferenceRow icon={Languages} title="Default writing tone" description="Used by local sample draft actions." control={<select className="input h-8 px-2 text-[10px]"><option>Professional</option><option>Friendly</option><option>Formal</option><option>Concise</option></select>} /><PreferenceRow icon={Eye} title="Always review drafts" description="Messages are never sent from this demo." control={<span className="rounded-md bg-green-500/10 px-2 py-1 text-[9px] text-green-700 dark:text-green-400">ALWAYS ON</span>} /><PreferenceRow icon={KeyRound} title="AI provider" description="No provider configured or contacted." control={<span className="rounded-md bg-soft px-2 py-1 text-[9px] text-muted">Not connected</span>} /></Card>
          <Button variant="primary" onClick={() => { setSaved(true); window.setTimeout(() => setSaved(false), 2500); }}><Check size={14} /> Preview settings</Button>
        </div>
        <div className="space-y-5">
          <Card className="p-5"><div className="flex items-center gap-2"><Sun size={15} className="text-accent" /><h2 className="text-sm font-semibold">Appearance</h2></div><p className="mt-1 text-[11px] text-muted">Choose your preferred workspace theme.</p><div className="mt-4 grid grid-cols-2 gap-2"><button onClick={() => theme === "dark" && toggleTheme()} className={`rounded-xl border p-3 text-left ${theme === "light" ? "border-accent bg-accent/5" : "border-line"}`}><Sun size={15} /><span className="mt-2 block text-xs font-medium">Light</span></button><button onClick={() => theme === "light" && toggleTheme()} className={`rounded-xl border p-3 text-left ${theme === "dark" ? "border-accent bg-accent/5" : "border-line"}`}><Moon size={15} /><span className="mt-2 block text-xs font-medium">Dark</span></button></div></Card>
          <Card className="p-5"><div className="flex items-center gap-2"><Link2 size={15} className="text-accent" /><h2 className="text-sm font-semibold">Connected accounts</h2></div><p className="mt-1 text-[11px] text-muted">Gmail permissions are separate from sign-in. Calendar event changes require confirmation and may notify attendees.</p><div className="mt-4 space-y-3">{integrations.map(({ label, icon: Icon }) => <div key={label} className="flex flex-wrap items-center gap-3 rounded-xl border border-line p-3"><span className="grid size-8 place-items-center rounded-lg bg-soft text-muted"><Icon size={15} /></span><span className="flex-1 text-xs font-medium">{label}</span>{label === "Google / Gmail" ? <><span className="rounded bg-soft px-2 py-1 text-[9px] text-muted">{gmailLoading ? "Checking…" : gmail?.connected ? `Connected${gmail.email ? ` · ${gmail.email}` : ""}` : gmail?.requires_reconnect ? "Reconnect required" : gmailError ? "Status unavailable" : "Not connected"}</span><Button disabled={gmailLoading || gmailBusy} onClick={gmail?.connected ? handleGmailSync : handleGmailConnect}>{gmailBusy ? "Working…" : gmail?.connected ? "Sync" : gmail?.requires_reconnect ? "Reconnect" : "Connect Gmail"}</Button>{gmail?.connected && !gmail.compose_enabled && <Button disabled={gmailBusy} onClick={handleGmailComposeConnect}>Enable drafts & sending</Button>}{gmail?.connected && gmail.compose_enabled && <span className="rounded bg-amber-500/10 px-2 py-1 text-[9px] text-amber-700">Drafts & sending enabled</span>}{gmail?.connected && <Button disabled={gmailBusy} onClick={handleGmailDisconnect}>Disconnect</Button>}</> : label === "Google Calendar" ? <><span className="rounded bg-soft px-2 py-1 text-[9px] text-muted">{calendarLoading ? "Checking…" : calendar?.connected ? `Connected${calendar.email ? ` · ${calendar.email}` : ""}` : calendar?.requires_reconnect ? "Reconnect required" : calendarError ? "Status unavailable" : "Not connected"}</span><Button disabled={calendarLoading || calendarBusy} onClick={handleCalendarConnect}>{calendarBusy ? "Working…" : calendar?.requires_reconnect ? "Reconnect" : "Connect Calendar"}</Button>{calendar?.connected && <Button disabled={calendarBusy} onClick={handleCalendarDisconnect}>Disconnect</Button>}</> : <span className="rounded bg-soft px-2 py-1 text-[9px] text-muted">Backend configured</span>}</div>)}</div>{gmailError && <p role="alert" className="mt-3 text-xs text-rose-600">{gmailError}</p>}{oauthMessage && <p role={searchParams.get("gmail_error") ? "alert" : "status"} className="mt-3 text-xs text-accent">{oauthMessage}</p>}{gmailNotice && <p role="status" className="mt-3 text-xs text-green-700 dark:text-green-400">{gmailNotice}</p>}{calendarError && <p role="alert" className="mt-3 text-xs text-rose-600">{calendarError}</p>}{calendarOauthMessage && <p role={searchParams.get("calendar_error") ? "alert" : "status"} className="mt-3 text-xs text-accent">{calendarOauthMessage}</p>}{calendarNotice && <p role="status" className="mt-3 text-xs text-green-700 dark:text-green-400">{calendarNotice}</p>}<div className="mt-4 flex items-start gap-2 rounded-lg bg-soft p-3 text-[10px] leading-4 text-muted"><ShieldCheck size={14} className="mt-0.5 shrink-0" />Google integration tokens remain encrypted server-side and are never returned to the browser. Calendar availability checks cover only your connected calendar, not invitee schedules.</div></Card>
          <Card className="p-5"><div className="flex items-center gap-2"><CircleHelp size={15} className="text-accent" /><h2 className="text-sm font-semibold">Help & privacy</h2></div><button className="menu-item mt-3 w-full"><EyeOff size={14} /> Privacy overview <ChevronRight size={13} className="ml-auto" /></button><button className="menu-item w-full"><CircleHelp size={14} /> Help center <ChevronRight size={13} className="ml-auto" /></button><Button className="mt-3 w-full justify-center" disabled>Manage subscription</Button></Card>
        </div>
      </div>
    </div>
  );
}
