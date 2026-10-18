import { OrganizationSwitcher, Show, SignIn, UserButton } from "@clerk/react";
import { ChevronRightIcon, LifeBuoyIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useSession, type DevIdentity } from "../auth";
import { BrandMark, ErrorLine, Eyebrow } from "../components/kit";
import { Badge } from "@/components/ui/badge";

interface DevUser extends DevIdentity {
  org_name: string;
  team: string | null;
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function Login() {
  const { mode, signInDev, error } = useSession();
  const [users, setUsers] = useState<DevUser[] | null>(null);

  useEffect(() => {
    if (mode === "dev") api.get<DevUser[]>("/api/dev/users").then(setUsers);
  }, [mode]);

  const byOrg = new Map<string, DevUser[]>();
  for (const u of users ?? []) byOrg.set(u.org_name, [...(byOrg.get(u.org_name) ?? []), u]);

  return (
    <div className="grid min-h-dvh bg-background lg:grid-cols-[780fr_660fr]">
      <aside
        className="relative hidden flex-col justify-between bg-slate bg-cover bg-center p-12 text-white lg:flex"
        style={{ backgroundImage: "url(/landing/login.jpg)" }}
      >
        <div
          className="absolute inset-0"
          style={{ background: "linear-gradient(180deg, rgb(11 15 20 / 0.6) 0%, rgb(11 15 20 / 0.15) 45%, rgb(11 15 20 / 0.92) 100%)" }}
          aria-hidden="true"
        />
        <Link to="/" className="relative flex items-center gap-2.5">
          <BrandMark className="bg-rain text-slate" />
          <span className="font-display text-xl font-semibold tracking-tight">ReliefNet</span>
        </Link>
        <div className="relative flex max-w-xl flex-col gap-5">
          <span className="eyebrow text-rain">[ Flood relief coordination for Patna ]</span>
          <h1 className="text-[44px] leading-[1.1] font-normal tracking-tight">
            Understood once, merged once, and reached <span className="accent-serif">only once</span>
          </h1>
          <p className="max-w-md text-base leading-relaxed text-[#dce3e5]">
            During a flood, help requests arrive as messy messages from every direction. ReliefNet’s agents share one memory, so no
            household is forgotten and none gets three teams.
          </p>
        </div>
        <span className="num relative text-[9px] tracking-wide text-white/50">PHOTO · UNSPLASH</span>
      </aside>

      <main className="flex flex-col justify-between gap-10 px-6 py-10 sm:px-16 lg:py-12">
        <Link to="/" className="flex items-center gap-2 lg:hidden">
          <BrandMark />
          <span className="font-display text-lg font-semibold tracking-tight">ReliefNet</span>
        </Link>
        {mode === "clerk" ? (
          <div className="flex flex-col gap-6">
            <Show when="signed-out">
              <div className="flex flex-col gap-2">
                <h2 className="text-[32px] leading-tight font-normal tracking-tight">
                  Sign in to your <span className="accent-serif">relief organisation</span>
                </h2>
                <p className="text-sm text-muted-foreground">
                  New here? Ask your organisation’s admin to invite your email address. Then sign in with that address and accept the
                  invitation to join their team.
                </p>
              </div>
              <SignIn routing="hash" />
            </Show>
            <Show when="signed-in">
              <div className="flex flex-col gap-2">
                <h2 className="text-[32px] leading-tight font-normal tracking-tight">
                  Choose your <span className="accent-serif">organisation</span>
                </h2>
                <p className="text-sm text-muted-foreground">Each organisation has its own private memory. Pick the one you are working for today.</p>
                <p className="text-sm text-muted-foreground">
                  Not in the list? Your organisation’s admin must invite your email address first. Invitations appear here after you
                  accept them from the email.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <OrganizationSwitcher hidePersonal afterSelectOrganizationUrl="/" afterCreateOrganizationUrl="/" />
                <UserButton />
              </div>
              {error && <ErrorLine>{error}</ErrorLine>}
            </Show>
          </div>
        ) : (
          <div className="flex flex-col gap-6">
            <Eyebrow>Dev mode · local demo people</Eyebrow>
            <div className="flex flex-col gap-2">
              <h2 className="text-[34px] leading-tight font-normal tracking-tight">
                Who is working <span className="accent-serif">this shift?</span>
              </h2>
              <p className="text-sm text-muted-foreground">
                Choose a person to see ReliefNet as they do. Coordinators open the ops room; volunteers open the field app. Production
                deployments use Clerk accounts and organisations.
              </p>
            </div>
            <div className="flex flex-col gap-5">
              {[...byOrg.entries()].map(([org, list]) => (
                <section key={org} className="flex flex-col gap-2" aria-label={org}>
                  <Eyebrow>{org}</Eyebrow>
                  <div className="overflow-hidden rounded-xl border bg-card">
                    {list.map((u) => (
                      <button
                        key={u.id}
                        type="button"
                        className="flex w-full items-center gap-3 border-b px-3.5 py-3 text-left last:border-b-0 hover:bg-info-soft"
                        onClick={() => signInDev({ id: u.id, name: u.name, org: u.org, role: u.role })}
                      >
                        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-[11px] font-semibold text-muted-foreground">
                          {initials(u.name)}
                        </span>
                        <span className="flex min-w-0 flex-1 flex-col">
                          <b className="text-sm font-semibold">{u.name}</b>
                          <span className="text-[13px] text-muted-foreground">
                            {u.role === "volunteer" ? `Volunteer, ${u.team}` : u.role === "admin" ? "Admin, can reset demo data" : "Shift coordinator"}
                          </span>
                        </span>
                        <Badge variant={u.role === "volunteer" ? "secondary" : "default"}>{u.role === "volunteer" ? "Field app" : "Operations"}</Badge>
                        <ChevronRightIcon className="size-4 text-muted-foreground" aria-hidden="true" />
                      </button>
                    ))}
                  </div>
                </section>
              ))}
              {users === null && <p className="text-sm text-muted-foreground">Loading people…</p>}
            </div>
            {error && <ErrorLine>{error}</ErrorLine>}
          </div>
        )}
        <p className="flex items-center gap-2 border-t pt-4 text-sm text-muted-foreground">
          <LifeBuoyIcon className="size-4 text-destructive" aria-hidden="true" />
          Need help, not a sign-in?{" "}
          <Link to="/help" className="font-medium text-primary underline underline-offset-4">
            Ask for flood help here
          </Link>
        </p>
      </main>
    </div>
  );
}
