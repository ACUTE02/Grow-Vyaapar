"use client";

import {
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { apiGet, apiPost, readToken, writeToken, ApiError } from "./api";
import { loginResponse, user as userSchema, type User } from "./types";

/**
 * Who is signed in.
 *
 * The token lives in localStorage because the API is on a different origin
 * with allow_credentials off, so its httponly cookie is never sent from here -
 * a bearer header is the only channel available. That trades CSRF safety for
 * XSS exposure, which is the accepted shape for a token-based SPA; the
 * mitigation is that nothing in this app renders untrusted HTML.
 *
 * Consumers see status/user/signIn/signOut and never touch storage.
 */
type SessionState =
  | { status: "loading"; user: null }
  | { status: "authenticated"; user: User }
  | { status: "anonymous"; user: null };

type SessionApi = SessionState & {
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
};

const SessionContext = createContext<SessionApi | null>(null);

export function useSession(): SessionApi {
  const api = use(SessionContext);
  if (api === null) throw new Error("useSession must be used inside <SessionProvider>");
  return api;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: "loading", user: null });

  // Revalidate a stored token once per app load. A token that expired
  // overnight must not leave the shell rendering a signed-in chrome around
  // 401s from every panel.
  useEffect(() => {
    let cancelled = false;

    // One async path whether or not a token exists. Reading storage during the
    // initial useState would disagree with the server render, and setting state
    // synchronously here would cascade a second render before paint - so the
    // no-token case resolves through the same promise as the validated one.
    Promise.resolve()
      .then(() => (readToken() === null ? null : apiGet<unknown>("/auth/me")))
      .then((raw) => {
        if (cancelled) return;
        setState(
          raw === null
            ? { status: "anonymous", user: null }
            : { status: "authenticated", user: userSchema.parse(raw) },
        );
      })
      .catch(() => {
        if (cancelled) return;
        writeToken(null);
        setState({ status: "anonymous", user: null });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    try {
      const raw = await apiPost<unknown>("/auth/login", undefined, { email, password });
      const parsed = loginResponse.parse(raw);
      writeToken(parsed.access_token);
      setState({ status: "authenticated", user: parsed.user });
    } catch (error) {
      writeToken(null);
      setState({ status: "anonymous", user: null });
      // The API deliberately does not say which half was wrong; pass its own
      // wording through rather than inventing a friendlier, vaguer one.
      throw error instanceof ApiError
        ? error
        : new Error("Cannot reach the API. Is uvicorn running on port 8000?");
    }
  }, []);

  const signOut = useCallback(() => {
    writeToken(null);
    setState({ status: "anonymous", user: null });
    // Best effort: clears the cookie the API also set. A failure here does not
    // matter, the token this app uses is already gone.
    void apiPost("/auth/logout").catch(() => {});
  }, []);

  const value = useMemo<SessionApi>(
    () => ({ ...state, signIn, signOut }),
    [state, signIn, signOut],
  );

  return <SessionContext value={value}>{children}</SessionContext>;
}

/** Role gate, used to hide what a role cannot do. The API enforces it too -
 *  this only saves the user a refusal they could not have acted on. */
export function canManage(user: User | null): boolean {
  return user?.role === "owner" || user?.role === "manager";
}
