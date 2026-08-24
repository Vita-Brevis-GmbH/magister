import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import {
  useAddDepartmentMember,
  useAssignManager,
  useDepartment,
  useDepartmentManagers,
  useDepartmentMembers,
  useRemoveDepartmentMember,
  useRevokeManager,
} from "@/api/hooks";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_app/departments/$departmentId")({
  component: DepartmentDetailPage,
});

function DepartmentDetailPage(): JSX.Element {
  const { t } = useTranslation();
  const { departmentId } = Route.useParams();
  const id = Number(departmentId);

  const dep = useDepartment(id);
  const members = useDepartmentMembers(id);
  const managers = useDepartmentManagers(id);
  const addMember = useAddDepartmentMember(id);
  const removeMember = useRemoveDepartmentMember(id);
  const assignManager = useAssignManager(id);
  const revokeManager = useRevokeManager(id);

  const [memberGuid, setMemberGuid] = useState("");
  const [managerGuid, setManagerGuid] = useState("");
  const [managerRole, setManagerRole] = useState<"lead" | "deputy">("lead");

  const submitMember = (e: FormEvent): void => {
    e.preventDefault();
    if (!memberGuid.trim()) return;
    addMember.mutate({ ad_object_guid: memberGuid.trim() }, { onSuccess: () => setMemberGuid("") });
  };

  const submitManager = (e: FormEvent): void => {
    e.preventDefault();
    if (!managerGuid.trim()) return;
    assignManager.mutate(
      { ad_object_guid: managerGuid.trim(), role: managerRole },
      { onSuccess: () => setManagerGuid("") },
    );
  };

  return (
    <div className="space-y-6">
      <header>
        <Link to="/departments" className="text-xs text-muted-foreground hover:underline">
          ← {t("departments.title")}
        </Link>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">
          {dep.data?.name ?? t("departments.title")}
        </h1>
        {dep.data?.kuerzel ? (
          <p className="text-sm text-muted-foreground">{dep.data.kuerzel}</p>
        ) : null}
      </header>

      <section className="rounded-md border bg-card">
        <h2 className="border-b px-4 py-2 text-sm font-medium">{t("departments.members")}</h2>
        <form onSubmit={submitMember} className="flex flex-wrap items-end gap-3 border-b px-4 py-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              {t("departments.member_guid")}
            </span>
            <input
              value={memberGuid}
              onChange={(e) => setMemberGuid(e.target.value)}
              placeholder="objectGUID"
              className="h-9 w-80 rounded-md border border-input bg-background px-3 text-sm"
            />
          </label>
          <Button type="submit" size="sm" disabled={addMember.isPending || !memberGuid.trim()}>
            {t("departments.add_member")}
          </Button>
        </form>
        <ul className="divide-y">
          {members.data && members.data.length > 0 ? (
            members.data.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-4 px-4 py-2">
                <code className="text-xs">{m.ad_object_guid}</code>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={removeMember.isPending}
                  onClick={() => removeMember.mutate(m.id)}
                >
                  {t("departments.remove")}
                </Button>
              </li>
            ))
          ) : (
            <li className="px-4 py-3 text-sm text-muted-foreground">
              {t("departments.no_members")}
            </li>
          )}
        </ul>
      </section>

      <section className="rounded-md border bg-card">
        <h2 className="border-b px-4 py-2 text-sm font-medium">{t("departments.managers")}</h2>
        <form
          onSubmit={submitManager}
          className="flex flex-wrap items-end gap-3 border-b px-4 py-3"
        >
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              {t("departments.manager_guid")}
            </span>
            <input
              value={managerGuid}
              onChange={(e) => setManagerGuid(e.target.value)}
              placeholder="objectGUID"
              className="h-9 w-80 rounded-md border border-input bg-background px-3 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              {t("departments.role")}
            </span>
            <select
              value={managerRole}
              onChange={(e) => setManagerRole(e.target.value as "lead" | "deputy")}
              className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="lead">{t("departments.role_lead")}</option>
              <option value="deputy">{t("departments.role_deputy")}</option>
            </select>
          </label>
          <Button type="submit" size="sm" disabled={assignManager.isPending || !managerGuid.trim()}>
            {t("departments.assign_manager")}
          </Button>
        </form>
        <ul className="divide-y">
          {managers.data && managers.data.length > 0 ? (
            managers.data.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-4 px-4 py-2">
                <span className="text-sm">
                  <code className="text-xs">{m.ad_object_guid}</code>
                  <span className="ml-2 text-xs text-muted-foreground">
                    {t(`departments.role_${m.role}`, { defaultValue: m.role })}
                  </span>
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={revokeManager.isPending}
                  onClick={() => revokeManager.mutate(m.id)}
                >
                  {t("departments.remove")}
                </Button>
              </li>
            ))
          ) : (
            <li className="px-4 py-3 text-sm text-muted-foreground">
              {t("departments.no_managers")}
            </li>
          )}
        </ul>
      </section>
    </div>
  );
}
