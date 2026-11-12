import { useBackendHealth } from "../hooks/useBackendHealth";

export default function BackendStatus() {
  const health = useBackendHealth();

  if (health.status === "checking") {
    return (
      <span className="inline-flex items-center gap-2 text-sm text-slate-400">
        <span className="size-2 animate-pulse rounded-full bg-amber-400" />
        Checking backend
      </span>
    );
  }

  if (health.status === "offline") {
    return (
      <span
        className="inline-flex items-center gap-2 text-sm text-rose-300"
        title={health.message}
      >
        <span className="size-2 rounded-full bg-rose-400" />
        Backend unavailable
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-2 text-sm text-emerald-300">
      <span className="size-2 rounded-full bg-emerald-400" />
      Backend connected
    </span>
  );
}
