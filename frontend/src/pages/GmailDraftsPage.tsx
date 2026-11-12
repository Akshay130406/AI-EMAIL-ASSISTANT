import { useEffect, useState } from "react";
import { FileText, Plus, RefreshCw, Send, Trash2 } from "lucide-react";
import { Button, PageHeading } from "../components/ui";
import {
  beginGmailComposeConnect,
  createGmailDraft,
  deleteGmailDraft,
  listGmailDrafts,
  sendGmailDraft,
  updateGmailDraft,
} from "../services/api";
import type { DraftRecord, GmailStatus, PageResponse } from "../types/api";

const PAGE_SIZE = 20;

function splitAddresses(value: string): string[] {
  return value.split(",").map((address) => address.trim()).filter(Boolean);
}

type DraftContent = {
  recipients: string[];
  cc: string[];
  bcc: string[];
  subject: string;
  body: string;
};

type SendConfirmation = {
  draft: DraftRecord;
  content: DraftContent;
};

export default function GmailDraftsPage({
  connection,
}: {
  connection: GmailStatus;
}) {
  const [data, setData] = useState<PageResponse<DraftRecord> | null>(null);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<DraftRecord | null>(null);
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [bcc, setBcc] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [sendConfirmation, setSendConfirmation] = useState<SendConfirmation | null>(null);

  useEffect(() => {
    if (!connection.compose_enabled) return;
    let active = true;
    setLoading(true);
    setError(null);
    listGmailDrafts({ page, page_size: PAGE_SIZE })
      .then((result) => {
        if (active) setData(result);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Gmail drafts could not be loaded.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [connection.compose_enabled, page, reloadKey]);

  function startNewDraft() {
    setSelected(null);
    setTo("");
    setCc("");
    setBcc("");
    setSubject("");
    setBody("");
    setError(null);
    setNotice(null);
  }

  function selectDraft(draft: DraftRecord) {
    setSelected(draft);
    setTo(draft.recipients.join(", "));
    setCc(draft.cc.join(", "));
    setBcc(draft.bcc.join(", "));
    setSubject(draft.subject);
    setBody(draft.body);
    setError(null);
    setNotice(null);
  }

  async function saveDraft() {
    const recipients = splitAddresses(to);
    if (recipients.length === 0) {
      setError("Add at least one recipient before saving.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    const payload = {
      recipients,
      cc: splitAddresses(cc),
      bcc: splitAddresses(bcc),
      subject,
      body,
    };
    try {
      const saved = selected
        ? await updateGmailDraft(selected.id, payload)
        : await createGmailDraft(payload);
      setSelected(saved);
      setNotice("Draft saved to Gmail.");
      setReloadKey((key) => key + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Gmail could not confirm the draft update.");
    } finally {
      setBusy(false);
    }
  }

  async function removeDraft(draft: DraftRecord) {
    if (!window.confirm("Delete this draft from your Gmail account? This cannot be undone.")) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await deleteGmailDraft(draft.id);
      if (selected?.id === draft.id) startNewDraft();
      setNotice("Draft deleted from Gmail.");
      setReloadKey((key) => key + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Gmail draft could not be deleted.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmSend(confirmation: SendConfirmation) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await updateGmailDraft(confirmation.draft.id, confirmation.content);
      const result = await sendGmailDraft(confirmation.draft.id);
      setSendConfirmation(null);
      if (selected?.id === confirmation.draft.id) startNewDraft();
      if (result.status === "sent") {
        setNotice("Gmail confirmed that the message was sent.");
      } else {
        setNotice(`Gmail send status: ${result.status}.`);
      }
      setReloadKey((key) => key + 1);
    } catch (reason) {
      setSendConfirmation(null);
      setSelected(null);
      setTo("");
      setCc("");
      setBcc("");
      setSubject("");
      setBody("");
      setError(reason instanceof Error ? reason.message : "Gmail could not confirm whether the message was sent.");
      setReloadKey((key) => key + 1);
    } finally {
      setBusy(false);
    }
  }

  function reviewBeforeSending(draft: DraftRecord) {
    const recipients = splitAddresses(to);
    if (recipients.length === 0) {
      setError("Add at least one recipient before sending.");
      return;
    }
    setError(null);
    setSendConfirmation({
      draft,
      content: {
        recipients,
        cc: splitAddresses(cc),
        bcc: splitAddresses(bcc),
        subject,
        body,
      },
    });
  }

  async function connectCompose() {
    setBusy(true);
    setError(null);
    try {
      await beginGmailComposeConnect();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Gmail compose permission could not be enabled.");
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeading
        eyebrow="Gmail"
        title="Drafts"
        description="Manage drafts saved in your connected Gmail account. Sending always requires a separate confirmation."
        action={
          connection.compose_enabled ? (
            <Button onClick={startNewDraft}><Plus size={14} /> New draft</Button>
          ) : null
        }
      />
      {connection.requires_reconnect && (
        <p role="alert" className="mb-4 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-700">
          Gmail authorization must be restored in Settings before drafts can be accessed.
        </p>
      )}
      {!connection.compose_enabled && !connection.requires_reconnect && (
        <div className="rounded-2xl border border-line bg-panel p-8 text-center">
          <FileText size={22} className="mx-auto text-muted" />
          <p className="mt-3 text-sm font-medium">Enable Gmail draft access</p>
          <p className="mx-auto mt-1 max-w-md text-xs leading-5 text-muted">
            Draft management and sending use a separate Google permission. Your existing read-only inbox permission does not change until you approve it.
          </p>
          <Button className="mt-4" onClick={connectCompose} disabled={busy}>
            {busy ? "Opening Google…" : "Enable draft access"}
          </Button>
        </div>
      )}
      {connection.compose_enabled && (
        <div className="grid gap-4 xl:grid-cols-[minmax(260px,0.8fr)_minmax(420px,1.2fr)]">
          <section className="overflow-hidden rounded-2xl border border-line bg-panel">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <span className="text-xs font-semibold">Gmail drafts</span>
              <Button onClick={() => setReloadKey((key) => key + 1)} disabled={loading || busy} aria-label="Refresh drafts">
                <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Refresh
              </Button>
            </div>
            {loading ? (
              <p role="status" className="p-8 text-center text-xs text-muted">Loading Gmail drafts…</p>
            ) : data?.items.length ? (
              <div className="divide-y divide-line">
                {data.items.map((draft) => (
                  <button
                    key={draft.id}
                    onClick={() => selectDraft(draft)}
                    className={`block w-full px-4 py-3 text-left hover:bg-soft ${selected?.id === draft.id ? "bg-accent/[0.06]" : ""}`}
                  >
                    <span className="block truncate text-xs font-medium">{draft.subject || "(no subject)"}</span>
                    <span className="mt-1 block truncate text-[10px] text-muted">{draft.recipients.join(", ") || "No recipient"}</span>
                    <span className="mt-1 block truncate text-[10px] text-faint">{draft.send_status === "unknown" ? "Send result unknown — do not retry" : draft.body.slice(0, 100)}</span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="p-8 text-center text-xs text-muted">No Gmail drafts found.</p>
            )}
            {data && data.total > PAGE_SIZE && (
              <div className="flex items-center justify-between border-t border-line px-4 py-3 text-[10px] text-muted">
                <span>Page {page} of {Math.ceil(data.total / PAGE_SIZE)}</span>
                <span className="flex gap-1">
                  <Button disabled={page === 1 || loading} onClick={() => setPage((value) => value - 1)}>Previous</Button>
                  <Button disabled={page >= Math.ceil(data.total / PAGE_SIZE) || loading} onClick={() => setPage((value) => value + 1)}>Next</Button>
                </span>
              </div>
            )}
          </section>
          <section className="rounded-2xl border border-line bg-panel p-4 sm:p-5">
            <h2 className="mb-4 text-sm font-semibold">{selected ? "Edit Gmail draft" : "New Gmail draft"}</h2>
            <div className="space-y-3">
              <label className="block text-[10px] font-medium text-muted">To<input value={to} onChange={(event) => setTo(event.target.value)} className="input mt-1 h-9 w-full px-3 text-xs" placeholder="name@example.com, ..." /></label>
              <label className="block text-[10px] font-medium text-muted">Cc<input value={cc} onChange={(event) => setCc(event.target.value)} className="input mt-1 h-9 w-full px-3 text-xs" /></label>
              <label className="block text-[10px] font-medium text-muted">Bcc<input value={bcc} onChange={(event) => setBcc(event.target.value)} className="input mt-1 h-9 w-full px-3 text-xs" /></label>
              <label className="block text-[10px] font-medium text-muted">Subject<input value={subject} onChange={(event) => setSubject(event.target.value)} className="input mt-1 h-9 w-full px-3 text-xs" /></label>
              <label className="block text-[10px] font-medium text-muted">Message<textarea value={body} onChange={(event) => setBody(event.target.value)} className="input mt-1 min-h-48 w-full resize-y p-3 text-xs leading-5" /></label>
            </div>
            {selected && <p className="mt-3 text-[10px] text-muted">Send status: {selected.send_status}</p>}
            {error && <p role="alert" className="mt-3 text-xs text-rose-600">{error}</p>}
            {notice && <p role="status" className="mt-3 text-xs text-green-700">{notice}</p>}
            <div className="mt-4 flex flex-wrap gap-2">
              <Button onClick={() => void saveDraft()} disabled={busy || !connection.compose_enabled || (selected !== null && !["not_sent", "failed"].includes(selected.send_status))}>Save draft</Button>
              {selected && ["not_sent", "failed"].includes(selected.send_status) && <Button variant="primary" onClick={() => reviewBeforeSending(selected)} disabled={busy}><Send size={13} /> Send…</Button>}
              {selected && ["not_sent", "failed"].includes(selected.send_status) && <Button onClick={() => void removeDraft(selected)} disabled={busy}><Trash2 size={13} /> Delete</Button>}
            </div>
          </section>
        </div>
      )}
      {sendConfirmation && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="gmail-send-confirmation-title"
            className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-line bg-panel p-5 shadow-xl"
          >
            <h2 id="gmail-send-confirmation-title" className="text-base font-semibold">Review before sending</h2>
            <p className="mt-1 text-xs text-muted">Gmail will deliver this message to the recipients below.</p>
            <dl className="mt-4 space-y-3 text-xs">
              <div><dt className="font-semibold text-muted">To</dt><dd className="mt-1 break-words">{sendConfirmation.content.recipients.join(", ") || "None"}</dd></div>
              {sendConfirmation.content.cc.length > 0 && <div><dt className="font-semibold text-muted">Cc</dt><dd className="mt-1 break-words">{sendConfirmation.content.cc.join(", ")}</dd></div>}
              {sendConfirmation.content.bcc.length > 0 && <div><dt className="font-semibold text-muted">Bcc</dt><dd className="mt-1 break-words">{sendConfirmation.content.bcc.join(", ")}</dd></div>}
              <div><dt className="font-semibold text-muted">Subject</dt><dd className="mt-1 break-words">{sendConfirmation.content.subject || "(no subject)"}</dd></div>
              <div><dt className="font-semibold text-muted">Message</dt><dd className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-soft p-3">{sendConfirmation.content.body || "(empty message)"}</dd></div>
            </dl>
            <div className="mt-5 flex justify-end gap-2">
              <Button disabled={busy} onClick={() => setSendConfirmation(null)}>Cancel</Button>
              <Button
                variant="primary"
                disabled={busy}
                onClick={() => void confirmSend(sendConfirmation)}
              >
                <Send size={13} /> {busy ? "Sending…" : "Confirm and send"}
              </Button>
            </div>
          </section>
        </div>
      )}
      {error && !connection.compose_enabled && <p role="alert" className="mt-4 text-xs text-rose-600">{error}</p>}
    </div>
  );
}
