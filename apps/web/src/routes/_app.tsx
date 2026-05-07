import { createFileRoute, redirect } from "@tanstack/react-router";

import { apiFetch, ApiError } from "@/api/client";
import type { CurrentUserOut } from "@/api/types";
import { Layout } from "@/components/Layout";

/**
 * Authenticated layout group. Pre-fetches /auth/me; on 401 we redirect to
 * /login (which then sends the browser to the backend's OIDC handshake).
 */
export const Route = createFileRoute("/_app")({
  beforeLoad: async ({ context }) => {
    try {
      const me = await apiFetch<CurrentUserOut>("/auth/me");
      return { me };
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        throw redirect({ to: "/login" });
      }
      throw err;
    }
    void context;
  },
  component: Layout,
});
