import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useMyStudents } from "@/api/hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const Route = createFileRoute("/_app/my-students")({
  component: MyStudentsPage,
});

function MyStudentsPage(): JSX.Element {
  const { t } = useTranslation();
  const q = useMyStudents();

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-serif text-2xl font-semibold">{t("my_students.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("my_students.intro")}</p>
      </header>

      {q.isLoading ? (
        <p>{t("common.loading")}</p>
      ) : q.isError ? (
        <p className="text-destructive">{t("errors.generic")}</p>
      ) : (q.data?.classes ?? []).length === 0 ? (
        <p className="text-muted-foreground">{t("my_students.empty")}</p>
      ) : (
        (q.data?.classes ?? []).map((c) => (
          <Card key={c.class_id}>
            <CardHeader>
              <CardTitle className="text-base">
                {c.name}
                {c.kuerzel ? ` (${c.kuerzel})` : ""}
              </CardTitle>
              <CardDescription>
                {t("my_students.count", { count: c.students.length })}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {c.students.length === 0 ? (
                <p className="text-muted-foreground">{t("my_students.empty_class")}</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("classes.student")}</TableHead>
                      <TableHead>{t("users.field.upn")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {c.students.map((s) => (
                      <TableRow key={s.ad_object_guid}>
                        <TableCell className="font-medium">
                          {s.display_name ?? s.upn ?? s.ad_object_guid}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{s.upn ?? "–"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}
