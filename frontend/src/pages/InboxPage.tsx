import {
  Archive, ArrowLeft, ChevronDown, ChevronRight, Forward, Mail,
  MoreHorizontal, Paperclip, Reply, Search, Send, SlidersHorizontal, Star,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { demoEmails } from "../data/demoEmails";
import type { DemoEmail, MailFolder } from "../types/mail";
import { Button, DemoNotice, PageHeading } from "../components/ui";
import GmailInboxPage from "./GmailInboxPage";
import GmailDraftsPage from "./GmailDraftsPage";
import { getGmailStatus } from "../services/api";
import type { GmailStatus } from "../types/api";

type FolderView = MailFolder | "starred";
const tabs = ["All mail", "Primary", "Updates", "Promotions"] as const;
type MailTab = (typeof tabs)[number];

function loadLocalIdSet(key: string, initialIds: string[]): Set<string> {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
    if (Array.isArray(stored) && stored.every((id) => typeof id === "string")) {
      return new Set(stored);
    }
  } catch {
    return new Set(initialIds);
  }
  return new Set(initialIds);
}

const pageTitles: Record<FolderView, string> = {
  inbox: "Inbox",
  starred: "Starred",
  sent: "Sent",
  drafts: "Drafts",
};

function EmailDetail({
  email,
  onClose,
}: {
  email: DemoEmail;
  onClose: () => void;
}) {
  const [reply, setReply] = useState("");
  const [message, setMessage] = useState("");
  const [forwarding, setForwarding] = useState(false);
  const [showEarlierMessage, setShowEarlierMessage] = useState(false);

  function saveDraft() {
    if (!reply.trim()) {
      setMessage("Write a message before saving this demo draft.");
      return;
    }
    setMessage("Demo draft saved locally. Nothing was sent.");
  }

  return (
    <aside className="flex min-h-[560px] flex-col border-l border-line bg-panel xl:min-h-0">
      <div className="flex h-14 items-center justify-between border-b border-line px-5">
        <div className="flex items-center gap-1 text-[11px] text-muted"><span>Inbox</span><ChevronRight size={13} /><span className="max-w-40 truncate text-subtle">{email.subject}</span></div>
        <button onClick={onClose} className="icon-button xl:hidden" aria-label="Close email"><X size={16} /></button>
        <div className="hidden items-center gap-1 xl:flex"><button className="icon-button" aria-label="Archive unavailable in demo" title="Archive is unavailable in this demo" disabled><Archive size={15} /></button><button className="icon-button" aria-label="More email options unavailable in demo" title="More actions are unavailable in this demo" disabled><MoreHorizontal size={17} /></button></div>
      </div>
      <div className="flex-1 overflow-y-auto p-5 sm:p-6">
        <div className="mb-5 flex items-start justify-between gap-3">
          <div><h2 className="text-lg font-semibold leading-6 text-main">{email.subject}</h2><div className="mt-2 flex flex-wrap gap-2"><span className="rounded-md bg-soft px-2 py-1 text-[10px] text-subtle">{email.category}</span>{email.priority === "High" && <span className="rounded-md bg-rose-500/10 px-2 py-1 text-[10px] text-rose-600">Priority</span>}</div></div>
          <button className="icon-button"><MoreHorizontal size={17} /></button>
        </div>
        <button onClick={() => setShowEarlierMessage((visible) => !visible)} className="mb-3 flex items-center gap-2 text-[10px] text-muted hover:text-accent">
          <ChevronDown size={13} className={showEarlierMessage ? "rotate-180" : ""} />
          {showEarlierMessage ? "Hide earlier message" : "1 earlier message in this sample thread"}
        </button>
        {showEarlierMessage && <article className="mb-3 rounded-xl border border-line bg-canvas/60 p-4">
          <div className="flex items-center gap-3"><span className="avatar size-8 text-[9px]">ML</span><div><p className="text-xs font-medium">Morgan Lee <span className="ml-1 font-normal text-muted">&lt;morgan.lee@example.test&gt;</span></p><p className="mt-1 text-[10px] text-muted">Tuesday · to {email.to}</p></div></div>
          <p className="mt-3 text-xs leading-5 text-muted">Sharing an early note so you have the background before the latest update. This is sample conversation content for the interface demo.</p>
        </article>}
        <article className="rounded-xl border border-line bg-canvas p-4">
          <div className="flex items-start gap-3">
            <div className="avatar">{email.initials}</div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1"><span className="text-sm font-semibold text-main">{email.sender}</span><span className="truncate text-[11px] text-muted">&lt;{email.address}&gt;</span><span className="ml-auto text-[10px] text-muted">{email.time}</span></div>
              <p className="mt-1 text-[11px] text-muted">to {email.to}</p>
            </div>
          </div>
          <div className="email-body mt-5 whitespace-pre-line text-[13px] leading-7 text-subtle">{email.body}</div>
          <div className="mt-5 flex gap-2 border-t border-line pt-4"><Button onClick={() => { setForwarding(false); setMessage(""); document.getElementById("reply-composer")?.focus(); }}><Reply size={14} /> Reply</Button><Button onClick={() => { setForwarding(true); setMessage(""); document.getElementById("reply-composer")?.focus(); }}><Forward size={14} /> Forward</Button></div>
        </article>
        <div className="mt-4 rounded-xl border border-accent/20 bg-accent/5 p-4">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-accent"><span className="grid size-6 place-items-center rounded-lg bg-accent/10"><SparkleIcon /></span>Suggested reply <span className="ml-auto rounded bg-accent/10 px-2 py-1 text-[9px] uppercase tracking-wide">Demo suggestion</span></div>
          <p className="text-xs leading-5 text-subtle">Thanks for sending this over, {email.sender.split(" ")[0]}. Thursday afternoon works well for me — I’ll review the materials beforehand and come prepared with feedback.</p>
          <button onClick={() => { setForwarding(false); setReply(`Thanks for sending this over, ${email.sender.split(" ")[0]}. Thursday afternoon works well for me — I’ll review the materials beforehand and come prepared with feedback.`); setMessage(""); }} className="mt-2 text-[11px] font-medium text-accent hover:underline">Use this draft</button>
        </div>
        <div className="mt-4 rounded-xl border border-line bg-canvas p-4">
          <div className="mb-3 text-xs font-medium text-subtle">{forwarding ? "Forward this message" : "Reply to this message"}</div>
          {forwarding && <input className="input mb-3 h-9 w-full text-xs" placeholder="To: recipient@example.test" aria-label="Forward recipient" />}
          <textarea id="reply-composer" value={reply} onChange={(event) => setReply(event.target.value)} placeholder={forwarding ? "Add a note (optional)..." : "Write a reply..."} className="input min-h-24 w-full resize-y p-3 text-xs leading-5" />
          {message && <p role="status" className="mt-2 text-[11px] text-accent">{message}</p>}
          <div className="mt-3 flex items-center justify-between"><span className="text-[10px] text-muted">Local demo only · no email will be sent</span><Button variant="primary" onClick={saveDraft}><Send size={13} /> Save demo draft</Button></div>
        </div>
      </div>
    </aside>
  );
}

