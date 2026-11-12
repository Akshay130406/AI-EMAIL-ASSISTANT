import { useEffect, useState } from "react";
import {
  Activity,
  BarChart3,
  Clock3,
  Mail,
  Star,
  TrendingUp,
} from "lucide-react";
import { Card, DemoNotice, PageHeading } from "../components/ui";
import { getAnalyticsOverview } from "../services/api";
import type { AnalyticsOverview } from "../types/api";

function dayLabel(value: string, period: number): string {
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat(undefined, {
    month: period > 7 ? "short" : undefined,
    weekday: period <= 7 ? "short" : undefined,
    day: period > 7 ? "numeric" : undefined,
  }).format(date);
}

export default function AnalyticsPage() {
  const [period, setPeriod] = useState(7);
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    getAnalyticsOverview(period)
      .then((result) => {
        if (active) setAnalytics(result);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Analytics could not be loaded.",
          );
          setAnalytics(null);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [period]);

  const metrics = analytics
    ? [
        { icon: Mail, label: "Received in synchronized data", value: analytics.total_received },
        { icon: TrendingUp, label: "Sent in synchronized data", value: analytics.total_sent },
        { icon: Activity, label: "Unread", value: analytics.unread },
        { icon: Star, label: "Starred", value: analytics.starred },
      ]
    : [];
  const maximum = Math.max(
    1,
    ...(analytics?.daily.map((item) => item.received + item.sent) ?? []),
  );

  return (
    <div>
      <PageHeading
        eyebrow="Insights"
        title="Your email, in perspective."
        description="Review measured activity from the selected local dataset."
        action={
          analytics?.source === "gmail" ? (
            <DemoNotice>Connected Gmail · synchronized records</DemoNotice>
          ) : analytics?.source === "sample" ? (
            <DemoNotice>Sample dataset · not real account analytics</DemoNotice>
          ) : null
        }
      />
      {error && (
        <p role="alert" className="mb-5 rounded-xl border border-rose-500/20 bg-rose-500/5 px-4 py-3 text-xs text-rose-700 dark:text-rose-300">
          {error}
        </p>
      )}
      <div className="mb-5 flex items-center justify-between gap-3">
        <p className="text-xs text-muted">
          {loading
            ? "Loading measured activity…"
            : analytics?.source === "gmail"
              ? "Counts cover bounded messages synchronized to this account; activity outside the synchronized dataset is not included."
              : "These values describe only the clearly labeled fictional sample dataset."}
        </p>
        <label className="shrink-0 text-[10px] text-muted">
          Period
          <select
            aria-label="Analytics period"
            value={period}
            onChange={(event) => setPeriod(Number(event.target.value))}
            className="input ml-2 h-8 px-2 text-[10px]"
          >
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
        </label>
      </div>
      {loading && !analytics ? (
        <Card className="p-6 text-xs text-muted">Loading analytics…</Card>
      ) : analytics ? (
        <>
          <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {metrics.map(({ icon: Icon, label, value }) => (
              <Card key={label} className="p-4">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-muted">{label}</span>
                  <Icon size={15} className="text-faint" />
                </div>
                <div className="mt-4 text-2xl font-semibold">{value}</div>
              </Card>
            ))}
          </div>
          <Card className="p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold">Daily email activity</h2>
                <p className="mt-1 text-xs text-muted">
                  Received and sent records · last {analytics.period_days} days
                </p>
              </div>
              <span className="rounded-lg border border-line px-2 py-1 text-[10px] text-muted">
                {analytics.source === "gmail" ? "SYNCHRONIZED DATA" : "SAMPLE DATA"}
              </span>
            </div>
            {analytics.daily.every((item) => item.received + item.sent === 0) ? (
              <p className="mt-8 rounded-lg bg-soft p-5 text-center text-xs text-muted">
                No messages were recorded in this period.
              </p>
            ) : (
              <div className="mt-8 flex h-56 items-end gap-1 border-b border-line px-1 sm:gap-2">
                {analytics.daily.map((item) => {
                  const receivedHeight = (item.received / maximum) * 100;
                  const sentHeight = (item.sent / maximum) * 100;
                  return (
                    <div
                      key={item.day}
                      className="group relative flex h-full min-w-0 flex-1 items-end justify-center gap-0.5"
                      title={`${item.day}: ${item.received} received, ${item.sent} sent`}
                    >
                      <span
                        className="w-[38%] rounded-t-sm bg-accent/70"
                        style={{ height: `${receivedHeight}%` }}
                      />
                      <span
                        className="w-[38%] rounded-t-sm bg-violet-400/80"
                        style={{ height: `${sentHeight}%` }}
                      />
                      {(analytics.period_days === 7 ||
                        analytics.daily.indexOf(item) % 5 === 0) && (
                        <span className="absolute -bottom-5 whitespace-nowrap text-[8px] text-faint">
                          {dayLabel(item.day, analytics.period_days)}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            <div className="mt-8 flex gap-5 text-[10px] text-muted">
              <span><i className="mr-1.5 inline-block size-2 rounded-sm bg-accent/70" />Received</span>
              <span><i className="mr-1.5 inline-block size-2 rounded-sm bg-violet-400/80" />Sent</span>
            </div>
          </Card>
          <div className="mt-5 grid gap-5 xl:grid-cols-2">
            <Card className="p-5 sm:p-6">
              <div className="flex items-center gap-2">
                <BarChart3 size={15} className="text-accent" />
                <h2 className="text-sm font-semibold">Measured inbox status</h2>
              </div>
              <p className="mt-1 text-xs text-muted">Counts, not model-generated estimates</p>
              <div className="mt-5 space-y-4">
                {[
                  ["Unread", analytics.unread],
                  ["Starred", analytics.starred],
                  ["Priority", analytics.priority],
                ].map(([label, count]) => (
                  <div key={label}>
                    <div className="mb-1.5 flex justify-between text-[10px]">
                      <span className="text-subtle">{label}</span>
                      <span className="text-muted">{count}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-soft">
                      <div
                        className="h-1.5 rounded-full bg-accent/80"
                        style={{
                          width: `${analytics.total_received ? Math.min(100, (Number(count) / analytics.total_received) * 100) : 0}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </Card>
            <Card className="p-5 sm:p-6">
              <div className="flex items-center gap-2">
                <Clock3 size={15} className="text-accent" />
                <h2 className="text-sm font-semibold">Interpretation limits</h2>
              </div>
              <p className="mt-3 text-xs leading-5 text-muted">
                Response times, reply rates, productivity gains, and time saved are not estimated because the available synchronized records cannot measure them reliably.
              </p>
              <p className="mt-3 text-[10px] text-faint">
                Last calculated: {new Intl.DateTimeFormat(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                }).format(new Date(analytics.generated_at))}
              </p>
            </Card>
          </div>
        </>
      ) : !error ? (
        <Card className="p-6 text-xs text-muted">Analytics are unavailable.</Card>
      ) : null}
    </div>
  );
}
