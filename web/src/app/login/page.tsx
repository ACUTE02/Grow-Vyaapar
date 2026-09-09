"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Store } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { Notice } from "@/components/ui/states";
import { useSession } from "@/lib/session";
import { ApiError } from "@/lib/api";

const schema = z.object({
  email: z.string().min(1, "Enter your email address").email("That is not an email address"),
  password: z.string().min(1, "Enter your password"),
});

type Fields = z.infer<typeof schema>;

export default function LoginPage() {
  const router = useRouter();
  const session = useSession();
  const [failure, setFailure] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Fields>({ resolver: zodResolver(schema), mode: "onSubmit" });

  useEffect(() => {
    if (session.status === "authenticated") router.replace("/");
  }, [session.status, router]);

  async function onSubmit(fields: Fields) {
    setFailure(null);
    try {
      await session.signIn(fields.email.trim(), fields.password);
      router.replace("/");
    } catch (error) {
      setFailure(
        error instanceof ApiError
          ? error.message
          : "Cannot reach the API. Start it with: uvicorn app.main:app --reload",
      );
    }
  }

  return (
    <main id="main" className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      {/* The brand half carries the product's claim; it is decorative on a
          phone, so it is simply not rendered there rather than squashed. */}
      <section className="relative hidden flex-col justify-between overflow-hidden bg-primary p-10 text-primary-ink lg:flex">
        <div
          aria-hidden
          className="absolute -top-24 -right-24 size-96 rounded-full bg-accent/20 blur-3xl"
        />
        <div className="relative flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-lg bg-primary-ink/15">
            <Store className="size-5" aria-hidden />
          </span>
          <span className="font-display text-lg font-semibold tracking-tight">LocalAI OS</span>
        </div>
        <div className="relative max-w-md">
          <h1 className="font-display text-3xl leading-tight font-semibold text-balance">
            Billing, stock and customers for the shop down the road.
          </h1>
          <p className="mt-4 text-sm/relaxed text-primary-ink/80">
            One counter for eight kinds of retail — kirana, chemist, optician, boutique — with a
            marketing agent that drafts, and a human who approves. Nothing is sent to a customer
            without someone pressing send.
          </p>
        </div>
        <p className="relative text-xs text-primary-ink/60">
          Vertical behaviour is configuration, not code.
        </p>
      </section>

      <section className="flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="grid size-9 place-items-center rounded-lg bg-primary text-primary-ink">
              <Store className="size-5" aria-hidden />
            </span>
            <span className="font-display text-lg font-semibold tracking-tight">LocalAI OS</span>
          </div>

          <h2 className="font-display text-2xl font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1.5 text-sm text-ink-2">
            The same check runs in the API for every request, not only here.
          </p>

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-7 space-y-4">
            {failure === null ? null : <Notice tone="danger">{failure}</Notice>}

            <TextField
              label="Email"
              type="email"
              autoComplete="username"
              autoFocus
              placeholder="owner@localai.demo"
              error={errors.email?.message}
              {...register("email")}
            />
            <TextField
              label="Password"
              type="password"
              autoComplete="current-password"
              error={errors.password?.message}
              {...register("password")}
            />

            <Button type="submit" variant="primary" size="lg" busy={isSubmitting} className="w-full">
              Sign in
            </Button>
          </form>

          <p className="mt-6 text-xs/relaxed text-ink-3">
            The demo seed creates a platform owner plus a manager and a cashier for each store.
            See the README for the addresses and the demo password.
          </p>
        </div>
      </section>
    </main>
  );
}
