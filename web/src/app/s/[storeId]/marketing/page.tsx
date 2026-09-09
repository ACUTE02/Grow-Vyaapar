"use client";

import { use, useState } from "react";
import { Megaphone, Sparkles, Users } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { TextField } from "@/components/ui/field";
import { EmptyState, ErrorState, Notice, Skeleton, SkeletonRows } from "@/components/ui/states";
import { SegmentMix } from "@/components/charts/segment-mix";
import { CampaignCard } from "@/components/marketing/campaign-card";
import { useToast } from "@/components/ui/toast";
import {
  useCampaignActions,
  useCampaigns,
  useRebuildSegments,
  useReminderRules,
  useSegmentSummary,
} from "@/lib/queries";
import { useActiveStore } from "@/lib/active-store";
import { useSession, canManage } from "@/lib/session";


export default function MarketingPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId: raw } = use(params);
  const storeId = Number(raw);
  const store = useActiveStore();
  const session = useSession();
  const toast = useToast();
  const manager = canManage(session.user);

  const [occasion, setOccasion] = useState("");
  const [offerText, setOfferText] = useState("");

  const segments = useSegmentSummary(storeId);
  const campaigns = useCampaigns(storeId);
  const rules = useReminderRules(storeId);
  const rebuild = useRebuildSegments(storeId);
  const { create, regenerate, setStatus } = useCampaignActions(storeId);

  return (
    <>
      <PageHeader
        title="Marketing"
        subtitle={`Who to talk to at ${store.store_name}, and what to say. Nothing is delivered from this page.`}
      />

      <div className="grid gap-4 xl:grid-cols-[1fr_1.2fr]">
        <div className="space-y-4">
          <Card>
            <Card.Header>
              <Card.Title hint="Recency, frequency and spend">Customer targeting</Card.Title>
              <Button
                size="sm"
                variant="secondary"
                busy={rebuild.isPending}
                onClick={() =>
                  rebuild.mutate(undefined, {
                    onSuccess: () => toast.success("Segments rebuilt."),
                    onError: (error) => toast.error(error.message),
                  })
                }
              >
                Rebuild
              </Button>
            </Card.Header>
            <Card.Body>
              {segments.isPending ? (
                <Skeleton className="h-32 w-full" />
              ) : (
                <SegmentMix distribution={segments.data ?? {}} />
              )}
            </Card.Body>
          </Card>

          <Card>
            <Card.Header>
              <Card.Title hint={`Active for ${store.vertical_name}`}>Reminder rules</Card.Title>
            </Card.Header>
            {rules.isPending ? (
              <SkeletonRows rows={4} columns={3} />
            ) : rules.isError ? (
              <ErrorState detail={rules.error.message} onRetry={() => void rules.refetch()} />
            ) : (rules.data ?? []).length === 0 ? (
              <EmptyState
                title="No rules for this vertical"
                hint="Reminder rules are configuration, loaded per vertical."
              />
            ) : (
              <ul className="divide-y divide-line">
                {(rules.data ?? []).map((rule) => (
                  <li key={rule.id} className="flex items-center gap-3 px-4 py-2.5">
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm text-ink">{rule.kind}</span>
                      <span className="block text-[11px] text-ink-3">
                        {rule.signal} · {rule.channel}
                      </span>
                    </span>
                    <Badge tone={rule.enabled ? "success" : "neutral"}>
                      {rule.enabled ? "Enabled" : "Off"}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
            <Card.Footer>
              <p className="text-xs text-ink-3">
                A different vertical enables a different set, which is why this list changes with
                the store — it comes from the vertical row, not from code.
              </p>
            </Card.Footer>
          </Card>
        </div>

        <Card>
          <Card.Header>
            <Card.Title hint="Drafted by the agent, published by a human">
              Festival campaigns
            </Card.Title>
          </Card.Header>

          {manager ? (
            <Card.Body className="border-b border-line">
              <form
                className="flex flex-wrap items-end gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  const trimmed = occasion.trim();
                  if (trimmed.length < 2) return;
                  create.mutate(
                    { occasion: trimmed, offer_text: offerText.trim() || null },
                    {
                      onSuccess: (campaign) => {
                        setOccasion("");
                        setOfferText("");
                        toast.success(`Draft ready for ${campaign.occasion}.`);
                      },
                      onError: (error) => toast.error(error.message),
                    },
                  );
                }}
              >
                <TextField
                  label="Occasion"
                  placeholder="Diwali, Eid, back to school…"
                  value={occasion}
                  onChange={(event) => setOccasion(event.currentTarget.value)}
                  wrapClassName="flex-1 min-w-40"
                />
                <TextField
                  label="Offer (optional)"
                  placeholder="20% off toothpaste, Buy 1 Get 1 on soap…"
                  maxLength={140}
                  value={offerText}
                  onChange={(event) => setOfferText(event.currentTarget.value)}
                  wrapClassName="flex-[2] min-w-56"
                />
                <Button type="submit" variant="primary" busy={create.isPending}>
                  <Sparkles className="size-4" aria-hidden />
                  Draft a campaign
                </Button>
              </form>
              <p className="mt-2 text-xs text-ink-3">
                The model writes the caption and the picture from this store&apos;s own profile —
                its vertical, city and stock. The offer is <em>not</em> left to the model: image
                generators cannot spell reliably, so it is drawn onto the poster afterwards as
                real text. If no model key is configured the caption falls back to a template
                rather than failing.
              </p>
            </Card.Body>
          ) : null}

          {campaigns.isPending ? (
            <SkeletonRows rows={4} columns={3} />
          ) : campaigns.isError ? (
            <ErrorState detail={campaigns.error.message} onRetry={() => void campaigns.refetch()} />
          ) : (campaigns.data ?? []).length === 0 ? (
            <EmptyState
              icon={<Megaphone className="size-5" aria-hidden />}
              title="No campaigns yet"
              hint={
                manager
                  ? "Name an occasion above and the agent drafts a caption and an image prompt."
                  : "A manager can draft a campaign for the next festival."
              }
            />
          ) : (
            <ul className="divide-y divide-line">
              {(campaigns.data ?? []).map((campaign) => (
                <CampaignCard
                  key={campaign.id}
                  campaign={campaign}
                  manager={manager}
                  regenerating={
                    regenerate.isPending && regenerate.variables === campaign.id
                  }
                  onRegenerate={() =>
                    regenerate.mutate(campaign.id, {
                      onSuccess: () =>
                        toast.success(`New poster drafted for ${campaign.occasion}.`),
                      onError: (error) => toast.error(error.message),
                    })
                  }
                  onSetStatus={(status) =>
                    setStatus.mutate(
                      { id: campaign.id, status },
                      {
                        onSuccess: () =>
                          toast.success(
                            status === "published"
                              ? "Marked as published."
                              : "Campaign saved.",
                          ),
                        onError: (error) => toast.error(error.message),
                      },
                    )
                  }
                />
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-4">
        <Notice tone="info">
          <span className="flex items-start gap-2">
            <Users className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              A campaign here is copy, not a send. Messages to customers live in the Outbox, where
              each one needs an explicit human press — plus a consent check, a daily cap and a rate
              limit before it leaves.
            </span>
          </span>
        </Notice>
      </div>
    </>
  );
}
