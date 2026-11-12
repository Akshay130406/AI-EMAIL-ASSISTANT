import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export default function ProtectedRoute() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <main className="grid min-h-screen place-items-center bg-canvas text-subtle" aria-live="polite">
        <div className="text-center">
          <div className="mx-auto mb-3 size-7 animate-spin rounded-full border-2 border-line border-t-accent" />
          <p className="text-sm">Restoring your secure session…</p>
        </div>
      </main>
    );
  }

  if (status !== "authenticated") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <Outlet />;
}
