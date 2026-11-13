import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./AuthContext";
import ProtectedRoute from "../components/ProtectedRoute";
import { logout, setCsrfToken } from "../services/api";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function renderProtectedRoute() {
  return render(
    <MemoryRouter initialEntries={["/private"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<p>Sign-in page</p>} />
          <Route element={<ProtectedRoute />}>
            <Route path="/private" element={<p>Protected dashboard</p>} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("authentication route state", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    cleanup();
    setCsrfToken(null);
    vi.unstubAllGlobals();
  });

  it("shows a loading state before redirecting an unauthenticated visitor", async () => {
    let resolveRequest!: (response: Response) => void;
    vi.mocked(fetch).mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveRequest = resolve;
      }),
    );

    renderProtectedRoute();
    expect(screen.getByText("Restoring your secure session…")).toBeTruthy();

    resolveRequest(jsonResponse(401, { detail: "Authentication required" }));
    expect(await screen.findByText("Sign-in page")).toBeTruthy();
    expect(screen.queryByText("Protected dashboard")).toBeNull();
  });

  it("restores a valid cookie session and renders the protected route", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(200, {
        user: {
          id: "user-1",
          email: "reader@example.test",
          display_name: "Test Reader",
          picture_url: null,
        },
        csrf_token: "in-memory-csrf-token",
      }),
    );

    renderProtectedRoute();
    expect(await screen.findByText("Protected dashboard")).toBeTruthy();
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/api/auth/me");
    expect(options).toMatchObject({ credentials: "include" });
  });

  it("sends the in-memory CSRF token on logout without exposing it in storage", async () => {
    setCsrfToken("csrf-test-token");
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      status: 204,
    } as Response);

    await logout();

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/api/auth/logout");
    expect(options?.credentials).toBe("include");
    expect(new Headers(options?.headers).get("X-CSRF-Token")).toBe("csrf-test-token");
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });
});
