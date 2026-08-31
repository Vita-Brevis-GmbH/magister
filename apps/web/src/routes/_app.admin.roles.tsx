import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import {
  useCreateRole,
  useDeleteRole,
  useRbacConfig,
  useRevokeRole,
  useRoles,
  useSchools,
  useSetRoleCapabilities,
  useSetUserRoles,
  useUsers,
} from "@/api/hooks";
import type { RbacRole, RoleAssignmentOut, RoleGrantRequest } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTerms } from "@/lib/useTerms";

export const Route = createFileRoute("/_app/admin/roles")({
  component: RolesPage,
});

/** i18n key for a capability value ("orgunit.manage" → rbac.cap_orgunit_manage). */
function capKey(cap: string): string {
  return `rbac.cap_${cap.replace(/\./g, "_")}`;
}

/** Display label for a role: built-ins are translated by key, custom by name. */
function useRoleLabel(): (role: Pick<RbacRole, "key" | "name" | "is_system">) => string {
  const { t } = useTranslation();
  return (role) =>
    role.is_system ? t(`admin.roles.role_${role.key}`, { defaultValue: role.name }) : role.name;
}

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

/** Map a role-grant failure to a specific i18n key so the operator sees which
 *  entity is missing (user vs org unit vs role) instead of a lumped message. */
function grantErrorKey(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "user_not_found") return "admin.roles.grant_user_not_found";
    if (err.code === "school_not_found") return "admin.roles.grant_school_not_found";
    if (err.code === "role_not_found") return "admin.roles.grant_role_not_found";
    if (err.status === 422) return "admin.roles.grant_invalid";
  }
  return "errors.generic";
}

function RolesPage(): JSX.Element {
  const { t } = useTranslation();
  const terms = useTerms();
  const unitVars = { unit: terms.unit, unit_plural: terms.unit_plural };
  const roles = useRoles();

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold">{t("admin.roles.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("admin.roles.description")}</p>
      </header>

      <RightsMatrix />

      <AssignCard />

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
                    <th className="py-2 pr-4">{t("admin.roles.col_school", unitVars)}</th>
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

