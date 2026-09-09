"use client";

import { use, useState } from "react";
import { useForm } from "react-hook-form";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { Notice } from "@/components/ui/states";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { useUpdateStoreDetails } from "@/lib/queries";
import { canManage } from "@/lib/session";
import { useActiveStore } from "@/lib/active-store";
import { useSession } from "@/lib/session";
import { API_BASE } from "@/lib/api";

/**
 * What this store is configured to be.
 *
 * Read-only on purpose: these values come from the vertical row and the
 * store_config overrides, and editing them is a manager action the API gates
 * behind PUT /config/stores/{id}/config. Showing them here is what makes the
 * "vertical behaviour is configuration, not code" claim checkable rather than
 * merely asserted.
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
                        Not set — the poster simply leaves the line out
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
                  onCancel={() => setEditing(false)}
                  onSubmit={(body) =>
                    updateDetails.mutate(body, {
                      onSuccess: () => {
                        setEditing(false);
                        toast.success("Store details updated.");
                      },
                      onError: (error) => toast.error(error.message),
                    })
                  }
                />
              ) : (
                <p className="mt-2 text-xs text-ink-3">
                  The address is printed under the store name on a campaign poster. It is
                  identity, not a threshold the agent reads, so it lives on the store row rather
                  than in the configuration below.
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

/** The one editable thing on this page. Everything else here comes from the
 *  vertical row and is changed through the config endpoint deliberately, not
 *  through a free-form editor. */
function StoreDetailsForm({
  store,
  busy,
  onCancel,
  onSubmit,
}: {
  store: { address?: string | null; whatsapp_number?: string | null };
  busy: boolean;
  onCancel: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const { register, handleSubmit } = useForm<{ address: string; whatsapp_number: string }>({
    defaultValues: {
      address: store.address ?? "",
      whatsapp_number: store.whatsapp_number ?? "",
    },
  });

  return (
    <form
      className="mt-3 space-y-3"
      onSubmit={handleSubmit((fields) =>
        onSubmit({
          address: fields.address.trim() || null,
          whatsapp_number: fields.whatsapp_number.trim() || null,
        }),
      )}
    >
      <TextField
        label="Address"
        maxLength={256}
        placeholder="12 MG Road, near the bus stand"
        hint="Printed under the store name on a poster. Leave it blank to omit that line."
        {...register("address")}
      />
      <TextField
        label="WhatsApp number"
        maxLength={20}
        placeholder="+9198…"
        {...register("whatsapp_number")}
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