function SparkleIcon() {
  return <span aria-hidden="true">✦</span>;
}

function DemoInboxPage({ folder }: { folder: FolderView }) {
  const [searchParams] = useSearchParams();
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const [tab, setTab] = useState<MailTab>("All mail");
  const [filter, setFilter] = useState<"all" | "unread" | "priority">("all");
  const [filterOpen, setFilterOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [starred, setStarred] = useState(() => loadLocalIdSet("mailmind-demo-starred", demoEmails.filter((email) => email.starred).map((email) => email.id)));
  const [unread, setUnread] = useState(() => loadLocalIdSet("mailmind-demo-unread", demoEmails.filter((email) => email.unread).map((email) => email.id)));
  useEffect(() => {
    setSearch(searchParams.get("q") ?? "");
  }, [searchParams]);
  useEffect(() => {
    localStorage.setItem("mailmind-demo-starred", JSON.stringify([...starred]));
  }, [starred]);
  useEffect(() => {
    localStorage.setItem("mailmind-demo-unread", JSON.stringify([...unread]));
  }, [unread]);
  const emails = useMemo(() => demoEmails.filter((email) => {
    if (folder === "starred" && !starred.has(email.id)) return false;
    if (folder !== "starred" && email.folder !== folder) return false;
    if (folder === "inbox" && tab !== "All mail" && email.category !== tab) return false;
    if (filter === "unread" && !unread.has(email.id)) return false;
    if (filter === "priority" && email.priority !== "High") return false;
    const query = search.trim().toLowerCase();
    return !query || `${email.sender} ${email.subject} ${email.preview}`.toLowerCase().includes(query);
  }), [filter, folder, search, starred, tab, unread]);
  const selectedEmail = emails.find((email) => email.id === selectedId)
    ?? demoEmails.find((email) => email.id === selectedId && (folder === "starred" ? starred.has(email.id) : email.folder === folder))
    ?? null;

  return (
    <div>
      <PageHeading eyebrow="Mail workspace" title={pageTitles[folder]} description="A local product preview populated with clearly labeled sample messages." action={<DemoNotice />} />
      <div className={`overflow-hidden rounded-2xl border border-line bg-panel shadow-sm ${selectedEmail ? "grid xl:grid-cols-[minmax(380px,0.9fr)_minmax(460px,1.1fr)]" : ""}`}>
        <section className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
            <div className="relative min-w-[180px] flex-1"><Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search in mail" aria-label="Search this folder" className="input h-9 w-full pl-9 text-xs" /></div>
            <div className="relative"><Button aria-expanded={filterOpen} onClick={() => setFilterOpen((open) => !open)}><SlidersHorizontal size={14} /> Filter <ChevronDown size={12} /></Button>
              {filterOpen && <div className="absolute right-0 top-10 z-20 w-40 rounded-xl border border-line bg-panel p-1.5 shadow-lg">{([["all", "All messages"], ["unread", "Unread only"], ["priority", "Priority only"]] as const).map(([value, label]) => <button key={value} onClick={() => { setFilter(value); setFilterOpen(false); }} className={`block w-full rounded-lg px-2.5 py-2 text-left text-[11px] ${filter === value ? "bg-accent/10 font-medium text-accent" : "text-subtle hover:bg-soft"}`}>{label}</button>)}</div>}
            </div>
            <button title="More inbox options are unavailable in this demo" aria-label="More inbox options unavailable in demo" disabled className="icon-button"><MoreHorizontal size={16} /></button>
          </div>
          {folder === "inbox" && <div role="tablist" aria-label="Inbox categories" className="flex gap-5 border-b border-line px-5">
            {tabs.map((item) => <button key={item} role="tab" aria-selected={tab === item} onClick={() => setTab(item)} className={`relative py-3 text-xs transition ${tab === item ? "font-semibold text-accent" : "text-muted hover:text-main"}`}>{item}{tab === item && <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-accent" />}</button>)}
          </div>}
          <div className="divide-y divide-line">
            {emails.map((email) => (
              <article key={email.id} onClick={() => { setSelectedId(email.id); setUnread((old) => { const next = new Set(old); next.delete(email.id); return next; }); }} className={`group flex cursor-pointer gap-3 px-4 py-4 transition hover:bg-soft/70 ${selectedId === email.id ? "bg-accent/[0.06]" : ""} ${unread.has(email.id) ? "bg-soft/35" : ""}`}>
                <div className="relative mt-0.5 shrink-0"><span className="avatar size-9 text-[10px]">{email.initials}</span>{unread.has(email.id) && <span className="absolute -left-2 top-3 size-1.5 rounded-full bg-accent" />}</div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2"><span className={`truncate text-xs ${unread.has(email.id) ? "font-semibold text-main" : "font-medium text-subtle"}`}>{email.sender}</span><span className="ml-auto shrink-0 text-[10px] text-muted">{email.time}</span></div>
                  <div className="mt-1 flex items-center gap-2"><span className={`truncate text-xs ${unread.has(email.id) ? "font-semibold text-main" : "text-subtle"}`}>{email.subject}</span>{email.priority === "High" && <span title="High priority" className="size-1.5 shrink-0 rounded-full bg-rose-500" />}</div>
                  <p className="mt-1 truncate text-[11px] text-muted">{email.preview}</p>
                  <div className="mt-2 flex items-center gap-2"><span className="rounded bg-soft px-1.5 py-0.5 text-[9px] text-muted">{email.category}</span>{email.folder === "drafts" && <span className="text-[9px] text-amber-600">Draft</span>}</div>
                </div>
                <button aria-label={`${starred.has(email.id) ? "Unstar" : "Star"} ${email.subject}`} onClick={(event) => { event.stopPropagation(); setStarred((old) => { const next = new Set(old); if (next.has(email.id)) next.delete(email.id); else next.add(email.id); return next; }); }} className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg transition ${starred.has(email.id) ? "text-amber-500" : "text-faint opacity-0 group-hover:opacity-100 hover:text-amber-500"}`}><Star size={14} fill={starred.has(email.id) ? "currentColor" : "none"} /></button>
              </article>
            ))}
            {emails.length === 0 && <div className="px-6 py-16 text-center"><div className="mx-auto mb-3 grid size-10 place-items-center rounded-xl bg-soft text-muted"><Search size={17} /></div><p className="text-sm font-medium">No sample emails found</p><p className="mt-1 text-xs text-muted">Try another search or category.</p></div>}
          </div>
          <div className="flex items-center justify-between border-t border-line px-4 py-3 text-[10px] text-muted"><span>Showing {emails.length} sample messages</span><div className="flex items-center gap-2"><span>1–{emails.length} of {emails.length}</span><button aria-label="Previous page" disabled className="icon-button size-7 disabled:opacity-40"><ArrowLeft size={13} /></button><button aria-label="Next page" disabled className="icon-button size-7 disabled:opacity-40"><ChevronRight size={13} /></button></div></div>
        </section>
        {selectedEmail && <div className="fixed inset-x-0 bottom-0 top-[68px] z-30 overflow-y-auto bg-panel md:left-[252px] xl:static xl:z-auto xl:overflow-visible"><div className="sticky top-0 z-10 flex justify-end bg-panel p-2 xl:hidden"><button className="icon-button" aria-label="Close email details" onClick={() => setSelectedId(null)}><X size={18} /></button></div><EmailDetail email={selectedEmail} onClose={() => setSelectedId(null)} /></div>}
        {!selectedEmail && <aside className="hidden min-h-[500px] flex-col items-center justify-center border-l border-line bg-canvas/50 px-8 text-center xl:flex"><div className="mb-4 grid size-12 place-items-center rounded-2xl border border-line bg-panel text-muted"><Mail size={20} /></div><p className="text-sm font-medium">Select a message</p><p className="mt-1 max-w-xs text-xs leading-5 text-muted">Choose an email from the list to read the sample conversation and draft a reply.</p><span className="mt-4 text-[10px] text-faint"><Paperclip size={12} className="mr-1 inline" /> No real messages are loaded</span></aside>}
      </div>
    </div>
  );
}

export default function InboxPage({ folder }: { folder: FolderView }) {
  const [gmailStatus, setGmailStatus] = useState<GmailStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getGmailStatus()
      .then((result) => {
        if (active) {
          setGmailStatus(result);
          setStatusError(null);
        }
      })
      .catch(() => {
        if (active) setStatusError("Gmail connection status could not be verified. Reload the page to try again.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reloadKey]);

  if (loading) {
    return <p role="status" className="p-8 text-center text-xs text-muted">Checking Gmail connection…</p>;
  }
  if (statusError || !gmailStatus) {
    return <p role="alert" className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-4 text-xs text-rose-700">{statusError}</p>;
  }
  if (gmailStatus.status === "not_connected") {
    return <DemoInboxPage folder={folder} />;
  }
  if (folder === "drafts") {
    return <GmailDraftsPage connection={gmailStatus} />;
  }
  return (
    <GmailInboxPage
      folder={folder}
      connection={gmailStatus}
      onConnectionChange={() => setReloadKey((key) => key + 1)}
    />
  );
}
