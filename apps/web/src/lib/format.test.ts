import { describe, expect, it } from "vitest";

import type { UserPreferencesOut } from "@/api/types";
import { makeFormatters } from "./format";

const ISO = "2026-08-12T12:00:00Z"; // noon UTC — stable day in any test-runner TZ

function prefs(over: Partial<UserPreferencesOut>): UserPreferencesOut {
  return { language: "de", region: "CH", date_format: "DD.MM.YYYY", time_format: "24h", ...over };
}

describe("makeFormatters.formatDate", () => {
  it("formats DD.MM.YYYY", () => {
    expect(makeFormatters(prefs({ date_format: "DD.MM.YYYY" })).formatDate(ISO)).toBe("12.08.2026");
  });
  it("formats YYYY-MM-DD", () => {
    expect(makeFormatters(prefs({ date_format: "YYYY-MM-DD" })).formatDate(ISO)).toBe("2026-08-12");
  });
  it("formats MM/DD/YYYY", () => {
    expect(makeFormatters(prefs({ date_format: "MM/DD/YYYY" })).formatDate(ISO)).toBe("08/12/2026");
  });
  it("passes through empty / invalid input", () => {
    const f = makeFormatters(prefs({}));
    expect(f.formatDate(null)).toBe("");
    expect(f.formatDate("not-a-date")).toBe("not-a-date");
  });
});

describe("makeFormatters.formatNumber", () => {
  it("uses the language-region locale grouping", () => {
    expect(makeFormatters(prefs({ language: "en", region: "US" })).formatNumber(1234567)).toBe(
      "1,234,567",
    );
    expect(makeFormatters(prefs({ language: "de", region: "DE" })).formatNumber(1234567)).toBe(
      "1.234.567",
    );
  });
});
