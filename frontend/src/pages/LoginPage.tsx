import { useState } from "react";
import { ArrowRight, LockKeyhole, Mail, ShieldCheck } from "lucide-react";
import { Navigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { beginGoogleSignIn } from "../services/api";

const authErrors: Record<string, string> = {
  cancelled: "Google sign-in was cancelled. You can try again whenever you're ready.",
  provider_error: "Google couldn't complete sign-in. Please try again.",
  sign_in_failed: "We couldn't verify your Google account. Please try again.",
  not_configured: "Google sign-in isn't configured yet. Contact the administrator.",
};

export default function LoginPage() {
  const { status, error: sessionError } = useAuth();
  const [searchParams] = useSearchParams();
  const [starting, setStarting] = useState(false);
  const authError = authErrors[searchParams.get("auth_error") ?? ""];

  if (status === "authenticated") return <Navigate to="/" replace />;
  if (status === "loading") {
    return (
      <main className="grid min-h-screen place-items-center bg-canvas text-subtle" aria-live="polite">
        <p className="text-sm">Checking your sign-in…</p>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-5 py-12 text-main">
      <section className="w-full max-w-[410px]">
        <div className="mb-8 flex items-center justify-center gap-3">
          <span className="grid size-11 place-items-center rounded-2xl bg-accent text-white shadow-sm">
            <Mail size={21} />
          </span>
          <span className="text-xl font-semibold tracking-tight">mailmind</span>
        </div>
        <div className="surface-card p-7 sm:p-9">
          <div className="mb-7 text-center">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-accent">A calmer inbox starts here</p>
            <h1 className="text-2xl font-semibold tracking-tight">Welcome to Mailmind</h1>
            <p className="mt-2 text-sm leading-6 text-muted">Sign in securely with your Google account to continue.</p>
          </div>

          {(authError || sessionError) && (
            <div role="alert" className="mb-5 rounded-xl border border-red-500/20 bg-red-500/5 px-3.5 py-3 text-xs leading-5 text-red-700 dark:text-red-300">
              {authError || sessionError}
            </div>
          )}

          <button
            type="button"
            disabled={starting}
            onClick={() => {
              setStarting(true);
              beginGoogleSignIn();
            }}
            className="flex min-h-11 w-full items-center justify-center gap-2.5 rounded-xl bg-accent px-4 text-sm font-medium text-white transition hover:bg-accent-hover disabled:opacity-60"
          >
            <GoogleMark />
            {starting ? "Connecting to Google…" : "Continue with Google"}
            {!starting && <ArrowRight size={15} className="ml-auto" />}
          </button>

          <div className="mt-6 space-y-3 border-t border-line pt-5">
            <p className="flex items-start gap-2.5 text-[11px] leading-5 text-muted">
              <ShieldCheck size={15} className="mt-0.5 shrink-0 text-green-600" />
              Your sign-in is handled by Google. Mailmind never receives your Google password.
            </p>
            <p className="flex items-start gap-2.5 text-[11px] leading-5 text-muted">
              <LockKeyhole size={15} className="mt-0.5 shrink-0 text-muted" />
              This sign-in requests identity only—no Gmail or Calendar access.
            </p>
          </div>
        </div>
        <p className="mt-5 text-center text-[10px] leading-5 text-faint">
          By continuing, you agree to use this application in accordance with its privacy and security policies.
        </p>
      </section>
    </main>
  );
}

function GoogleMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[17px] rounded-full bg-white p-0.5">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1Z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.65l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.15v2.84A11 11 0 0 0 12 23Z" />
      <path fill="#FBBC05" d="M5.84 14.11a6.6 6.6 0 0 1 0-4.22V7.05H2.15a11 11 0 0 0 0 9.9l3.69-2.84Z" />
      <path fill="#EA4335" d="M12 4.36c1.62 0 3.07.56 4.21 1.64l3.15-3.15C17.45 1.09 14.97 0 12 0a11 11 0 0 0-9.85 7.05l3.69 2.84C6.71 7.29 9.14 4.36 12 4.36Z" />
    </svg>
  );
}
