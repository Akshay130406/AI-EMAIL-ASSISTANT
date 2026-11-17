import { afterEach, describe, expect, it, vi } from "vitest";
import { APIError, setCsrfToken, syncGmail } from "./api";

const csrfFailure = () => new Response(
  JSON.stringify({ detail: "CSRF validation failed" }),
  { status: 403, headers: { "Content-Type": "application/json" } },
);

describe("API CSRF recovery", () => {
  afterEach(() => {
    setCsrfToken(null);
    vi.unstubAllGlobals();
  });

  it("refreshes a stale session CSRF token and retries a rejected sync once", async () => {
    setCsrfToken("stale-token");
    const sentTokens: (string | null)[] = [];
    const responses = [
      csrfFailure(),
      new Response(JSON.stringify({ csrf_token: "fresh-token" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
      new Response(JSON.stringify({ synced: 3, incremental: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ];
    const fetchMock = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
      sentTokens.push(new Headers(init?.headers).get("X-CSRF-Token"));
      return Promise.resolve(responses.shift()!);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(syncGmail()).resolves.toEqual({ synced: 3, incremental: false });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(sentTokens).toEqual(["stale-token", null, "fresh-token"]);
  });

  it("does not retry unrelated forbidden responses", async () => {
    setCsrfToken("csrf-token");
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "Gmail access denied" }),
      { status: 403, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);

    await expect(syncGmail()).rejects.toMatchObject<Partial<APIError>>({
      message: "Gmail access denied",
      status: 403,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
