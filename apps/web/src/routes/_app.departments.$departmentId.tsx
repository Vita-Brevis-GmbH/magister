import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useAddDepartmentMember,
  useAssignManager,
  useDepartment,
  useDepartmentManagers,
  useDepartmentMembers,
  useRemoveDepartmentMember,
  useRevokeManager,
  useSchools,
} from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { UserPicker, type PickedUser } from "@/components/UserPicker";
import { userLabel } from "@/lib/userDisplay";
import { useFormatters } from "@/lib/useFormatters";
import { useTerms } from "@/lib/useTerms";

export const Route = createFileRoute("/_app/departments/$departmentId")({
  component: DepartmentDetailPage,
});

/** Label for a member/manager row: name if enriched, else the raw GUID. */
function personLabel(m: {
  display_name: string | null;
  given_name: string | null;
  surname: string | null;
  upn: string | null;
  ad_object_guid: string;
}): string {
  const label = userLabel(m);
  return label === "?" ? m.ad_object_guid : label;
}

/** "CN=Lehrer,OU=…" → "Lehrer". */
function groupName(dn: string): string {
  return dn.startsWith("CN=") ? dn.slice(3).split(",")[0] : dn;
}

export function DepartmentDetailPage(): JSX.Element {
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
  const schools = useSchools();
  const terms = useTerms();
  const fmt = useFormatters();

  const [memberPick, setMemberPick] = useState<PickedUser | null>(null);
  const [managerPick, setManagerPick] = useState<PickedUser | null>(null);
  const [managerRole, setManagerRole] = useState<"lead" | "deputy">("lead");

  const submitMember = (): void => {
    if (!memberPick) return;
    addMember.mutate({ ad_object_guid: memberPick.guid }, { onSuccess: () => setMemberPick(null) });
  };

  const submitManager = (): void => {
    if (!managerPick) return;
    assignManager.mutate(
      { ad_object_guid: managerPick.guid, role: managerRole },
      { onSuccess: () => setManagerPick(null) },
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

      {dep.data ? (
        <section className="rounded-md border bg-card">
          <h2 className="border-b px-4 py-2 text-sm font-medium">{t("departments.overview")}</h2>
          <dl className="grid gap-x-6 gap-y-3 px-4 py-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted-foreground">{terms.unit}</dt>
              <dd>
                {dep.data.school_id === null
                  ? t("departments.global_label")
                  : (schools.data?.find((s) => s.id === dep.data?.school_id)?.name ??
                    dep.data.school_id)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("departments.members")}</dt>
              <dd>{t("departments.members_count", { count: members.data?.length ?? 0 })}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("departments.role_lead")}</dt>
              <dd>
                {(managers.data ?? [])
                  .filter((m) => m.role === "lead")
                  .map(personLabel)
                  .join(", ") || "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("departments.role_deputy")}</dt>
              <dd>
                {(managers.data ?? [])
                  .filter((m) => m.role === "deputy")
                  .map(personLabel)
                  .join(", ") || "—"}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs text-muted-foreground">{t("departments.groups_label")}</dt>
              <dd className="mt-1 flex flex-wrap gap-1">
                {dep.data.ad_groups.length > 0
                  ? dep.data.ad_groups.map((g) => (
                      <span
                        key={g}
                        title={g}
                        className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
                      >
                        {groupName(g)}
                      </span>
                    ))
                  : "—"}
              </dd>
            </div>
            {dep.data.details ? (
              <div className="sm:col-span-2">
                <dt className="text-xs text-muted-foreground">{t("departments.details_text")}</dt>
                <dd className="whitespace-pre-line">{dep.data.details}</dd>
              </div>
            ) : null}
            <div>
              <dt className="text-xs text-muted-foreground">{t("departments.created_at")}</dt>
              <dd>{fmt.formatDate(dep.data.created_at)}</dd>
            </div>
          </dl>
        </section>
      ) : null}

      <section className="rounded-md border bg-card">
        <h2 className="border-b px-4 py-2 text-sm font-medium">{t("departments.members")}</h2>
        <div className="flex flex-wrap items-end gap-3 border-b px-4 py-3">
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              {t("departments.member_user")}
            </span>
            <div className="w-80">
              <UserPicker value={memberPick} onChange={setMemberPick} />
            </div>
          </div>
          <Button
            type="button"
            size="sm"
            disabled={addMember.isPending || !memberPick}
            onClick={submitMember}
          >
            {t("departments.add_member")}
          </Button>
        </div>
        <ul className="divide-y">
          {members.data && members.data.length > 0 ? (
            members.data.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-4 px-4 py-2">
                <div className="flex flex-col leading-tight">
                  <span className="text-sm font-medium">{personLabel(m)}</span>
                  <span className="text-xs text-muted-foreground">
                    {[m.upn, t("departments.since", { date: fmt.formatDate(m.valid_from) })]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </div>
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
        <div className="flex flex-wrap items-end gap-3 border-b px-4 py-3">
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              {t("departments.manager_user")}
            </span>
            <div className="w-80">
              <UserPicker value={managerPick} onChange={setManagerPick} />
            </div>
          </div>
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
          <Button
            type="button"
            size="sm"
            disabled={assignManager.isPending || !managerPick}
            onClick={submitManager}
          >
            {t("departments.assign_manager")}
          </Button>
        </div>
        <ul className="divide-y">
          {managers.data && managers.data.length > 0 ? (
            managers.data.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-4 px-4 py-2">
                <div className="flex flex-col leading-tight">
                  <span className="text-sm font-medium">
                    {personLabel(m)}
                    <span className="ml-2 text-xs text-muted-foreground">
                      {t(`departments.role_${m.role}`, { defaultValue: m.role })}
                    </span>
                  </span>
                  {m.upn ? <span className="text-xs text-muted-foreground">{m.upn}</span> : null}
                </div>
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
