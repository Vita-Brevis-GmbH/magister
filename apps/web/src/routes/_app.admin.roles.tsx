import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useGrantRole, useRevokeRole, useRoles, useSchools, useUsers } from "@/api/hooks";
import type { GrantableRole, RoleAssignmentOut } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/_app/admin/roles")({
  component: RolesPage,
});

const ROLES: GrantableRole[] = ["admin", "schulleitung", "smi"];

const selectClasses =
  "flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

function userLabel(a: {
  display_name: string | null;
  given_name: string | null;
  surname: string | null;
  upn: string | null;
}): string {
  if (a.display_name) return a.display_name;
  const name = [a.given_name, a.surname].filter(Boolean).join(" ");
  return name || a.upn || "?";
}

function RolesPage(): JSX.Element {
  const { t } = useTranslation();
  const roles = useRoles();

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold">{t("admin.roles.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("admin.roles.description")}</p>
      </header>

      <GrantCard />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("admin.roles.list_title")}</CardTitle>
          <CardDescription>{t("admin.roles.list_desc")}</CardDescription>
        </CardHeader>
        <CardContent>
          {roles.isLoading ? (
            <p>{t("common.loading")}</p>
          ) : roles.isError ? (
            <p className="text-destructive">{t("errors.generic")}</p>
          ) : roles.data && roles.data.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-2 pr-4">{t("admin.roles.col_user")}</th>
                    <th className="py-2 pr-4">{t("admin.roles.col_role")}</th>
                    <th className="py-2 pr-4">{t("admin.roles.col_school")}</th>
                    <th className="py-2 pr-4">{t("admin.roles.col_granted_by")}</th>
                    <th className="py-2 pr-4" />
                  </tr>
                </thead>
                <tbody>
                  {roles.data.map((a) => (
                    <RoleRow key={`${a.ad_object_guid}:${a.role}:${a.school_id ?? "null"}`} a={a} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("admin.roles.empty")}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function RoleRow({ a }: { a: RoleAssignmentOut }): JSX.Element {
  const { t } = useTranslation();
  const revoke = useRevokeRole();
  return (
    <tr className="border-b last:border-0">
      <td className="py-2 pr-4">
        <div className="font-medium">{userLabel(a)}</div>
        <div className="text-xs text-muted-foreground">{a.upn}</div>
      </td>
      <td className="py-2 pr-4">{t(`admin.roles.role_${a.role}`)}</td>
      <td className="py-2 pr-4">{a.school_name ?? "—"}</td>
      <td className="py-2 pr-4 text-xs text-muted-foreground">{a.granted_by ?? "—"}</td>
      <td className="py-2 pr-4 text-right">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={revoke.isPending}
          onClick={() =>
            revoke.mutate({ guid: a.ad_object_guid, role: a.role, school_id: a.school_id })
          }
        >
          {t("admin.roles.revoke")}
        </Button>
      </td>
    </tr>
  );
}

function GrantCard(): JSX.Element {
  const { t } = useTranslation();
  const schools = useSchools();
  const grant = useGrantRole();

  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<{ guid: string; label: string } | null>(null);
  const [role, setRole] = useState<GrantableRole>("schulleitung");
  const [schoolId, setSchoolId] = useState<number | "">("");

  const results = useUsers(search.trim().length >= 2 ? { search: search.trim(), limit: 8 } : {});
  const showResults = search.trim().length >= 2 && !selected;
  const needsSchool = role !== "admin";
  const canGrant = !!selected && (!needsSchool || schoolId !== "");

  function submit(): void {
    if (!selected) return;
    grant.mutate(
      {
        guid: selected.guid,
        body: { role, school_id: needsSchool ? Number(schoolId) : null },
      },
      {
        onSuccess: () => {
          setSelected(null);
          setSearch("");
          setSchoolId("");
        },
      },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("admin.roles.grant_title")}</CardTitle>
        <CardDescription>{t("admin.roles.grant_desc")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <Label htmlFor="role-user-search">{t("admin.roles.user")}</Label>
          {selected ? (
            <div className="flex items-center gap-2">
              <span className="rounded-md border bg-muted px-2 py-1 text-sm">{selected.label}</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSelected(null);
                  setSearch("");
                }}
              >
                {t("admin.roles.change_user")}
              </Button>
            </div>
          ) : (
            <Input
              id="role-user-search"
              placeholder={t("admin.roles.user_search_placeholder")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          )}
          {showResults ? (
            <div className="mt-1 rounded-md border">
              {results.isLoading ? (
                <p className="px-3 py-2 text-sm text-muted-foreground">{t("common.loading")}</p>
              ) : results.data && results.data.items.length > 0 ? (
                <ul className="max-h-56 overflow-y-auto text-sm">
                  {results.data.items.map((u) => (
                    <li key={u.ad_object_guid}>
                      <button
                        type="button"
                        className="flex w-full flex-col items-start px-3 py-1.5 text-left hover:bg-muted"
                        onClick={() => setSelected({ guid: u.ad_object_guid, label: userLabel(u) })}
                      >
                        <span className="font-medium">{userLabel(u)}</span>
                        <span className="text-xs text-muted-foreground">{u.upn}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="px-3 py-2 text-sm text-muted-foreground">
                  {t("admin.roles.no_matches")}
                </p>
              )}
            </div>
          ) : null}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="role-select">{t("admin.roles.col_role")}</Label>
            <select
              id="role-select"
              className={selectClasses}
              value={role}
              onChange={(e) => setRole(e.target.value as GrantableRole)}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(`admin.roles.role_${r}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="role-school">{t("admin.roles.col_school")}</Label>
            <select
              id="role-school"
              className={selectClasses}
              disabled={!needsSchool}
              value={needsSchool ? schoolId : ""}
              onChange={(e) => setSchoolId(e.target.value === "" ? "" : Number(e.target.value))}
            >
              <option value="">
                {needsSchool ? t("admin.roles.school_placeholder") : t("admin.roles.school_all")}
              </option>
              {(schools.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {grant.isError ? (
          <p className="text-sm text-destructive">
            {grant.error instanceof ApiError && grant.error.status === 404
              ? t("admin.roles.grant_not_found")
              : t("errors.generic")}
          </p>
        ) : grant.isSuccess ? (
          <p className="text-sm text-emerald-700">{t("admin.roles.grant_ok")}</p>
        ) : null}

        <Button type="button" disabled={!canGrant || grant.isPending} onClick={submit}>
          {grant.isPending ? t("common.loading") : t("admin.roles.grant_button")}
        </Button>
      </CardContent>
    </Card>
  );
}
