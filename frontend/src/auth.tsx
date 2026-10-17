import { ClerkProvider, useAuth, useOrganization, useUser } from "@clerk/react";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setCredentialSource, type Credentials } from "./api";
import type { AppConfig, Me } from "./types";

const CLERK_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;
const DEV_KEY = "reliefnet.dev-identity";

export interface DevIdentity {
  id: string;
  name: string;
  org: string;
  role: string;
}

interface AuthState {
  config: AppConfig | null;
  me: Me | null;
  loading: boolean;
  error: string | null;
  mode: "dev" | "clerk";
  signInDev: (who: DevIdentity) => void;
  signOut: () => void;
  refresh: () => void;
}

const Ctx = createContext<AuthState | null>(null);

export function useSession(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession outside AuthProvider");
  return v;
}

function readDev(): DevIdentity | null {
  try {
    const raw = localStorage.getItem(DEV_KEY);
    return raw ? (JSON.parse(raw) as DevIdentity) : null;
  } catch {
    return null;
  }
}

function devCredentials(who: DevIdentity | null): Credentials {
  if (!who) return { headers: {}, query: {} };
  return {
    headers: { "x-dev-user": who.id, "x-dev-org": who.org, "x-dev-role": who.role, "x-dev-name": who.name },
    query: { dev_user: who.id, dev_org: who.org, dev_role: who.role, dev_name: who.name },
  };
}

function DevAuth({ config, children }: { config: AppConfig; children: ReactNode }) {
  const [who, setWho] = useState<DevIdentity | null>(readDev);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  setCredentialSource(async () => devCredentials(who));

  useEffect(() => {
    if (!who) {
      setMe(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    api
      .get<Me>("/api/me")
      .then((m) => {
        setMe(m);
        setError(null);
      })
      .catch((e) => {
        setError(String(e.message ?? e));
        setMe(null);
      })
      .finally(() => setLoading(false));
  }, [who, tick]);

  const signInDev = useCallback((w: DevIdentity) => {
    try {
      localStorage.setItem(DEV_KEY, JSON.stringify(w));
    } catch {
      /* private mode: identity lasts for this tab only */
    }
    setWho(w);
  }, []);
  const signOut = useCallback(() => {
    try {
      localStorage.removeItem(DEV_KEY);
    } catch {
      /* ignore */
    }
    setWho(null);
  }, []);

  return (
    <Ctx.Provider
      value={{ config, me, loading, error, mode: "dev", signInDev, signOut, refresh: () => setTick((t) => t + 1) }}
    >
      {children}
    </Ctx.Provider>
  );
}

function ClerkBridge({ config, children }: { config: AppConfig; children: ReactNode }) {
  const { isLoaded, isSignedIn, getToken, orgSlug, signOut } = useAuth();
  const { user } = useUser();
  const { organization } = useOrganization();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const displayName = user?.fullName || user?.primaryEmailAddress?.emailAddress || "";

  setCredentialSource(async (): Promise<Credentials> => {
    const token = await getToken();
    return {
      headers: token
        ? { authorization: `Bearer ${token}`, "x-user-name": encodeURIComponent(displayName),"x-org-name": encodeURIComponent(organization?.name ?? "") }
        : ({} as Record<string, string>),
      query: token ? { token } : ({} as Record<string, string>),
    };
  });

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn || !orgSlug) {
      setMe(null);
      return;
    }
    api
      .get<Me>("/api/me")
      .then((m) => {
        setMe(m);
        setError(null);
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, [isLoaded, isSignedIn, orgSlug, tick]);

  return (
    <Ctx.Provider
      value={{
        config,
        me,
        loading: !isLoaded || (isSignedIn === true && !!orgSlug && !me && !error),
        error,
        mode: "clerk",
        signInDev: () => undefined,
        signOut: () => void signOut(),
        refresh: () => setTick((t) => t + 1),
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AppConfig>("/api/config")
      .then(setConfig)
      .catch((e) => setFailed(String(e.message ?? e)));
  }, []);

  if (failed)
    return (
      <div className="boot">
        <p>ReliefNet cannot reach its server ({failed}). Start the API on port 8000, then reload this page.</p>
      </div>
    );
  if (!config) return <div className="boot" aria-busy="true" />;

  if (config.auth_mode === "clerk") {
    if (!CLERK_KEY)
      return (
        <div className="boot">
          <p>The server uses Clerk sign-in, but this app has no VITE_CLERK_PUBLISHABLE_KEY. Add it to frontend/.env.</p>
        </div>
      );
    return (
      <ClerkProvider publishableKey={CLERK_KEY}>
        <ClerkBridge config={config}>{children}</ClerkBridge>
      </ClerkProvider>
    );
  }
  return <DevAuth config={config}>{children}</DevAuth>;
}
