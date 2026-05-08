import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";

import type { CurrentUserOut } from "@/api/types";

/**
 * Admin-only layout group. Rides on top of the parent `_app` layout (which
 * already loaded `me`); we only do the admin-gating here. The backend RBAC
 * is the source of truth — this guard is purely so non-admins don't see a
 * blank screen of access errors.
 */
export const Route = createFileRoute("/_app/admin")({
  beforeLoad: ({ context }) => {
    const me = (context as { me?: CurrentUserOut }).me;
    if (!me?.is_admin) {
      throw redirect({ to: "/" });
    }
  },
  component: AdminLayout,
});

function AdminLayout(): JSX.Element {
  return <Outlet />;
}
