import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { APIError, getCurrentUser, logout as endSession, setCsrfToken } from "../services/api";
import type { AuthenticatedUser } from "../types/auth";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  status: AuthStatus;
  user: AuthenticatedUser | null;
  error: string | null;
  signOut: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [error, setError] = useState<string | null>(null);

  const restoreSession = useCallback(async () => {
    setStatus("loading");
    try {
      const current = await getCurrentUser();
      setCsrfToken(current.csrf_token);
      setUser(current.user);
      setError(null);
      setStatus("authenticated");
    } catch (reason) {
      setCsrfToken(null);
      setUser(null);
      setStatus("unauthenticated");
      if (reason instanceof APIError && reason.status === 401) {
        setError(null);
      } else {
        setError("Unable to verify your sign-in. Check your connection and try again.");
      }
    }
  }, []);

  useEffect(() => {
    void restoreSession();
  }, [restoreSession]);

  const signOut = useCallback(async () => {
    try {
      await endSession();
      setCsrfToken(null);
      setUser(null);
      setError(null);
      setStatus("unauthenticated");
      return true;
    } catch {
      setError("We couldn't sign you out. Please try again.");
      return false;
    }
  }, []);

  const value = useMemo(
    () => ({ status, user, error, signOut }),
    [status, user, error, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
