"use client";

import { use, useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/shell/app-shell";
import { ActiveStoreProvider } from "@/lib/active-store";
import { useStoreContext } from "@/lib/queries";
import { useSession } from "@/lib/session";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { ApiError } from "@/lib/api";

/**
 * Everything below /s/[storeId] runs inside a resolved store context.
 *
 * The context is fetched once here and handed down, so no page repeats the
 * request and none of them can disagree about which store they are on. A 403
 * is not an error state but a wrong turn: a store-scoped user who edits the URL
 * is sent back to their own store.
 */
export default function StoreLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ storeId: string }>;
}) {
  const { storeId: rawStoreId } = use(params);
  const storeId = Number(rawStoreId);
  const router = useRouter();
  const session = useSession();
  const context = useStoreContext(storeId);

  useEffect(() => {
    if (session.status === "anonymous") router.replace("/login");
  }, [session.status, router]);

  const forbidden = context.error instanceof ApiError && context.error.isForbidden;
  const ownStore = session.user?.store_id;

  useEffect(() => {
    if (forbidden && ownStore !== null && ownStore !== undefined) {
      router.replace(`/s/${ownStore}/dashboard`);
    }
  }, [forbidden, ownStore, router]);

  if (session.status === "loading" || context.isLoading) {
    return <ShellSkeleton />;
  }

  if (context.isError || context.data === undefined) {
    const error = context.error;
    return (
      <main className="grid min-h-dvh place-items-center p-6">
        <ErrorState
          title={forbidden ? "Not your store" : "Could not load this store"}
          detail={
            error instanceof ApiError
              ? error.message
              : "The API did not answer. Start it with: uvicorn app.main:app --reload"
          }
          onRetry={() => void context.refetch()}
        />
      </main>
    );
  }

  return (
    <ActiveStoreProvider value={context.data}>
      <AppShell storeId={storeId}>{children}</AppShell>
    </ActiveStoreProvider>
  );
}

/** The shell's own loading state, shaped like the shell so nothing jumps. */
function ShellSkeleton() {
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[16rem_1fr]">
      <div className="hidden border-r border-line bg-surface p-3 lg:block">
        <Skeleton className="mb-4 h-8 w-40" />
        {Array.from({ length: 9 }, (_, index) => (
          <Skeleton key={index} className="mb-1.5 h-9 w-full" />
        ))}
      </div>
      <div>
        <div className="flex h-14 items-center border-b border-line px-6">
          <Skeleton className="h-9 w-64" />
        </div>
        <div className="space-y-4 p-6">
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-40 w-full" />
        </div>
      </div>
    </div>
  );
}
