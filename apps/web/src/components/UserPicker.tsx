import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useUsers } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { userLabel } from "@/lib/userDisplay";

export interface PickedUser {
  guid: string;
  label: string;
}

/**
 * Search-and-pick a user by name/UPN. Controlled: the parent owns the selection
 * so it can drive an "add" action. Replaces raw objectGUID inputs (#9).
 */
export function UserPicker({
  value,
  onChange,
  placeholder,
}: {
  value: PickedUser | null;
  onChange: (u: PickedUser | null) => void;
  placeholder?: string;
}): JSX.Element {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const results = useUsers(search.trim().length >= 2 ? { search: search.trim(), limit: 8 } : {});
  const showResults = search.trim().length >= 2 && !value;

  if (value) {
    return (
      <div className="flex items-center gap-2">
        <span className="rounded-md border bg-muted px-2 py-1 text-sm">{value.label}</span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            onChange(null);
            setSearch("");
          }}
        >
          {t("user_picker.change")}
        </Button>
      </div>
    );
  }

  return (
    <div>
      <Input
        placeholder={placeholder ?? t("user_picker.placeholder")}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
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
                    onClick={() => onChange({ guid: u.ad_object_guid, label: userLabel(u) })}
                  >
                    <span className="font-medium">{userLabel(u)}</span>
                    <span className="text-xs text-muted-foreground">{u.upn}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-3 py-2 text-sm text-muted-foreground">{t("user_picker.no_matches")}</p>
          )}
        </div>
      ) : null}
    </div>
  );
}
