import { describe, expect, it } from "vitest";

import { cleanOu, ouInUnit, ouValid } from "./ou";

describe("Ziel-OU", () => {
  it("räumt Leerzeichen um die Kommas weg", () => {
    expect(cleanOu(" OU=Sonstige , DC=schule,DC=local ")).toBe("OU=Sonstige,DC=schule,DC=local");
  });

  it("verlangt einen vollständigen Pfad, leer ist erlaubt", () => {
    expect(ouValid("")).toBe(true);
    expect(ouValid("OU=Sonstige,DC=schule,DC=local")).toBe(true);
    expect(ouValid("Sonstige")).toBe(false);
    expect(ouValid("OU=Sonstige")).toBe(false);
  });

  it("erkennt die OU des Standorts am Kürzel", () => {
    expect(ouInUnit("OU=Gast,OU=A,DC=schule,DC=local", "a")).toBe(true);
    expect(ouInUnit("OU=Sonstige,DC=schule,DC=local", "A")).toBe(false);
  });
});
