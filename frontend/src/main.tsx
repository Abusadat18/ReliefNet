import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useSession } from "./auth";
import { applyStoredTheme } from "./components/ThemeToggle";
import { Field } from "./pages/Field";
import { Help } from "./pages/Help";
import { Login } from "./pages/Login";
import { Ops } from "./pages/Ops";
import "./styles.css";

applyStoredTheme();

function Home() {
  const { me, loading } = useSession();
  if (loading) return <div className="boot" aria-busy="true" />;
  if (!me) return <Login />;
  return <Navigate to={me.role === "volunteer" ? "/field" : "/ops"} replace />;
}

function Guard({ need, children }: { need: "volunteer" | "coordinator"; children: JSX.Element }) {
  const { me, loading } = useSession();
  if (loading) return <div className="boot" aria-busy="true" />;
  if (!me) return <Navigate to="/" replace />;
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
