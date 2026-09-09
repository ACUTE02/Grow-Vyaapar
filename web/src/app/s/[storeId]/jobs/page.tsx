"use client";

import { use, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { ClipboardList, Plus } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader, StatTile } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { SelectField, TextField } from "@/components/ui/field";
import { EmptyState, ErrorState, Notice, Skeleton } from "@/components/ui/states";
import { Table, TBody, TD, THead, TH, TR, TRowHeader } from "@/components/ui/table";
import { Modal } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { JobCard, statusLabel } from "@/components/jobs/job-card";
import { useCustomers, useJobActions, useJobs, useJobsBoard } from "@/lib/queries";
import { useActiveStore } from "@/lib/active-store";
import { count, formatDate } from "@/lib/format";
import { JOB_COLUMNS } from "@/lib/types";

type BookingFields = { customer_id: string; type: string; promised_date: string };

/**
 * The jobs board: a column per status, cards that advance through the status
 * graph the API supplies, and a booking form.
 *
 * Marking a job ready fires the same pickup_ready rule the nightly run uses -
 * the response says how many reminders that queued, and the toast repeats it,
 * because a message drafted on the user's behalf should never be silent.
 */
export default function JobsPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId: raw } = use(params);
  const storeId = Number(raw);
  const store = useActiveStore();
  const toast = useToast();

  const [booking, setBooking] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const board = useJobsBoard(storeId);
  const takesJobs = board.data?.takes_jobs ?? false;
  const jobs = useJobs(storeId, takesJobs);
  const actions = useJobActions(storeId);

  const all = useMemo(() => jobs.data ?? [], [jobs.data]);
  const overdue = useMemo(() => all.filter((job) => job.is_overdue), [all]);
  const cancelled = useMemo(() => all.filter((job) => job.status === "cancelled"), [all]);

  function advance(id: number, status: string) {
    actions.setStatus.mutate(
      { id, status },
      {
        onSuccess: (result) => {
          const queued = result.reminders_queued;
          toast.success(
            `Marked ${statusLabel(status).toLowerCase()}` +
              (queued
                ? ` — ${count(queued)} pickup reminder${queued === 1 ? "" : "s"} queued in the Outbox, not sent.`
                : "."),
          );
        },
        onError: (error) => toast.error(error.message),
      },
    );
  }

  if (board.isPending) {
    return (
      <>
        <PageHeader title="Jobs" />
        <Skeleton className="h-64 w-full" />
      </>
    );
  }

  if (board.isError) {
    return (
      <>
        <PageHeader title="Jobs" />
        <Card>
          <ErrorState detail={board.error.message} onRetry={() => void board.refetch()} />
        </Card>
      </>
    );
  }

  // The flag is off for this vertical. Say so, rather than hiding the page and
  // letting the URL 404 - the API already explains why.
  if (!takesJobs) {
    return (
      <>
        <PageHeader title="Jobs" />
        <Card>
          <EmptyState
            icon={<ClipboardList className="size-5" aria-hidden />}
            title="This store does not take jobs"
            hint={`The jobs flag is off for ${store.vertical_name}, so nothing here applies. An optician or a tailor would have it on.`}
          />
        </Card>
      </>
    );
  }

  const jobTypes = board.data?.job_types ?? [];

  return (
    <>
      <PageHeader
        title="Jobs"
        subtitle={
          jobTypes.length > 0
            ? `${store.vertical_name} takes: ${jobTypes.join(", ")}. These come from its config, not from code.`
            : `${store.vertical_name} takes jobs but lists no types in its config.`
        }
        actions={
          <Button variant="primary" onClick={() => setBooking(true)}>
            <Plus className="size-4" aria-hidden />
            Take a new job
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {JOB_COLUMNS.map((column) => (
          <StatTile
            key={column}
            label={statusLabel(column)}
            value={count(board.data?.counts?.[column] ?? 0)}
            tone={column === "ready" ? "primary" : "neutral"}
          />
        ))}
      </div>

      {overdue.length > 0 ? (
        <div className="mt-4">
          <Notice tone="danger">
            <strong>
              {count(overdue.length)} job{overdue.length === 1 ? " is" : "s are"} past the promised
              date.
            </strong>{" "}
            They are marked in red on the board below.
          </Notice>
        </div>
      ) : null}

      {jobs.isPending ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          {JOB_COLUMNS.map((column) => (
            <Skeleton key={column} className="h-56 w-full" />
          ))}
        </div>
      ) : jobs.isError ? (
        <Card className="mt-4">
          <ErrorState detail={jobs.error.message} onRetry={() => void jobs.refetch()} />
        </Card>
      ) : (
        <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          {JOB_COLUMNS.map((column) => {
            const inColumn = all.filter((job) => job.status === column);
            return (
              <Card key={column} className="self-start">
                <Card.Header>
                  <Card.Title>{statusLabel(column)}</Card.Title>
                  <span className="tnum rounded-full bg-surface-2 px-2 py-0.5 text-xs text-ink-2">
                    {count(inColumn.length)}
                  </span>
                </Card.Header>
                {inColumn.length === 0 ? (
                  <p className="px-4 py-8 text-center text-sm text-ink-3">Nothing here.</p>
                ) : (
                  <ul className="space-y-2 p-3">
                    {inColumn.slice(0, 25).map((job) => (
                      <JobCard
                        key={job.id}
                        job={job}
                        busy={
                          actions.setStatus.isPending &&
                          actions.setStatus.variables?.id === job.id
                        }
                        onAdvance={(status) => advance(job.id, status)}
                      />
                    ))}
                    {inColumn.length > 25 ? (
                      <li className="px-1 pt-1 text-[11px] text-ink-3">
                        …and {count(inColumn.length - 25)} more
                      </li>
                    ) : null}
                  </ul>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {cancelled.length > 0 ? (
        <details className="mt-4 group">
          <summary className="cursor-pointer text-sm text-ink-2 hover:text-ink">
            Cancelled ({count(cancelled.length)})
          </summary>
          <Card className="mt-2">
            <Table caption="Cancelled jobs" minWidth="30rem">
              <THead>
                <TH>Customer</TH>
                <TH>Type</TH>
                <TH>Promised</TH>
              </THead>
              <TBody>
                {cancelled.map((job) => (
                  <TR key={job.id}>
                    <TRowHeader>{job.customer_name ?? `Customer ${job.customer_id}`}</TRowHeader>
                    <TD className="font-mono text-xs text-ink-2">{job.type}</TD>
                    <TD className="text-ink-2">{formatDate(job.promised_date)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </Card>
        </details>
      ) : null}

      <BookJobModal
        open={booking}
        storeId={storeId}
        jobTypes={jobTypes}
        busy={actions.book.isPending}
        error={formError}
        onClose={() => {
          setBooking(false);
          setFormError(null);
        }}
        onSubmit={(body) => {
          setFormError(null);
          actions.book.mutate(body, {
            onSuccess: (created) => {
              setBooking(false);
              toast.success(`Booked ${created.type}.`);
            },
            onError: (error) => setFormError(error.message),
          });
        }}
      />
    </>
  );
}

function BookJobModal({
  open,
  storeId,
  jobTypes,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  open: boolean;
  storeId: number;
  jobTypes: string[];
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const { register, handleSubmit } = useForm<BookingFields>({
    defaultValues: { customer_id: "", type: jobTypes[0] ?? "", promised_date: today },
  });

  // The quick list is enough to book from; a store with more customers than
  // this reaches them through the Customers page.
  const customers = useCustomers(storeId, { q: "", segment: "All", limit: 200, offset: 0 });
  const rows = customers.data?.items ?? [];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Take a new job"
      description="Booking a job does not message the customer. A pickup reminder is drafted only when it is marked ready."
    >
      {rows.length === 0 && !customers.isPending ? (
        <EmptyState
          title="No customers yet"
          hint="Add someone on the Customers page first — a job belongs to a customer."
        />
      ) : (
        <form
          className="space-y-4"
          onSubmit={handleSubmit((fields) =>
            onSubmit({
              customer_id: Number(fields.customer_id),
              type: fields.type,
              promised_date: fields.promised_date || null,
            }),
          )}
        >
          {error ? <Notice tone="danger">{error}</Notice> : null}

          <SelectField label="Customer" required {...register("customer_id")}>
            {rows.map((customer) => (
              <option key={customer.id} value={customer.id}>
                {customer.name} · {customer.phone}
              </option>
            ))}
          </SelectField>

          <SelectField label="Type" required {...register("type")}>
            {jobTypes.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </SelectField>

          <TextField label="Promised date" type="date" {...register("promised_date")} />

          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" busy={busy}>
              Book job
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
