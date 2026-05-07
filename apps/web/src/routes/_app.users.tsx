import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useUsers, type UseUsersParams } from "@/api/hooks";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const Route = createFileRoute("/_app/users")({
  component: UsersPage,
});

type KindFilter = "all" | "teacher" | "student";

function UsersPage(): JSX.Element {
  const { t } = useTranslation();
  const [kind, setKind] = useState<KindFilter>("all");
  const [search, setSearch] = useState("");

  const params: UseUsersParams = {
    limit: 50,
    ...(kind !== "all" && { kind }),
    ...(search && { search }),
  };
  const q = useUsers(params);

  return (
    <div className="space-y-4">
      <h1 className="font-serif text-2xl font-semibold">{t("users.title")}</h1>

      <div className="flex flex-wrap items-center gap-3">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as KindFilter)}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
        >
          <option value="all">{t("users.filter_kind_all")}</option>
          <option value="teacher">{t("users.filter_kind_teacher")}</option>
          <option value="student">{t("users.filter_kind_student")}</option>
        </select>
        <input
          type="search"
          placeholder={t("users.search_placeholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-9 flex-1 rounded-md border border-input bg-background px-3 text-sm"
        />
        <span className="text-xs text-muted-foreground">
          {t("users.last_sync_at")}: {q.data?.last_sync_at ?? t("users.never_synced")}
        </span>
      </div>

      {q.isLoading ? (
        <p>{t("common.loading")}</p>
      ) : q.isError ? (
        <p className="text-destructive">{t("errors.generic")}</p>
      ) : q.data && q.data.items.length === 0 ? (
        <p className="text-muted-foreground">{t("users.empty")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>UPN</TableHead>
              <TableHead>{t("users.kind")}</TableHead>
              <TableHead>{t("users.enabled")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {q.data?.items.map((u) => (
              <TableRow key={u.ad_object_guid}>
                <TableCell className="font-medium">{u.upn}</TableCell>
                <TableCell>{u.kind}</TableCell>
                <TableCell>{u.enabled ? t("users.yes") : t("users.no")}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
