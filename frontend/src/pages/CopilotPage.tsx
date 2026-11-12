import { ArrowUp, Bot, ChevronRight, LoaderCircle, Paperclip, Plus, Sparkles, User } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, DemoNotice, PageHeading } from "../components/ui";
import { askEmailCopilot } from "../services/api";
import type { AICopilotResult } from "../types/api";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  sources?: AICopilotResult["sources"];
}

const prompts = [
  "Summarize my important unread emails",
  "Which emails require my attention?",
  "Which conversations contain unanswered questions?",
  "Find upcoming deadlines mentioned in my emails",
  "What should I prioritize today?",
];

export default function CopilotPage() {
  const [searchParams] = useSearchParams();
  const selectedEmailId = searchParams.get("email_id") || undefined;
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function send(text = input) {
    const question = text.trim();
    if (!question || loading) {
      if (!question) setError("Enter a question or choose a suggested prompt.");
      return;
    }
    setError("");
    setInput("");
    setMessages((current) => [...current, { role: "user", text: question }]);
    setLoading(true);
    try {
      const result = await askEmailCopilot({ question, email_id: selectedEmailId });
      setMessages((current) => [
        ...current,
        { role: "assistant", text: result.answer, sources: result.sources },
      ]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Email Copilot could not complete the request.");
    } finally {
      setLoading(false);
    }
  }

  function clearConversation() {
    setMessages([]);
    setError("");
    setInput("");
  }

  return (
    <div className="flex min-h-[calc(100vh-150px)] flex-col">
      <PageHeading eyebrow="Email copilot" title="A thoughtful second opinion." description="Ask questions grounded in your synchronized Gmail messages." action={<DemoNotice>Gemini · Gmail context when connected</DemoNotice>} />
      <section className="flex min-h-[500px] flex-1 flex-col overflow-hidden rounded-2xl border border-line bg-panel">
        <div className="flex items-center justify-between border-b border-line px-5 py-3"><div className="flex items-center gap-2"><span className="grid size-8 place-items-center rounded-lg bg-accent/10 text-accent"><Bot size={17} /></span><div><p className="text-xs font-semibold">Mailmind Copilot</p><p className="text-[10px] text-muted">Gemini · grounded in your Gmail data</p></div></div><Button onClick={clearConversation}><Plus size={13} /> New chat</Button></div>
        <div className="flex flex-1 flex-col overflow-y-auto p-4 sm:p-7">
          {messages.length === 0 ? (
            <div className="m-auto max-w-lg py-10 text-center">
              <div className="mx-auto mb-4 grid size-12 place-items-center rounded-2xl bg-accent/10 text-accent"><Sparkles size={22} /></div>
              <h2 className="text-lg font-semibold">What needs your attention?</h2>
              <p className="mt-2 text-xs leading-5 text-muted">Answers use only relevant, synchronized Gmail messages. Connect Gmail and sync your inbox first. Email content is sent to Gemini when you ask a question.</p>
              <div className="mt-6 grid gap-2 sm:grid-cols-2">{prompts.map((prompt) => <button key={prompt} onClick={() => void send(prompt)} disabled={loading} className="rounded-xl border border-line p-3 text-left text-[11px] leading-5 text-subtle transition hover:border-accent/30 hover:bg-accent/5 disabled:opacity-50">{prompt}<ChevronRight size={13} className="mt-2 text-accent" /></button>)}</div>
            </div>
          ) : (
            <div className="mx-auto w-full max-w-2xl space-y-5">
              {messages.map((message, index) => <div key={`${message.role}-${index}`} className={`flex gap-3 ${message.role === "user" ? "flex-row-reverse" : ""}`}>
                <span className={`grid size-8 shrink-0 place-items-center rounded-full ${message.role === "user" ? "bg-soft text-subtle" : "bg-accent/10 text-accent"}`}>{message.role === "user" ? <User size={15} /> : <Bot size={15} />}</span>
                <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-xs leading-6 ${message.role === "user" ? "bg-accent text-white" : "border border-line bg-canvas text-subtle"}`}>
                  <p className="whitespace-pre-wrap">{message.text}</p>
                  {message.role === "assistant" && <><p className="mt-2 border-t border-line pt-2 text-[9px] text-muted">AI-generated answer · verify important details against the source email.</p>{message.sources?.length ? <div className="mt-2 space-y-1" aria-label="Source emails">{message.sources.map((source) => <p key={source.email_id} className="truncate text-[10px] text-accent">Source: {source.subject || "(no subject)"} · {source.sender}</p>)}</div> : null}</>}
                </div>
              </div>)}
              {loading && <p role="status" className="flex items-center gap-2 text-xs text-muted"><LoaderCircle size={14} className="animate-spin" />Checking relevant email context with Gemini…</p>}
            </div>
          )}
        </div>
        <div className="border-t border-line p-4 sm:px-7 sm:py-5"><div className="mx-auto max-w-2xl"><form onSubmit={(event) => { event.preventDefault(); void send(); }} className="flex items-end gap-2 rounded-2xl border border-line bg-canvas p-2 focus-within:border-accent/40"><button type="button" className="icon-button mb-0.5" aria-label="Attachments are unavailable" title="Attachments are not available"><Paperclip size={16} /></button><textarea value={input} onChange={(event) => { setInput(event.target.value); setError(""); }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="Ask about your synchronized Gmail messages…" rows={1} className="max-h-28 min-h-9 flex-1 resize-y bg-transparent py-2 text-xs text-subtle outline-none placeholder:text-faint" aria-label="Copilot message" /><Button variant="primary" type="submit" className="size-9 justify-center !px-0" aria-label="Send message" disabled={loading}>{loading ? <LoaderCircle size={16} className="animate-spin" /> : <ArrowUp size={16} />}</Button></form>{error && <p role="alert" className="mt-2 text-[11px] text-rose-600">{error}</p>}<p className="mt-2 text-center text-[10px] text-faint">Copilot does not send, modify, or take actions on email.</p></div></div>
      </section>
    </div>
  );
}
