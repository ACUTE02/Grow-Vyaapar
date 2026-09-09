"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/session";
import { useStores } from "@/lib/queries";

/**
 * The entry point decides where you belong: the sign-in screen, or the first
 * store you are allowed to see. A store-scoped user lands on their own store,
 * never on store 1 by accident.
 */
export default function Home() {
  const router = useRouter();
  const session = useSession();
  const stores = useStores();

  const signedIn = session.status === "authenticated";
  const storeList = stores.data;

  useEffect(() => {
    if (session.status === "anonymous") {
      router.replace("/login");
      return;
    }
    if (!signedIn || storeList === undefined) return;

    const own = session.user?.store_id;
    const target = own ?? storeList[0]?.id;
    router.replace(target === undefined ? "/login" : `/s/${target}/dashboard`);
  }, [router, session.status, session.user, signedIn, storeList]);

  return (
    <main className="grid min-h-dvh place-items-center p-6">
      <p className="text-sm text-ink-2">Loading LocalAI OS…</p>
    </main>
  );
}
