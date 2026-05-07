import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useClasses } from "@/api/hooks";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const Route = createFileRoute("/_app/classes")({
  component: ClassesPage,
});

function ClassesPage(): JSX.Element {
  const { t } = useTranslation();
  const q = useClasses();

  if (q.isLoading) return <p>{t("common.loading")}</p>;
  if (q.isError) return <p className="text-destructive">{t("errors.generic")}</p>;
  const rows = q.data ?? [];

  return (
    <div className="space-y-4">
      <h1 className="font-serif text-2xl font-semibold">{t("classes.title")}</h1>
      {rows.length === 0 ? (
        <p className="text-muted-foreground">{t("classes.empty")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("classes.name")}</TableHead>
              <TableHead>{t("classes.kuerzel")}</TableHead>
              <TableHead>{t("classes.jahrgangsstufe")}</TableHead>
              <TableHead>{t("classes.school")}</TableHead>
              <TableHead>{t("classes.status")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-medium">{c.name}</TableCell>
                <TableCell>{c.kuerzel ?? "–"}</TableCell>
                <TableCell>{c.jahrgangsstufe}</TableCell>
                <TableCell>{c.school_id}</TableCell>
                <TableCell>
                  {c.status === "active"
                    ? t("classes.status_active")
                    : t("classes.status_archived")}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
