"use client";

import Image from "next/image";
import { useState } from "react";
import { Download, RefreshCw, Tag } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import { assetUrl } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Campaign } from "@/lib/types";

/**
 * One drafted campaign: the poster, the copy, and what a shopkeeper can do
 * with it.
 *
 * Save and Mark published only move the `status` column - nothing is sent,
 * posted or shared by either. Download is the one that actually gets the
 * poster out of the building, and it deliberately hands the file to the
 * shopkeeper rather than routing it through the Outbox: that pipeline is for
 * consented, rate-limited, customer-by-customer reminders, and forwarding a
 * poster to your own broadcast list is a different and much simpler act.
 */
export function CampaignCard({
  campaign,
  manager,
  onSetStatus,
  onRegenerate,
  regenerating,
}: {
  campaign: Campaign;
  manager: boolean;
  onSetStatus: (status: string) => void;
  onRegenerate: () => void;
  regenerating: boolean;
}) {
  const toast = useToast();
  const [downloading, setDownloading] = useState(false);
  const src = assetUrl(campaign.image_url);
  const published = campaign.status === "published";

  async function download() {
    if (!src) return;
    setDownloading(true);
    try {
      // Fetched as a blob rather than linked with `download`: the attribute is
      // ignored cross-origin, which is exactly the case for a poster the
      // generator served rather than one we composed.
      const response = await fetch(src);
      if (!response.ok) throw new Error(`The poster could not be fetched (${response.status})`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${campaign.occasion.replace(/\W+/g, "-").toLowerCase()}-poster.jpg`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(
        error instanceof Error
          ? `${error.message}. Open the image in a new tab and save it from there.`
          : "The poster could not be downloaded.",
      );
    } finally {
      setDownloading(false);
    }
  }

  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-display text-sm font-semibold text-ink">{campaign.occasion}</span>
        <Badge tone={published ? "success" : campaign.status === "saved" ? "info" : "neutral"}>
          {campaign.status}
        </Badge>
        <span className="text-[11px] text-ink-3">{formatDate(campaign.created_at)}</span>
      </div>

      {/* The offer is shown in the list as well as on the poster, so scrolling
          past history tells you which deal each one carried. */}
      {campaign.offer_text ? (
        <p className="mt-1.5 inline-flex items-center gap-1.5 rounded-md bg-accent-soft px-2 py-1 text-xs font-medium text-accent">
          <Tag className="size-3" aria-hidden />
          {campaign.offer_text}
        </p>
      ) : null}

      {campaign.caption ? (
        <p className="mt-1.5 text-sm text-ink-2">{campaign.caption}</p>
      ) : null}

      {campaign.hashtags.length > 0 ? (
        <p className="mt-1.5 text-xs text-primary">
          {campaign.hashtags.map((tag) => `#${tag.replace(/^#/, "")}`).join(" ")}
        </p>
      ) : null}

      {src ? (
        <a
          href={src}
          target="_blank"
          rel="noreferrer"
          className="relative mt-2 block h-56 w-full overflow-hidden rounded-lg border border-line"
          aria-label={`Open the full-size ${campaign.occasion} poster`}
        >
          {/* Unoptimised: the background comes from a generation service on a
              host Next cannot pre-declare, and a composed poster is already
              sized for sharing. */}
          <Image
            src={src}
            alt={
              campaign.offer_text
                ? `${campaign.occasion} poster reading “${campaign.offer_text}”`
                : `${campaign.occasion} poster`
            }
            fill
            unoptimized
            className="object-cover"
          />
        </a>
      ) : null}

      <div className="mt-2 flex flex-wrap gap-2">
        {src ? (
          <Button size="sm" variant="secondary" busy={downloading} onClick={() => void download()}>
            <Download className="size-3.5" aria-hidden />
            Download
          </Button>
        ) : null}

        {manager ? (
          <>
            <Button
              size="sm"
              variant="secondary"
              busy={regenerating}
              // Regenerating a published poster would replace one already in
              // use; the API refuses it too, this only saves the round trip.
              disabled={published}
              title={
                published
                  ? "Set this back to saved first — it is already published"
                  : undefined
              }
              onClick={onRegenerate}
            >
              <RefreshCw className="size-3.5" aria-hidden />
              Regenerate
            </Button>

            {published ? (
              <Button size="sm" variant="ghost" onClick={() => onSetStatus("saved")}>
                Unpublish
              </Button>
            ) : (
              <>
                <Button size="sm" variant="secondary" onClick={() => onSetStatus("saved")}>
                  Save
                </Button>
                <Button size="sm" variant="primary" onClick={() => onSetStatus("published")}>
                  Mark published
                </Button>
              </>
            )}
          </>
        ) : null}
      </div>
    </li>
  );
}
