/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import i18n from "@/i18n";

import { CustomerPortalLink } from "./CustomerPortalLink";

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

describe("CustomerPortalLink", () => {
  it("unter <kunde>-um.<domain>: Kundenportal im selben Tab", () => {
    render(<CustomerPortalLink hostname="kunde-a-um.mgmt.example.ch" />);
    const link = screen.getByRole("link", { name: "Kundenportal" });
    expect(link.getAttribute("href")).toBe("https://kunde-a.mgmt.example.ch");
    expect(link.getAttribute("target")).toBeNull();
    expect(link.getAttribute("title")).toBe("Zur Startseite des Kundenportals");
  });

  it("unter einem anderen Namen kein Link", () => {
    const { container } = render(<CustomerPortalLink hostname="magister.example.ch" />);
    expect(container.innerHTML).toBe("");
  });

  it("in der Sprache des Benutzers", async () => {
    await i18n.changeLanguage("fr");
    try {
      const { unmount } = render(<CustomerPortalLink hostname="kunde-a-um.mgmt.example.ch" />);
      expect(screen.getByRole("link", { name: "Portail client" })).toBeInTheDocument();
      unmount(); // vor dem Zurückschalten der Sprache
    } finally {
      await i18n.changeLanguage("de");
    }
  });
});
