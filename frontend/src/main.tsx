import { StrictMode, type ReactElement } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, Boot, useSession } from "./auth";
import { applyStoredTheme } from "./components/ThemeToggle";
import { Field } from "./pages/Field";
import { Help } from "./pages/Help";
import { Landing } from "./pages/Landing";
import { Login } from "./pages/Login";
import { Ops } from "./pages/Ops";
import "./index.css";
import "./map.css";

applyStoredTheme();

function home(role: string) {
  return role === "volunteer" ? "/field" : "/ops";
}

/** The front page for visitors; people who are signed in go straight to their app. */
function Home() {
  const { me, loading } = useSession();
  if (loading) return <Boot />;
  if (!me) return <Landing />;
  return <Navigate to={home(me.role)} replace />;
}

function SignInPage() {
  const { me, loading } = useSession();
  if (loading) return <Boot />;
  if (me) return <Navigate to={home(me.role)} replace />;
  return <Login />;
}

function Guard({ need, children }: { need: "volunteer" | "coordinator"; children: ReactElement }) {
  const { me, loading } = useSession();
  if (loading) return <Boot />;
  if (!me) return <Navigate to="/login" replace />;
  if (need === "coordinator" && me.role === "volunteer") return <Navigate to="/field" replace />;
  return children;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/help" element={<Help />} />
        <Route path="/help/:org" element={<Help />} />
        <Route
          path="*"
          element={
            <AuthProvider>
              <Routes>
                <Route path="/" element={<Home />} />
                <Route path="/login" element={<SignInPage />} />
                <Route path="/about" element={<Landing />} />
                <Route
                  path="/ops"
                  element={
                    <Guard need="coordinator">
                      <Ops />
                    </Guard>
                  }
                />
                <Route
                  path="/field"
                  element={
                    <Guard need="volunteer">
                      <Field />
                    </Guard>
                  }
                />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </AuthProvider>
          }
        />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
