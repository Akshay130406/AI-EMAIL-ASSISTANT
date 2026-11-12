import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Mail,
  RefreshCw,
  Search,
  Sparkles,
  Star,
} from "lucide-react";
import { Button, PageHeading } from "../components/ui";
import {
  beginGmailComposeConnect,
  classifyEmail,
  createGmailDraft,
  getEmailThread,
  listEmails,
  summarizeEmail,
  summarizeEmailThread,
  suggestEmailReply,
  syncGmail,
} from "../services/api";
import type { AIClassification, AIEmailSummary, EmailRecord, GmailStatus, PageResponse } from "../types/api";
import { APIError } from "../services/api";
import type { MailFolder } from "../types/mail";

type FolderView = MailFolder | "starred";

function formatDate(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

function initials(sender: string): string {
  const name = sender.split("<")[0].trim();
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0] ?? "")
    .join("")
    .toUpperCase() || "?";
}

export default function GmailInboxPage({
  folder,
  connection,
  onConnectionChange,
}: {
  folder: FolderView;
  connection: GmailStatus;
  onConnectionChange: () => void;
}) {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [data, setData] = useState<PageResponse<EmailRecord> | null>(null);
  const [selected, setSelected] = useState<EmailRecord | null>(null);
  const [thread, setThread] = useState<EmailRecord[]>([]);
  const [threadError, setThreadError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [classification, setClassification] = useState<AIClassification | null>(null);
  const [classifications, setClassifications] = useState<Record<string, AIClassification>>({});
  const [summary, setSummary] = useState<AIEmailSummary | null>(null);
  const [replySuggestion, setReplySuggestion] = useState("");
  const [replySubject, setReplySubject] = useState("");
  const [replyDraftBusy, setReplyDraftBusy] = useState(false);
  const [replyDraftError, setReplyDraftError] = useState<string | null>(null);
  const [replyDraftSaved, setReplyDraftSaved] = useState(false);
  const [aiBusy, setAiBusy] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    listEmails({
      page,
      page_size: 20,
      search: search.trim() || undefined,
      unread: unreadOnly || undefined,
      sent: folder === "sent" || undefined,
      starred: folder === "starred" || undefined,
    })
      .then((result) => {
        if (active) setData(result);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Inbox could not be loaded.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [folder, page, reloadKey, search, unreadOnly]);

  useEffect(() => {
    if (!selected) {
      setThread([]);
      setThreadError(null);
      setClassification(null);
      setSummary(null);
      setReplySuggestion("");
      setReplySubject("");
      setReplyDraftError(null);
      setReplyDraftSaved(false);
      setAiError(null);
      return;
    }
    setClassification(null);
    setSummary(null);
    setReplySuggestion("");
    setReplySubject("");
    setReplyDraftError(null);
    setReplyDraftSaved(false);
    setAiError(null);
    let active = true;
    setThread([]);
    setThreadError(null);
    getEmailThread(selected.id)
      .then((result) => {
        if (active) setThread(result.messages);
      })
      .catch((reason: unknown) => {
        if (active) setThreadError(reason instanceof Error ? reason.message : "Thread could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, [selected]);

  async function runAI(action: "classify" | "summarize" | "reply") {
    if (!selected || aiBusy) return;
    setAiBusy(action);
    setAiError(null);
    try {
      if (action === "classify") {
        const result = await classifyEmail(selected.id);
        setClassification(result);
        setClassifications((current) => ({ ...current, [selected.id]: result }));
      } else if (action === "summarize") {
        setSummary(selected.thread_id
          ? await summarizeEmailThread(selected.thread_id)
          : await summarizeEmail(selected.id));
      } else {
        const suggestion = await suggestEmailReply(selected.id);
        setReplySubject(suggestion.subject);
        setReplySuggestion(suggestion.body);
      }
    } catch (reason) {
      setAiError(reason instanceof Error ? reason.message : "Gemini could not complete this request.");
    } finally {
      setAiBusy(null);
    }
  }

  async function saveSuggestedReply() {
    if (!selected || !replySuggestion.trim() || replyDraftBusy) return;
    if (!connection.compose_enabled) {
      if (connection.requires_reconnect) {
        setReplyDraftError("Reconnect Gmail in Settings before saving a draft.");
        return;
      }
      setReplyDraftBusy(true);
      setReplyDraftError(null);
      try {
        await beginGmailComposeConnect();
      } catch (reason) {
        setReplyDraftError(reason instanceof Error ? reason.message : "Gmail draft permission could not be enabled.");
        setReplyDraftBusy(false);
      }
      return;
    }

    const emailAddress =
      selected.sender.match(/<([^<>]+)>/)?.[1] ?? selected.sender.trim();
    if (!/^[^@\s,<>]+@[^@\s,<>]+\.[^@\s,<>]+$/.test(emailAddress)) {
      setReplyDraftError("The sender address could not be verified. Create the draft manually.");
      return;
    }

    setReplyDraftBusy(true);
    setReplyDraftError(null);
    setReplyDraftSaved(false);
    try {
      const subject = replySubject.trim()
        || (selected.subject.toLowerCase().startsWith("re:")
          ? selected.subject
          : `Re: ${selected.subject}`);
      await createGmailDraft({
        recipients: [emailAddress],
        cc: [],
        bcc: [],
        subject,
        body: replySuggestion,
      });
      setReplyDraftSaved(true);
    } catch (reason) {
      setReplyDraftError(reason instanceof Error ? reason.message : "Gmail could not confirm the draft save.");
    } finally {
      setReplyDraftBusy(false);
    }
  }

  async function handleSync() {
    setSyncing(true);
    setNotice(null);
    setError(null);
    try {
      const result = await syncGmail();
      setNotice(`${result.synced} message${result.synced === 1 ? "" : "s"} synchronized.`);
      setReloadKey((key) => key + 1);
      onConnectionChange();
    } catch (reason) {
      setError(reason instanceof APIError ? reason.message : "Gmail synchronization failed.");
      onConnectionChange();
    } finally {
      setSyncing(false);
    }
  }

  const title = folder === "starred" ? "Starred" : folder === "inbox" ? "Inbox" : folder === "sent" ? "Sent" : "Drafts";
  const supportedFolder =
    folder === "inbox" || folder === "starred" || folder === "sent";

  return (
    <div>
      <PageHeading
        eyebrow="Gmail"
        title={title}
        description={`Read-only messages from ${connection.email ?? "your connected Gmail account"}. Gmail content is displayed as plain text.`}
        action={
          <Button onClick={handleSync} disabled={syncing || !connection.connected}>
            <RefreshCw size={14} className={syncing ? "animate-spin" : ""} />
            {syncing ? "Syncing…" : "Sync inbox"}
          </Button>
        }
      />
      {connection.requires_reconnect && (
        <p role="status" className="mb-4 rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-xs text-amber-700 dark:text-amber-400">
          Gmail authorization needs to be restored. Cached Gmail messages remain separate from sample data.
        </p>
      )}
      {notice && <p role="status" className="mb-4 text-xs text-green-700 dark:text-green-400">{notice}</p>}
      {error && <p role="alert" className="mb-4 rounded-xl border border-rose-500/20 bg-rose-500/5 px-4 py-3 text-xs text-rose-700 dark:text-rose-400">{error}</p>}
      {!supportedFolder ? (
        <div className="rounded-2xl border border-line bg-panel p-10 text-center text-sm text-muted">
          This Gmail view is not available yet. No sample messages are shown while Gmail data is connected.
        </div>
      ) : (
        <div className={`overflow-hidden rounded-2xl border border-line bg-panel shadow-sm ${selected ? "grid xl:grid-cols-[minmax(380px,0.9fr)_minmax(460px,1.1fr)]" : ""}`}>
          <section className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
              <div className="relative min-w-[180px] flex-1">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
                <input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Search in Gmail" aria-label="Search Gmail" className="input h-9 w-full pl-9 text-xs" />
              </div>
              <label className="flex items-center gap-2 text-xs text-muted">
                <input type="checkbox" checked={unreadOnly} onChange={(event) => { setUnreadOnly(event.target.checked); setPage(1); }} />
                Unread
              </label>
            </div>
            {loading ? (
              <p role="status" className="p-8 text-center text-xs text-muted">Loading Gmail messages…</p>
            ) : data?.items.length ? (
              <div className="divide-y divide-line">
                {data.items.map((email) => (
                  <button key={email.id} onClick={() => setSelected(email)} className={`flex w-full gap-3 px-4 py-4 text-left transition hover:bg-soft/70 ${selected?.id === email.id ? "bg-accent/[0.06]" : ""} ${!email.is_read ? "bg-soft/35" : ""}`}>
                    <span className="avatar size-9 shrink-0 text-[10px]">{initials(email.sender)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2"><span className={`truncate text-xs ${!email.is_read ? "font-semibold text-main" : "font-medium text-subtle"}`}>{email.sender}</span><span className="ml-auto shrink-0 text-[10px] text-muted">{formatDate(email.received_at)}</span></span>
                      <span className="mt-1 flex items-center gap-2"><span className={`truncate text-xs ${!email.is_read ? "font-semibold text-main" : "text-subtle"}`}>{email.subject || "(no subject)"}</span>{email.is_priority && <span title="Important" className="size-1.5 shrink-0 rounded-full bg-rose-500" />}</span>
                      {classifications[email.id] && <span className="mt-1 inline-flex rounded bg-accent/10 px-1.5 py-0.5 text-[9px] text-accent">AI: {classifications[email.id].category} · {classifications[email.id].priority}</span>}
                      <span className="mt-1 block truncate text-[11px] text-muted">{email.preview}</span>
                    </span>
                    <Star size={14} aria-label={email.is_starred ? "Starred" : "Not starred"} className={`mt-1 shrink-0 ${email.is_starred ? "fill-amber-500 text-amber-500" : "text-faint"}`} />
                  </button>
                ))}
              </div>
            ) : (
              <div className="px-6 py-16 text-center">
                <div className="mx-auto mb-3 grid size-10 place-items-center rounded-xl bg-soft text-muted"><Mail size={17} /></div>
                <p className="text-sm font-medium">No Gmail messages found</p>
                <p className="mt-1 text-xs text-muted">Try another search or synchronize your inbox.</p>
              </div>
            )}
            <div className="flex items-center justify-between border-t border-line px-4 py-3 text-[10px] text-muted">
              <span>{data ? `${data.total} Gmail messages` : "Gmail messages"}</span>
              <div className="flex items-center gap-2">
                <span>Page {page}</span>
                <button aria-label="Previous page" disabled={page <= 1 || loading} onClick={() => setPage((value) => value - 1)} className="icon-button size-7 disabled:opacity-40"><ArrowLeft size={13} /></button>
                <button aria-label="Next page" disabled={!data || page * data.page_size >= data.total || loading} onClick={() => setPage((value) => value + 1)} className="icon-button size-7 disabled:opacity-40"><ChevronRight size={13} /></button>
              </div>
            </div>
          </section>
          {selected && (
            <aside className="border-l border-line bg-panel p-5 sm:p-6">
              <div className="mb-5 flex items-center justify-between">
                <button onClick={() => setSelected(null)} className="icon-button xl:hidden" aria-label="Back to inbox"><ChevronLeft size={16} /></button>
                <span className="text-[10px] text-muted">Read-only Gmail message</span>
              </div>
              <h2 className="text-lg font-semibold leading-6 text-main">{selected.subject || "(no subject)"}</h2>
              <p className="mt-3 text-xs font-medium text-subtle">{selected.sender}</p>
              <p className="mt-1 text-[10px] text-muted">To {selected.recipients.join(", ") || "you"} · {formatDate(selected.received_at)}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button onClick={() => void runAI("classify")} disabled={aiBusy !== null}><Sparkles size={13} />{aiBusy === "classify" ? "Classifying…" : "Classify"}</Button>
                <Button onClick={() => void runAI("summarize")} disabled={aiBusy !== null}><Sparkles size={13} />{aiBusy === "summarize" ? "Summarizing…" : selected.thread_id ? "Summarize thread" : "Summarize"}</Button>
                <Button onClick={() => void runAI("reply")} disabled={aiBusy !== null}><Sparkles size={13} />{aiBusy === "reply" ? "Drafting…" : "Suggest reply"}</Button>
                <Button onClick={() => navigate(`/copilot?email_id=${encodeURIComponent(selected.id)}`)}>Ask Copilot</Button>
              </div>
              {aiError && <p role="alert" className="mt-3 text-xs text-rose-600">{aiError}</p>}
              {classification && <section className="mt-4 rounded-xl border border-accent/20 bg-accent/5 p-4" aria-label="AI classification">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-accent">Gemini classification · {Math.round(classification.confidence * 100)}% confidence</p>
                <div className="mt-2 flex flex-wrap gap-2"><span className="rounded bg-soft px-2 py-1 text-[10px]">{classification.category}</span><span className="rounded bg-soft px-2 py-1 text-[10px]">Priority: {classification.priority}</span><span className="rounded bg-soft px-2 py-1 text-[10px]">Urgency: {classification.urgency}</span><span className="rounded bg-soft px-2 py-1 text-[10px]">Reply likely: {classification.response_required === null ? "Unclear" : classification.response_required ? "Yes" : "No"}</span></div>
                <p className="mt-2 text-[11px] leading-5 text-subtle">{classification.explanation}</p>
                {classification.deadlines.map((deadline) => <p key={`${deadline.date_text}-${deadline.evidence}`} className="mt-2 text-[10px] text-muted">Mentioned date: {deadline.date_text} · “{deadline.evidence}”</p>)}
              </section>}
              {summary && <section className="mt-4 rounded-xl border border-accent/20 bg-accent/5 p-4" aria-label="AI summary">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-accent">Gemini summary · verify against original</p>
                <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-subtle">{summary.summary}</p>
                {summary.important_points.length > 0 && <div className="mt-3"><p className="text-[10px] font-semibold text-subtle">Important points</p>{summary.important_points.map((item, index) => <p key={index} className="mt-1 text-[10px] text-muted">{item.text} · “{item.evidence}”</p>)}</div>}
                {summary.action_items.length > 0 && <div className="mt-3"><p className="text-[10px] font-semibold text-subtle">Action items</p>{summary.action_items.map((item, index) => <p key={index} className="mt-1 text-[10px] text-muted">{item.text} · “{item.evidence}”</p>)}</div>}
                {summary.questions_requiring_response.length > 0 && <div className="mt-3"><p className="text-[10px] font-semibold text-subtle">Questions that may need a response</p>{summary.questions_requiring_response.map((item, index) => <p key={index} className="mt-1 text-[10px] text-muted">{item.text} · “{item.evidence}”</p>)}</div>}
                {summary.deadlines.map((deadline) => <p key={`${deadline.date_text}-${deadline.evidence}`} className="mt-2 text-[10px] text-muted">Mentioned date: {deadline.date_text} · “{deadline.evidence}”</p>)}
                {summary.people_or_organizations.length > 0 && <p className="mt-3 text-[10px] text-muted">People or organizations mentioned: {summary.people_or_organizations.map((item) => item.text).join(", ")}</p>}
              </section>}
              {replySuggestion && <section className="mt-4 rounded-xl border border-accent/20 bg-accent/5 p-4">
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-accent">Gemini reply suggestion · not sent</p>
                <textarea aria-label="Editable suggested reply" value={replySuggestion} onChange={(event) => setReplySuggestion(event.target.value)} className="min-h-28 w-full resize-y bg-transparent text-xs leading-5 text-subtle outline-none" />
                <label className="mt-3 block text-[10px] font-medium text-muted">Subject<input aria-label="Suggested reply subject" value={replySubject} onChange={(event) => setReplySubject(event.target.value)} className="input mt-1 h-8 w-full px-2 text-xs" /></label>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Button onClick={() => void saveSuggestedReply()} disabled={replyDraftBusy || !replySuggestion.trim()}>
                    {replyDraftBusy ? "Saving…" : connection.compose_enabled ? "Save to Gmail Drafts" : "Enable draft access"}
                  </Button>
                  {replyDraftSaved && <Button onClick={() => navigate("/drafts")}>Open Drafts</Button>}
                </div>
                {replyDraftError && <p role="alert" className="mt-2 text-[10px] text-rose-600">{replyDraftError}</p>}
                {replyDraftSaved && <p role="status" className="mt-2 text-[10px] text-green-700">Reply saved as a Gmail draft. Nothing was sent.</p>}
              </section>}
              {threadError && <p role="alert" className="mt-4 text-xs text-rose-600">{threadError}</p>}
              <div className="mt-5 space-y-4">
                {(thread.length ? thread : [selected]).map((message) => (
                  <article key={message.id} className="rounded-xl border border-line bg-canvas p-4">
                    <p className="mb-3 text-[10px] font-medium text-muted">{message.sender} · {formatDate(message.received_at)}</p>
                    <div className="whitespace-pre-wrap break-words text-[13px] leading-7 text-subtle">{message.body || message.preview || "(No text body)"}</div>
                  </article>
                ))}
              </div>
              {thread.length > 1 && <p className="mt-4 text-[10px] text-muted">{thread.length} messages in this thread</p>}
            </aside>
          )}
        </div>
      )}
    </div>
  );
}
