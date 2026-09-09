"use client";

import { use, useState } from "react";
import { Brain, Lightbulb, RefreshCw, Sparkles, TrendingDown, Truck } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, Notice, Skeleton, SkeletonRows } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR, TRowHeader } from "@/components/ui/table";
import {
  useAtRiskCustomers,
  useInsights,
  useLatestChurnRun,
  useStockForecast,
  useStockForecastStatus,
} from "@/lib/queries";
import { useActiveStore } from "@/lib/active-store";
import { money, count, quantity, relativeDays, formatDate } from "@/lib/format";
import { ApiError } from "@/lib/api";

/**
 * Everything model-backed, in one place, with its provenance on the surface.
 *
 * The rule the backend enforces is that Python computes every number and the
 * model is only ever asked to narrate figures it was handed. This page makes
 * that visible: each panel says where its output came from - a trained model, a
 * SQL estimate, the LLM, or the template fallback - so nothing here can pass
 * itself off as cleverer than it is.
 */
export default function AssistantPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId: raw } = use(params);
  const storeId = Number(raw);
  const store = useActiveStore();

  // The insight endpoint can call an LLM, so it is not fired on page load -
  // the user asks for it. That is also why it has no refetch-on-focus.
  const [asked, setAsked] = useState(false);
  const insights = useInsights(storeId, asked);
  const atRisk = useAtRiskCustomers(storeId);
  const churnRun = useLatestChurnRun(storeId);
  const forecast = useStockForecast(storeId);
  const forecastStatus = useStockForecastStatus(storeId);

  const sourceLabel: Record<string, { tone: "success" | "info" | "warning"; text: string }> = {
    llm: { tone: "success", text: "Written by the model" },
    cache: { tone: "info", text: "From the cache" },
    template: { tone: "warning", text: "Template fallback — no model key configured" },
    template_failed: { tone: "warning", text: "Template fallback — the model call failed" },
  };

  return (
    <>
      <PageHeader
        title="AI assistant"
        subtitle={`Model-backed help for ${store.store_name}. Every figure below is computed in SQL; the model only narrates.`}
      />

      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        {/* ---- narrated insights ---- */}
        <Card>
          <Card.Header>
            <Card.Title hint="This week against last week">Weekly insights</Card.Title>
            {asked && insights.data ? (
              <div className="flex items-center gap-2">
                <Badge tone={sourceLabel[insights.data.source]?.tone ?? "neutral"}>
                  {sourceLabel[insights.data.source]?.text ?? insights.data.source}
                </Badge>
                <Button
                  size="sm"
                  variant="ghost"
                  busy={insights.isFetching}
                  onClick={() => void insights.refetch()}
                >
                  <RefreshCw className="size-3.5" aria-hidden />
                  Refresh
                </Button>
              </div>
            ) : null}
          </Card.Header>

          {!asked ? (
            <EmptyState
              icon={<Sparkles className="size-5" aria-hidden />}
              title="Ask for this week's read"
              hint="The numbers are computed first, then handed to the model to narrate. If no model key is configured, a written template says the same thing — it never silently makes something up."
              action={
                <Button variant="primary" onClick={() => setAsked(true)}>
                  <Sparkles className="size-4" aria-hidden />
                  Generate insights
                </Button>
              }
            />
          ) : insights.isPending ? (
            <div className="space-y-3 p-4">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
              <p className="text-xs text-ink-3">
                Computing the figures, then asking the model to read them…
              </p>
            </div>
          ) : insights.isError ? (
            <ErrorState
              title="Insights could not be generated"
              detail={
                insights.error instanceof ApiError
                  ? insights.error.message
                  : "The API did not answer."
              }
              onRetry={() => void insights.refetch()}
            />
          ) : insights.data === undefined ? null : (
            <>
              <Card.Body className="border-b border-line">
                <MetricRow metrics={insights.data.metrics} />
              </Card.Body>
              <ul className="divide-y divide-line">
                {insights.data.suggestions.map((item, index) => (
                  <li key={index} className="flex gap-3 px-4 py-3">
                    <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-primary-soft text-primary">
                      <Lightbulb className="size-3.5" aria-hidden />
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-ink">{item.title}</p>
                      <p className="mt-0.5 text-sm text-ink-2">{item.detail}</p>
                      {item.figure ? (
                        <p className="tnum mt-1 text-xs text-primary">{item.figure}</p>
                      ) : null}
                      {item.action ? (
                        <p className="mt-1 text-xs text-ink-3">Suggested: {item.action}</p>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
              <Card.Footer>
                <p className="text-xs text-ink-3">
                  Period: {insights.data.period} · generated {formatDate(insights.data.generated_at)}
                </p>
              </Card.Footer>
            </>
          )}
        </Card>

        {/* ---- churn ---- */}
        <Card>
          <Card.Header>
            <Card.Title hint="Trained per store on its own history">Customers at risk</Card.Title>
            {churnRun.data ? (
              <Badge tone="info">
                {churnRun.data.model_name} {churnRun.data.model_version}
              </Badge>
            ) : null}
          </Card.Header>

          {atRisk.isPending ? (
            <SkeletonRows rows={5} columns={3} />
          ) : atRisk.isError ? (
            <EmptyState
              icon={<Brain className="size-5" aria-hidden />}
              title="No churn model for this store yet"
              hint="A manager can train one from the API. Until then this panel stays empty rather than showing a guess."
            />
          ) : (atRisk.data ?? []).length === 0 ? (
            <EmptyState
              icon={<Brain className="size-5" aria-hidden />}
              title="Nobody is flagged at risk"
              hint="Either the model has not been scored yet, or no customer currently meets the risk threshold."
            />
          ) : (
            <ul className="divide-y divide-line">
              {(atRisk.data ?? []).map((row) => (
                <li key={row.customer_id} className="flex items-center gap-3 px-4 py-2.5">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-ink">{row.name}</span>
                    <span className="block text-[11px] text-ink-3">
                      {relativeDays(row.recency_days)} · {money(row.total_spend ?? 0)} lifetime
                    </span>
                  </span>
                  <Badge
                    tone={
                      row.risk_level === "high"
                        ? "danger"
                        : row.risk_level === "medium"
                          ? "warning"
                          : "neutral"
                    }
                  >
                    {Math.round(row.probability * 100)}%
                  </Badge>
                </li>
              ))}
            </ul>
          )}

          {churnRun.data ? (
            <Card.Footer>
              <p className="text-xs text-ink-3">
                Trained {formatDate(churnRun.data.trained_at)} on{" "}
                {count(churnRun.data.rows_trained)} rows.{" "}
                {typeof churnRun.data.metrics?.roc_auc === "number" ? (
                  <>ROC-AUC {(churnRun.data.metrics.roc_auc as number).toFixed(2)}.</>
                ) : null}{" "}
                The model card records this honestly rather than tuning the number away.
              </p>
            </Card.Footer>
          ) : null}
        </Card>
      </div>

      {/* ---- stock forecast ---- */}
      <Card className="mt-4">
        <Card.Header>
          <Card.Title hint="Predicted demand against what is on the shelf">
            Reorder forecast
          </Card.Title>
          {/* Every row carries a "Trained model" or "SQL estimate" badge, but a
              badge cannot say WHY. When a model exists and is being refused for
              being no better than predicting the mean, that is the single most
              important thing on this card - a manager about to order stock
              should know the clever-sounding number is not the one in play. */}
          {forecastStatus.data ? (
            <Badge tone={forecastStatus.data.in_use ? "success" : "warning"}>
              {forecastStatus.data.in_use
                ? "Trained model in use"
                : forecastStatus.data.trained
                  ? "Model trained, not in use"
                  : "No trained model"}
            </Badge>
          ) : null}
        </Card.Header>

        {forecastStatus.data && !forecastStatus.data.in_use ? (
          <div className="px-4 pb-3">
            <Notice tone={forecastStatus.data.trained ? "warning" : "info"}>
              {forecastStatus.data.explanation}
            </Notice>
          </div>
        ) : null}

        {forecast.isPending ? (
          <SkeletonRows rows={5} columns={5} />
        ) : forecast.isError ? (
          <EmptyState
            icon={<Truck className="size-5" aria-hidden />}
            title="No forecast has been computed yet"
            hint="Run the forecast from the API and this fills in. Nothing is estimated on the fly here."
          />
        ) : (forecast.data ?? []).length === 0 ? (
          <EmptyState
            icon={<Truck className="size-5" aria-hidden />}
            title="Nothing needs reordering soon"
            hint="No product is predicted to run out inside the reorder window."
          />
        ) : (
          <Table caption="Products predicted to need a reorder">
            <THead>
              <TH>Product</TH>
              <TH align="right">In stock</TH>
              <TH align="right">Daily demand</TH>
              <TH align="right">Days left</TH>
              <TH align="right">Suggested order</TH>
              <TH>Basis</TH>
            </THead>
            <TBody>
              {(forecast.data ?? []).map((row) => (
                <TR key={row.product_id}>
                  <TRowHeader>
                    <span className="block truncate">{row.name}</span>
                    <span className="block font-mono text-[11px] font-normal text-ink-3">
                      {row.sku}
                    </span>
                  </TRowHeader>
                  <TD align="right" numeric>
                    {quantity(row.qty_on_hand, row.unit_label)}
                  </TD>
                  <TD align="right" numeric className="text-ink-2">
                    {row.predicted_daily_velocity.toFixed(2)}
                  </TD>
                  <TD align="right" numeric>
                    {row.days_to_stockout === null || row.days_to_stockout === undefined ? (
                      <span className="text-ink-3">—</span>
                    ) : (
                      Math.round(row.days_to_stockout)
                    )}
                  </TD>
                  <TD align="right" numeric className="font-medium">
                    {quantity(row.suggested_reorder_qty, row.unit_label)}
                  </TD>
                  <TD>
                    {/* "model" and "estimate" mean different things and the
                        difference is not cosmetic - say which one this row is. */}
                    <Badge tone={row.source === "model" ? "success" : "neutral"}>
                      {row.source === "model" ? "Trained model" : "SQL estimate"}
                    </Badge>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <div className="mt-4">
        <Notice tone="info">
          <span className="flex items-start gap-2">
            <TrendingDown className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              Nothing on this page sends a message or spends money. Winback drafts produced from
              the churn scores land in the Outbox as queued, where a human still has to press send.
            </span>
          </span>
        </Notice>
      </div>
    </>
  );
}

/** The exact figures the narrator was handed, shown beside its narration. */
function MetricRow({ metrics }: { metrics: Record<string, unknown> }) {
  const week = Number(metrics.week_sales ?? 0);
  const previous = Number(metrics.previous_week_sales ?? 0);
  const change = Number(metrics.week_over_week_change_pct ?? 0);
  const bills = Number(metrics.week_invoices ?? 0);
  const average = Number(metrics.average_bill_value ?? 0);

  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Figure label="This week" value={money(week)} />
      <Figure label="Last week" value={money(previous)} />
      <Figure
        label="Change"
        value={`${change > 0 ? "+" : ""}${change}%`}
        tone={change > 0 ? "up" : change < 0 ? "down" : "flat"}
      />
      <Figure label="Bills" value={`${count(bills)} · avg ${money(average)}`} />
    </dl>
  );
}

function Figure({
  label,
  value,
  tone = "flat",
}: {
  label: string;
  value: string;
  tone?: "up" | "down" | "flat";
}) {
  const colour =
    tone === "up" ? "text-success" : tone === "down" ? "text-danger" : "text-ink";
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-ink-3">{label}</dt>
      <dd className={`tnum mt-0.5 truncate font-display text-base font-semibold ${colour}`}>
        {value}
      </dd>
    </div>
  );
}