function RightsMatrix(): JSX.Element {
  const { t } = useTranslation();
  const cfg = useRbacConfig();
  const setCaps = useSetRoleCapabilities();
  const deleteRole = useDeleteRole();
  const roleLabel = useRoleLabel();

  const toggle = (role: RbacRole, cap: string, on: boolean): void => {
    const next = on ? [...role.capabilities, cap] : role.capabilities.filter((c) => c !== cap);
    setCaps.mutate({ key: role.key, capabilities: Array.from(new Set(next)) });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("rbac.matrix_title")}</CardTitle>
        <CardDescription>{t("rbac.matrix_desc")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {cfg.isLoading ? (
          <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : cfg.isError || !cfg.data ? (
          <p className="text-sm text-destructive">{t("errors.generic")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-4">{t("rbac.col_role")}</th>
                  {cfg.data.capabilities.map((cap) => (
                    <th key={cap} className="px-2 py-2 text-center font-medium">
                      {t(capKey(cap), { defaultValue: cap })}
                    </th>
                  ))}
                  <th className="py-2 pl-2" />
                </tr>
              </thead>
              <tbody>
                {cfg.data.roles.map((role) => (
                  <tr key={role.key} className="border-b last:border-0">
                    <td className="py-2 pr-4">
                      <div className="font-medium">{roleLabel(role)}</div>
                      <div className="text-xs text-muted-foreground">
                        {role.is_admin
                          ? t("rbac.role_admin_hint")
                          : role.is_derived
                            ? t("rbac.role_derived_hint")
                            : role.is_system
                              ? t("rbac.role_system_hint")
                              : t("rbac.role_custom_hint")}
                      </div>
                    </td>
                    {cfg.data.capabilities.map((cap) => {
                      const checked = role.is_admin || role.capabilities.includes(cap);
                      return (
                        <td key={cap} className="px-2 py-2 text-center">
                          <input
                            type="checkbox"
                            aria-label={`${role.key}:${cap}`}
                            checked={checked}
                            disabled={!role.editable || setCaps.isPending}
                            onChange={(e) => toggle(role, cap, e.target.checked)}
                          />
                        </td>
                      );
                    })}
                    <td className="py-2 pl-2 text-right">
                      {role.deletable ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={deleteRole.isPending}
                          onClick={() => deleteRole.mutate(role.key)}
                        >
                          {t("rbac.delete_role")}
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {setCaps.isError ? <p className="text-sm text-destructive">{t("errors.generic")}</p> : null}
        <CreateRoleForm />
      </CardContent>
    </Card>
  );
}

/** machine-key slug from a display name: lowercase, ascii, _-separated. */
function slugifyRoleKey(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 32);
}

function CreateRoleForm(): JSX.Element {
  const { t } = useTranslation();
  const create = useCreateRole();
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  // The technical key is auto-derived from the name until the admin edits it
  // by hand, so simply typing a name is enough to enable "Rolle anlegen".
  const [keyTouched, setKeyTouched] = useState(false);
  const effectiveKey = keyTouched ? key : slugifyRoleKey(name);

  const keyOk = /^[a-z][a-z0-9_-]*$/.test(effectiveKey) && effectiveKey.length >= 2;
  const canCreate = keyOk && name.trim().length > 0;

  function reset(): void {
    setKey("");
    setName("");
    setKeyTouched(false);
  }

  return (
    <div className="space-y-2 border-t pt-4">
      <h3 className="text-sm font-medium">{t("rbac.add_role_title")}</h3>
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="new-role-name">{t("rbac.role_name")}</Label>
          <Input
            id="new-role-name"
            className="w-56"
            placeholder={t("rbac.role_name_placeholder")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="new-role-key">{t("rbac.role_key")}</Label>
          <Input
            id="new-role-key"
            className="w-40"
            placeholder="koordinator"
            value={effectiveKey}
            onChange={(e) => {
              setKeyTouched(true);
              setKey(e.target.value);
            }}
          />
        </div>
        <Button
          type="button"
          disabled={!canCreate || create.isPending}
          onClick={() =>
            create.mutate({ key: effectiveKey, name: name.trim() }, { onSuccess: reset })
          }
        >
          {t("rbac.add_role_button")}
        </Button>
      </div>
      <p
        className={
          effectiveKey.length > 0 && !keyOk
            ? "text-xs text-amber-600"
            : "text-xs text-muted-foreground"
        }
      >
        {t("rbac.role_key_hint")}
      </p>
      {create.isError ? (
        <p className="text-sm text-destructive">
          {create.error instanceof ApiError && create.error.status === 409
            ? t("rbac.role_exists")
            : t("errors.generic")}
        </p>
      ) : null}
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
      <td className="py-2 pr-4">{t(`admin.roles.role_${a.role}`, { defaultValue: a.role })}</td>
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

/** Membership key for one (role, org-unit) pair. Role keys match
 *  `[a-z][a-z0-9_-]*`, so "::" can never collide with a role key. */
function scopeKey(role: string, schoolId: number | null): string {
  return `${role}::${schoolId ?? "null"}`;
}

function sameSet(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false;
  for (const k of a) if (!b.has(k)) return false;
  return true;
}

/** Per-person role editor: pick a person, then tick which assignable roles they
 *  hold — and for scoped roles, at which org units (multiple-choice per site).
 *  One "Speichern" diffs the ticks against the current grants and applies them
 *  transactionally, so several roles across several sites go in one action. */
function AssignCard(): JSX.Element {
  const { t } = useTranslation();
  const terms = useTerms();
  const unitVars = { unit: terms.unit, unit_plural: terms.unit_plural };
  const schools = useSchools();
  const cfg = useRbacConfig();
  const roles = useRoles();
  const setUserRoles = useSetUserRoles();
  const roleLabel = useRoleLabel();

  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<{ guid: string; label: string } | null>(null);
  // Pending edits; null means "unchanged, mirror the person's current grants".
  const [draft, setDraft] = useState<Set<string> | null>(null);

  // Assignable roles: everything except derived roles (kl).
  const assignable = useMemo(
    () => (cfg.data?.roles ?? []).filter((r) => !r.is_derived),
    [cfg.data?.roles],
  );
  const schoolList = schools.data ?? [];

  // The person's current active grants, as a membership set (assignable only).
  const current = useMemo(() => {
    const keys = new Set<string>();
    if (!selected) return keys;
    const assignableKeys = new Set(assignable.map((r) => r.key));
    for (const a of roles.data ?? []) {
      if (a.ad_object_guid === selected.guid && assignableKeys.has(a.role)) {
        keys.add(scopeKey(a.role, a.school_id));
      }
    }
    return keys;
  }, [selected, roles.data, assignable]);

  const shown = draft ?? current;
  const ready = roles.isSuccess && !!cfg.data;
  const dirty = draft !== null && !sameSet(draft, current);

  function reset(): void {
    setSelected(null);
    setSearch("");
    setDraft(null);
  }

  function toggle(role: string, schoolId: number | null, on: boolean): void {
    setDraft((prev) => {
      const next = new Set(prev ?? current);
      const k = scopeKey(role, schoolId);
      if (on) next.add(k);
      else next.delete(k);
      return next;
    });
  }

  function submit(): void {
    if (!selected) return;
    const assignments: RoleGrantRequest[] = [];
    for (const r of assignable) {
      if (r.is_admin) {
        if (shown.has(scopeKey(r.key, null))) assignments.push({ role: r.key, school_id: null });
      } else {
        for (const s of schoolList) {
          if (shown.has(scopeKey(r.key, s.id))) assignments.push({ role: r.key, school_id: s.id });
        }
      }
    }
    setUserRoles.mutate(
      { guid: selected.guid, body: { assignments } },
      { onSuccess: () => setDraft(null) },
    );
  }

  const results = useUsers(search.trim().length >= 2 ? { search: search.trim(), limit: 8 } : {});
  const showResults = search.trim().length >= 2 && !selected;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("admin.roles.grant_title")}</CardTitle>
        <CardDescription>{t("admin.roles.grant_desc", unitVars)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <Label htmlFor="role-user-search">{t("admin.roles.user")}</Label>
          {selected ? (
            <div className="flex items-center gap-2">
              <span className="rounded-md border bg-muted px-2 py-1 text-sm">{selected.label}</span>
              <Button type="button" variant="ghost" size="sm" onClick={reset}>
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

        {selected ? (
          !ready ? (
            <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
          ) : assignable.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("admin.roles.no_roles")}</p>
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                {t("admin.roles.assign_hint", unitVars)}
              </p>
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="px-3 py-2">{t("admin.roles.col_role")}</th>
                      <th className="px-3 py-2">{t("admin.roles.col_school", unitVars)}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {assignable.map((r) => (
                      <tr key={r.key} className="border-b last:border-0 align-top">
                        <td className="px-3 py-2 font-medium">{roleLabel(r)}</td>
                        <td className="px-3 py-2">
                          {r.is_admin ? (
                            <label className="inline-flex items-center gap-2">
                              <input
                                type="checkbox"
                                checked={shown.has(scopeKey(r.key, null))}
                                disabled={setUserRoles.isPending}
                                onChange={(e) => toggle(r.key, null, e.target.checked)}
                              />
                              <span>{t("admin.roles.cross_school", unitVars)}</span>
                            </label>
                          ) : schoolList.length === 0 ? (
                            <span className="text-xs text-muted-foreground">
                              {t("admin.roles.no_schools", unitVars)}
                            </span>
                          ) : (
                            <div className="flex flex-wrap gap-x-4 gap-y-1">
                              {schoolList.map((s) => (
                                <label key={s.id} className="inline-flex items-center gap-2">
                                  <input
                                    type="checkbox"
                                    checked={shown.has(scopeKey(r.key, s.id))}
                                    disabled={setUserRoles.isPending}
                                    onChange={(e) => toggle(r.key, s.id, e.target.checked)}
                                  />
                                  <span>{s.name}</span>
                                </label>
                              ))}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {setUserRoles.isError ? (
                <p className="text-sm text-destructive">
                  {t(grantErrorKey(setUserRoles.error), unitVars)}
                </p>
              ) : setUserRoles.isSuccess && !dirty ? (
                <p className="text-sm text-emerald-700">{t("admin.roles.grant_ok")}</p>
              ) : null}

              <Button type="button" disabled={!dirty || setUserRoles.isPending} onClick={submit}>
                {setUserRoles.isPending ? t("common.loading") : t("admin.roles.save")}
              </Button>
            </div>
          )
        ) : (
          <p className="text-sm text-muted-foreground">{t("admin.roles.select_user_first")}</p>
        )}
      </CardContent>
    </Card>
  );
}
