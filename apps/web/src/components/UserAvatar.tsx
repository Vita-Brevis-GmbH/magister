import type { AdUserOut } from "@/api/types";
import { avatarPalette, initials } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

interface Props {
  user: Pick<AdUserOut, "ad_object_guid" | "given_name" | "surname" | "display_name" | "upn">;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const SIZE: Record<NonNullable<Props["size"]>, string> = {
  sm: "h-8 w-8 text-xs",
  md: "h-10 w-10 text-sm",
  lg: "h-14 w-14 text-base",
};

/** Small colored bubble with the user's initials. Color is deterministic
 *  per ad_object_guid so the same person always renders identically. */
export function UserAvatar({ user, size = "md", className }: Props): JSX.Element {
  const palette = avatarPalette(user.ad_object_guid);
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded-full font-semibold",
        SIZE[size],
        palette,
        className,
      )}
    >
      {initials(user)}
    </span>
  );
}
