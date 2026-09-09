"use client";

import {
  createContext,
  use,
  useCallback,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";

type Tone = "success" | "error" | "info";
type Toast = { id: number; tone: Tone; message: string };

/**
 * The provider is the only thing that knows how toasts are stored - consumers
 * see `toast.success(...)` and nothing else. Swapping the queue for a library
 * later would not touch a single call site.
 */
type ToastApi = {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const api = use(ToastContext);
  if (api === null) throw new Error("useToast must be used inside <ToastProvider>");
  return api;
}

const ICONS: Record<Tone, ReactNode> = {
  success: <CheckCircle2 className="size-4 shrink-0" aria-hidden />,
  error: <XCircle className="size-4 shrink-0" aria-hidden />,
  info: <Info className="size-4 shrink-0" aria-hidden />,
};

const TONES: Record<Tone, string> = {
  success: "border-success/30 bg-success-soft text-success",
  error: "border-danger/30 bg-danger-soft text-danger",
  info: "border-info/30 bg-info-soft text-info",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (tone: Tone, message: string) => {
      const id = (nextId.current += 1);
      // Functional setState so `push` never depends on the current list and
      // therefore stays stable for the lifetime of the provider.
      setToasts((current) => [...current, { id, tone, message }]);
      // An error stays longer: it usually carries something worth reading.
      window.setTimeout(() => dismiss(id), tone === "error" ? 7000 : 4000);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (message: string) => push("success", message),
      error: (message: string) => push("error", message),
      info: (message: string) => push("info", message),
    }),
    [push],
  );

  return (
    <ToastContext value={api}>
      {children}
      {/* role=status announces without stealing focus; errors get role=alert
          on the item itself so they interrupt. */}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 sm:items-end"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role={toast.tone === "error" ? "alert" : undefined}
            className={cn(
              "pointer-events-auto flex w-full max-w-md items-start gap-2.5 rounded-lg border px-3.5 py-3 text-sm shadow-pop",
              TONES[toast.tone],
            )}
          >
            {ICONS[toast.tone]}
            <p className="min-w-0 flex-1 break-words">{toast.message}</p>
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              aria-label="Dismiss notification"
              className="-m-1 shrink-0 rounded p-1 opacity-70 hover:opacity-100"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </div>
        ))}
      </div>
    </ToastContext>
  );
}
