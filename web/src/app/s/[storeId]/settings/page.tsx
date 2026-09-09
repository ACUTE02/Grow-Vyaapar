"use client";

import { use, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { Notice } from "@/components/ui/states";
import { Button } from "@/components/ui/button";
import { SelectField, TextField } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { useUpdateStoreDetails } from "@/lib/queries";
import { canManage } from "@/lib/session";
import { useActiveStore } from "@/lib/active-store";
import { useSession } from "@/lib/session";
import { API_BASE, ApiError } from "@/lib/api";
import type { StoreContext } from "@/lib/types";

/**
 * What this store is configured to be, and the part of it a shopkeeper owns.
 *
 * Two kinds of value sit on this page and they are not interchangeable. The
 * store's own identity - its name, city, language, address, GSTIN, WhatsApp
 * number and review link - belongs to the shop, and a manager edits it here
 * without asking anybody. The thresholds further down come from the vertical
 * row and change what the agent drafts for every customer, so they stay behind
 * the config endpoint rather than a free-form editor.
 */
export default function SettingsPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId } = use(params);
  const store = useActiveStore();
  const session = useSession();
  const toast = useToast();
  const manager = canManage(session.user);
  const updateDetails = useUpdateStoreDetails(Number(storeId));
  const [editing, setEditing] = useState(false);

  const configEntries = Object.entries(store.config).sort(([a], [b]) => a.localeCompare(b));
  const flagEntries = Object.entries(store.feature_flags).sort(([a], [b]) => a.localeCompare(b));

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle={`How ${store.store_name} is configured. Every value here comes from the ${store.vertical_name} profile, not from code.`}
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <Card.Header>
            <Card.Title>Store</Card.Title>
          </Card.Header>
          <Card.Body>
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <Row label="Name">{store.store_name}</Row>
              <Row label="City">{store.city}</Row>
              <Row label="Vertical">{store.vertical_name}</Row>
              <Row label="Language">{store.language}</Row>
              <Row label="GSTIN">{store.gstin ?? "—"}</Row>
              <Row label="Unit">{store.unit_labels.default}</Row>
              <Row label="WhatsApp">{store.whatsapp_number ?? "—"}</Row>
              <Row label="Store id">{storeId}</Row>
            </dl>

            <div className="mt-4 border-t border-line pt-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[11px] text-ink-3">Address</p>
                  <p className="mt-0.5 text-sm text-ink">
                    {store.address ?? (
                      <span className="text-ink-3">
                        Not set, so a poster simply leaves the line out
                      </span>
                    )}
                  </p>
                </div>
                {manager && !editing ? (
                  <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
                    Edit details
                  </Button>
                ) : null}
              </div>

              {editing ? (
                <StoreDetailsForm
                  store={store}
                  busy={updateDetails.isPending}
                  serverError={
                    updateDetails.error instanceof ApiError ? updateDetails.error.message : null
                  }
                  onCancel={() => {
                    updateDetails.reset();
                    setEditing(false);
                  }}
                  onSubmit={(body) =>
                    updateDetails.mutate(body, {
                      onSuccess: () => {
                        setEditing(false);
                        toast.success("Store details updated.");
                      },
                    })
                  }
                />
              ) : (
                <p className="mt-2 text-xs text-ink-3">
                  {manager
                    ? "Edit details changes the store's own information: its name, city, language, address, GSTIN, WhatsApp number and review link. The thresholds below are a different kind of setting."
                    : "Changing the store's details is a manager action. The API refuses it for a cashier, whether or not this button is on screen."}
                </p>
              )}
            </div>
          </Card.Body>
        </Card>

        <Card>
          <Card.Header>
            <Card.Title hint="Which pages and rules this kind of shop gets">
              Feature flags
            </Card.Title>
          </Card.Header>
          <Card.Body>
            {flagEntries.length === 0 ? (
              <p className="text-sm text-ink-3">This vertical enables no optional features.</p>
            ) : (
              <ul className="flex flex-wrap gap-1.5">
                {flagEntries.map(([name, enabled]) => (
                  <li key={name}>
                    <Badge tone={enabled ? "success" : "neutral"}>
                      {name}
                      {enabled ? "" : " · off"}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card.Body>
        </Card>
      </div>

      <Card className="mt-4">
        <Card.Header>
          <Card.Title hint="Vertical defaults, with this store's overrides applied">
            Thresholds
          </Card.Title>
        </Card.Header>
        <Card.Body>
          <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3 lg:grid-cols-4">
            {configEntries.map(([key, value]) => (
              <Row key={key} label={key.replace(/_/g, " ")}>
                {typeof value === "object" && value !== null
                  ? JSON.stringify(value)
                  : String(value)}
              </Row>
            ))}
          </dl>
        </Card.Body>
      </Card>

      <Card className="mt-4">
        <Card.Header>
          <Card.Title>Session</Card.Title>
        </Card.Header>
        <Card.Body>
          <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <Row label="Signed in as">{session.user?.name ?? "—"}</Row>
            <Row label="Email">{session.user?.email ?? "—"}</Row>
            <Row label="Role">{session.user?.role ?? "—"}</Row>
            <Row label="Scoped to store">
              {session.user?.store_id === null ? "All stores" : String(session.user?.store_id ?? "—")}
            </Row>
          </dl>
          <p className="mt-4 text-xs text-ink-3">API: {API_BASE}</p>
        </Card.Body>
      </Card>

      <div className="mt-4">
        <Notice tone="info">
          Changing a threshold is a manager action and goes through the API
          (<code className="font-mono text-[11px]">PUT /config/stores/{storeId}/config</code>),
          which refuses a store the signed-in user does not belong to. It is deliberately not a
          free-form editor here — a mistyped threshold silently changes what the agent drafts for
          every customer.
        </Notice>
      </div>
    </>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-ink-3 capitalize">{label}</dt>
      <dd className="mt-0.5 truncate text-ink" title={String(children)}>
        {children}
      </dd>
    </div>
  );
}

/** Store identity: the seven columns on the store row a shopkeeper owns.
 *
 *  The thresholds below this card are a different kind of thing - they change
 *  what the agent drafts for every customer - and stay behind the config
 *  endpoint deliberately.
 *
 *  The rules here mirror the API rather than replacing it. The server is the
 *  authority and refuses the same values with the same words; checking them
 *  first only saves a round trip and puts the message beside the field. */
const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi" },
  { value: "hi-en", label: "Hindi and English mixed" },
] as const;

const detailsSchema = z.object({
  name: z.string().trim().min(2, "A store needs a name of at least 2 characters"),
  city: z.string().trim().min(2, "A store needs a city"),
  language: z.enum(["en", "hi", "hi-en"]),
  address: z.string().trim().max(256).optional(),
  gstin: z
    .string()
    .trim()
    .optional()
    .refine(
      (value) => !value || /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/i.test(value),
      "A GSTIN is 15 characters, for example 27AAPFU0939F1ZV",
    ),
  whatsapp_number: z
    .string()
    .trim()
    .optional()
    .refine(
      (value) => !value || /^\+?[0-9\s-]{10,20}$/.test(value),
      "10 to 15 digits, optionally starting with +",
    ),
  google_review_url: z
    .string()
    .trim()
    .optional()
    .refine(
      (value) => !value || /^https?:\/\//.test(value),
      "A review link must start with http:// or https://",
    ),
});

type DetailsFields = z.infer<typeof detailsSchema>;

function StoreDetailsForm({
  store,
  busy,
  serverError,
  onCancel,
  onSubmit,
}: {
  store: StoreContext;
  busy: boolean;
  serverError?: string | null;
  onCancel: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<DetailsFields>({
    resolver: zodResolver(detailsSchema),
    defaultValues: {
      name: store.store_name,
      city: store.city,
      language: (LANGUAGES.find((item) => item.value === store.language)?.value ??
        "en") as DetailsFields["language"],
      address: store.address ?? "",
      gstin: store.gstin ?? "",
      whatsapp_number: store.whatsapp_number ?? "",
      google_review_url: store.google_review_url ?? "",
    },
  });

  return (
    <form
      noValidate
      className="mt-3 space-y-3"
      onSubmit={handleSubmit((fields) =>
        onSubmit({
          name: fields.name.trim(),
          city: fields.city.trim(),
          language: fields.language,
          // An empty box means "clear it", which the API accepts for these
          // four and refuses for the three above.
          address: fields.address?.trim() || null,
          gstin: fields.gstin?.trim() || null,
          whatsapp_number: fields.whatsapp_number?.trim() || null,
          google_review_url: fields.google_review_url?.trim() || null,
        }),
      )}
    >
      {serverError ? <Notice tone="danger">{serverError}</Notice> : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <TextField label="Store name" maxLength={128} error={errors.name?.message} {...register("name")} />
        <TextField label="City" maxLength={64} error={errors.city?.message} {...register("city")} />
      </div>

      <SelectField
        label="Language"
        hint="Which language reminders are written in."
        error={errors.language?.message}
        {...register("language")}
      >
        {LANGUAGES.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </SelectField>

      <TextField
        label="Address"
        maxLength={256}
        placeholder="12 MG Road, near the bus stand"
        hint="Printed under the store name on a campaign poster. Leave it blank to omit that line."
        error={errors.address?.message}
        {...register("address")}
      />

      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          label="GSTIN"
          maxLength={20}
          placeholder="27AAPFU0939F1ZV"
          hint="Optional. Printed on every invoice."
          error={errors.gstin?.message}
          {...register("gstin")}
        />
        <TextField
          label="WhatsApp number"
          maxLength={20}
          placeholder="+919812345678"
          error={errors.whatsapp_number?.message}
          {...register("whatsapp_number")}
        />
      </div>

      <TextField
        label="Google review link"
        maxLength={512}
        placeholder="https://g.page/r/your-shop/review"
        hint="Reminders asking for a review link here."
        error={errors.google_review_url?.message}
        {...register("google_review_url")}
      />

      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" busy={busy}>
          Save details
        </Button>
      </div>
    </form>
  );
}
