"use client";

import { use, useMemo, useState } from "react";
import { Ban, Play, RotateCw, Send, Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader, StatTile } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badge";
import { EmptyState, ErrorState, Notice, SkeletonRows } from "@/components/ui/states";
import { ConfirmDialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import {
  useDeliveryStatus,
  useReminderAction,
  useReminderRules,
  useReminders,
} from "@/lib/queries";
import { useActiveStore } from "@/lib/active-store";
import { formatDateTime, count } from "@/lib/format";
import { cn } from "@/lib/cn";
import { REMINDER_STATUSES } from "@/lib/types";

const FILTERS = ["all", ...REMINDER_STATUSES] as const;
type Filter = (typeof FILTERS)[number];

const LABELS: Record<Filter, string> = {
  all: "All",
  queued: "Queued",
  failed: "Failed",
  sent: "Sent",
  dismissed: "Dismissed",
};

export default function OutboxPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId: raw } = use(params);
  const storeId = Number(raw);
  const store = useActiveStore();
  const toast = useToast();

  const [kind, setKind] = useState("all");
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirmSend, setConfirmSend] = useState(false);

  const reminders = useReminders(storeId, kind);
  const rules = useReminderRules(storeId);
  const delivery = useDeliveryStatus(storeId);
  const actions = useReminderAction(storeId);

  const all = useMemo(() => reminders.data ?? [], [reminders.data]);

  // One fetch covers every status; the filter is applied here, over data
  // already in memory. That is deliberate: a message that just failed is never
  // a request away from view, whichever tab happens to be open.
  const counts = useMemo(() => {
    const tally: Record<string, number> = { all: all.length };
    for (const status of REMINDER_STATUSES) tally[status] = 0;
    for (const item of all) tally[item.status] = (tally[item.status] ?? 0) + 1;
    return tally;
  }, [all]);

  const visible = useMemo(
    () => (filter === "all" ? all : all.filter((item) => item.status === filter)),
    [all, filter],
  );

  const kinds = useMemo(
    () => [...new Set((rules.data ?? []).map((rule) => rule.kind))].sort(),
    [rules.data],
  );

  const live = delivery.data?.adapter !== "console";

  function toggle(id: number) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <>
      <PageHeader
        title="Outbox"
        subtitle={`Everything the reminder agent drafted for ${store.store_name}, and why.`}
        actions={
          <Button
            variant="secondary"
            busy={actions.runCheck.isPending}
            onClick={() =>
              actions.runCheck.mutate(undefined, {
                onSuccess: (result) =>
                  toast.success(
                    result.total > 0
                      ? `Queued ${count(result.total)} new message(s).`
                      : "Nothing new to draft right now.",
                  ),
                onError: (error) => toast.error(error.message),
              })
            }
          >
            <Play className="size-4" aria-hidden />
            Run reminder check
          </Button>
        }
      />

      {delivery.data ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile label="Channel" value={delivery.data.adapter} />
          <StatTile label="Sent today" value={count(delivery.data.sent_today)} />
          <StatTile label="Daily cap" value={count(delivery.data.daily_cap)} />
          <StatTile
            label="Left today"
            value={count(delivery.data.cap_remaining)}
            tone={delivery.data.cap_remaining === 0 ? "danger" : "neutral"}
          />
        </div>
      ) : null}

      <div className="mt-4">
        {live ? (
          <Notice tone="warning">
            <strong>{delivery.data?.adapter} is live.</strong> Messages you send reach real phones,
            up to {count(delivery.data?.cap_remaining ?? 0)} more today.
          </Notice>
        ) : (
          <Notice tone="info">
            The console adapter logs messages instead of sending them. Real delivery is opt-in per
            send, never on a schedule, and only for the rows you tick.
          </Notice>
        )}
      </div>

      <Card className="mt-4">
        <Card.Header>
          <div role="tablist" aria-label="Message status" className="flex flex-wrap gap-1">
            {FILTERS.map((option) => (
              <button
                key={option}
                type="button"
                role="tab"
                aria-selected={filter === option}
                onClick={() => setFilter(option)}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  filter === option
                    ? "bg-primary-soft text-primary"
                    : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                )}
              >
                {LABELS[option]}
                <span className="tnum rounded-full bg-surface-3 px-1.5 text-[11px] text-ink-2">
                  {count(counts[option] ?? 0)}
                </span>
              </button>
            ))}
          </div>

          <label className="flex items-center gap-1.5 text-xs text-ink-2">
            <span className="sr-only sm:not-sr-only">Kind</span>
            <select
              value={kind}
              onChange={(event) => setKind(event.currentTarget.value)}
              className="h-9 rounded-lg border border-line bg-surface px-2 text-sm text-ink hover:border-line-strong"
            >
              <option value="all">All kinds</option>
              {kinds.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        </Card.Header>

        {reminders.isPending ? (
          <SkeletonRows rows={6} columns={4} />
        ) : reminders.isError ? (
          <ErrorState detail={reminders.error.message} onRetry={() => void reminders.refetch()} />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={<Sparkles className="size-5" aria-hidden />}
            title="Nothing in this view"
            hint="Run the reminder check, or complete a sale on the POS page and come back."
          />
        ) : (
          <ul className="divide-y divide-line">
            {visible.map((item) => (
              <li key={item.id} className="px-4 py-3">
                <div className="flex flex-wrap items-start gap-3">
                  {item.status === "queued" ? (
                    <input
                      type="checkbox"
                      checked={selected.has(item.id)}
                      onChange={() => toggle(item.id)}
                      aria-label={`Select the message for ${item.customer_name}`}
                      className="mt-1 size-4 accent-[var(--primary)]"
                    />
                  ) : (
                    <span className="mt-1 size-4" aria-hidden />
                  )}

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-ink">{item.customer_name}</span>
                      <span className="tnum font-mono text-[11px] text-ink-3">{item.phone}</span>
                      <span className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-2">
                        {item.kind}
                      </span>
                      <StatusBadge status={item.status} />
                      <span className="text-[11px] text-ink-3">
                        {formatDateTime(item.scheduled_for ?? item.created_at)}
                      </span>
                    </div>

                    <p className="mt-1.5 text-sm text-ink-2">{item.message}</p>

                    {item.provider_response ? (
                      <p
                        className={cn(
                          "mt-1.5 text-xs",
                          item.status === "failed" ? "text-danger" : "text-ink-3",
                        )}
                      >
                        {item.status === "failed" ? "Reason: " : "Provider said: "}
                        {item.provider_response}
                      </p>
                    ) : null}
                  </div>

                  <div className="flex shrink-0 gap-1.5">
                    {item.status === "queued" ? (
                      <>
                        <Button
                          size="sm"
                          variant="secondary"
                          busy={actions.send.isPending && actions.send.variables === item.id}
                          onClick={() =>
                            actions.send.mutate(item.id, {
                              onSuccess: () => toast.success("Message sent."),
                              onError: (error) => toast.error(error.message),
                            })
                          }
                        >
                          <Send className="size-3.5" aria-hidden />
                          Send
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            actions.dismiss.mutate(item.id, {
                              onSuccess: () => toast.info("Message dismissed."),
                              onError: (error) => toast.error(error.message),
                            })
                          }
                        >
                          <Ban className="size-3.5" aria-hidden />
                          Dismiss
                        </Button>
                      </>
                    ) : item.status === "failed" ? (
                      <>
                        <Button
                          size="sm"
                          variant="primary"
                          busy={actions.retry.isPending && actions.retry.variables === item.id}
                          onClick={() =>
                            actions.retry.mutate(item.id, {
                              onSuccess: () =>
                                toast.success(
                                  "Requeued. It has not been sent — press Send when you are ready.",
                                ),
                              onError: (error) => toast.error(error.message),
                            })
                          }
                        >
                          <RotateCw className="size-3.5" aria-hidden />
                          Retry
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            actions.dismiss.mutate(item.id, {
                              onSuccess: () => toast.info("Message dismissed."),
                              onError: (error) => toast.error(error.message),
                            })
                          }
                        >
                          <Ban className="size-3.5" aria-hidden />
                          Dismiss
                        </Button>
                      </>
                    ) : null}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* The only path to a real send, and it is deliberately explicit. */}
      {selected.size > 0 ? (
        <div className="sticky bottom-4 mt-4">
          <Card>
            <Card.Body className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-ink">
                  {count(selected.size)} message{selected.size === 1 ? "" : "s"} selected
                </p>
                <p className="text-xs text-ink-3">
                  Nothing is sent until this button is pressed. The scheduler never sends; it only
                  drafts.
                </p>
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => setSelected(new Set())}>
                  Clear selection
                </Button>
                <Button variant="primary" onClick={() => setConfirmSend(true)}>
                  <Send className="size-4" aria-hidden />
                  Send {count(selected.size)} now
                </Button>
              </div>
            </Card.Body>
          </Card>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmSend}
        title={`Send ${count(selected.size)} message${selected.size === 1 ? "" : "s"}?`}
        description={
          live
            ? `These will reach real phones through ${delivery.data?.adapter}. Opted-out customers are refused at send time, and the daily cap still applies.`
            : "The console adapter will log these rather than deliver them. Nothing reaches a real phone."
        }
        confirmLabel="Send now"
        destructive={live}
        busy={actions.sendBatch.isPending}
        onCancel={() => setConfirmSend(false)}
        onConfirm={() =>
          actions.sendBatch.mutate([...selected].sort((a, b) => a - b), {
            onSuccess: (result) => {
              setConfirmSend(false);
              setSelected(new Set());
              toast.success(
                `Sent ${count(result.sent)}, failed ${count(result.failed)}, skipped ${count(result.skipped)}. ${count(result.cap_remaining)} left today.`,
              );
              for (const row of result.results.filter((entry) => entry.status === "failed")) {
                toast.error(`Reminder ${row.reminder_id}: ${row.detail ?? "failed"}`);
              }
            },
            onError: (error) => {
              setConfirmSend(false);
              toast.error(error.message);
            },
          })
        }
      />
    </>
  );
}
