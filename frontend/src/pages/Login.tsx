import { OrganizationSwitcher, Show, SignIn, UserButton } from "@clerk/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useSession, type DevIdentity } from "../auth";

interface DevUser extends DevIdentity {
  org_name: string;
  team: string | null;
}

/** A fragment of chart: soundings and contour lines around a river bend. */
function ChartArt() {
  const soundings = [
    [120, 180, "3"], [260, 140, "4"], [410, 210, "6"], [560, 170, "7"], [700, 230, "5"],
    [180, 300, "2"], [340, 330, "5"], [500, 300, "8"], [650, 340, "6"], [820, 290, "4"],
  ] as const;
  return (
    <svg viewBox="0 0 900 700" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <path d="M0 0H900V110C760 150 640 90 480 120S180 90 0 140Z" fill="var(--land)" stroke="var(--land-edge)" />
      <path d="M0 420C160 380 300 450 470 420S760 380 900 410V700H0Z" fill="var(--land)" stroke="var(--land-edge)" />
      {[0, 1, 2].map((i) => (
        <path
          key={i}
          d={`M0 ${190 + i * 45}C180 ${150 + i * 45} 330 ${230 + i * 40} 480 ${200 + i * 45}S760 ${160 + i * 45} 900 ${200 + i * 42}`}
          fill="none"
          stroke="var(--water-deep)"
          strokeDasharray={i === 1 ? "6 6" : undefined}
        />
      ))}
      {soundings.map(([x, y, d], i) => (
        <text key={i} x={x} y={y} fill="var(--water-ink)" fontStyle="italic" fontSize="18">
          {d}
        </text>
      ))}
      <path d="M430 116L430 425" stroke="var(--hazard)" strokeWidth="7" />
      <g stroke="var(--hazard)" strokeWidth="3">
        <path d="M418 258l24 24M442 258l-24 24" />
      </g>
      <text x="452" y="276" fill="var(--hazard)" fontSize="17" fontWeight="700">
        NH-12 Bridge
      </text>
      <path d="M150 60L250 80L330 62L430 116" fill="none" stroke="var(--route)" strokeWidth="3" strokeDasharray="2 7" strokeLinecap="round" />
      <circle cx="150" cy="60" r="9" fill="var(--route)" />
      <circle cx="760" cy="72" r="11" fill="var(--waiting)" stroke="var(--hazard)" strokeWidth="3" />
    </svg>
  );
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
    <div className="login">
      <div className="login-art">
        <ChartArt />
        <div className="title">
          <h1>ReliefNet</h1>
          <p>
            During a flood, help requests arrive as messy messages from every direction. ReliefNet's agents share one
            memory, so each family is understood once, merged once and reached once.
          </p>
        </div>
      </div>
      <main className="login-main">
        {mode === "clerk" ? (
          <>
            <Show when="signed-out">
              <h2>Sign in to your relief organisation</h2>
              <SignIn routing="hash" />
            </Show>
            <Show when="signed-in">
              <h2>Choose your organisation</h2>
              <p>Each organisation has its own private memory. Pick the one you are working for today.</p>
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <OrganizationSwitcher hidePersonal afterSelectOrganizationUrl="/" afterCreateOrganizationUrl="/" />
                <UserButton />
              </div>
              {error && <p className="error">{error}</p>}
            </Show>
          </>
        ) : (
          <>
            <div>
              <h2>Who is working this shift?</h2>
              <p className="login-foot">
                Demo sign-in: choose a person to see ReliefNet as they do. Coordinators get the operations chart;
                volunteers get the field app. Production deployments use Clerk accounts and organisations.
              </p>
            </div>
            <div className="who-list">
              {[...byOrg.entries()].map(([org, list]) => (
                <section key={org} className="who-org" aria-label={org}>
                  <h3>{org}</h3>
                  {list.map((u) => (
                    <button
                      key={u.id}
                      type="button"
                      className="who"
                      onClick={() => signInDev({ id: u.id, name: u.name, org: u.org, role: u.role })}
                    >
                      <b>{u.name}</b>
                      <span className={`chip ${u.role === "volunteer" ? "s-ASSIGNED" : "s-TRIAGED"}`}>
                        {u.role === "volunteer" ? "Field app" : "Operations"}
                      </span>
                      <span>{u.role === "volunteer" ? `Volunteer, ${u.team}` : u.role === "admin" ? "Admin, can reset demo data" : "Shift coordinator"}</span>
                    </button>
                  ))}
                </section>
              ))}
              {users === null && <p>Loading people…</p>}
            </div>
            {error && <p className="error">{error}</p>}
          </>
        )}
        <p className="login-foot">
          Need help, not a sign-in? <Link to="/help">Ask for flood help here</Link>.
        </p>
      </main>
    </div>
  );
}
