import { describe, expect, it } from "vitest";

import { customerPortalUrl } from "./customerPortal";

describe("customerPortalUrl", () => {
  it("unter <kunde>-um.<domain>: die Startseite <kunde>.<domain>", () => {
    expect(customerPortalUrl("kunde-a-um.mgmt.example.ch")).toBe("https://kunde-a.mgmt.example.ch");
    expect(customerPortalUrl("vb-um.example.ch")).toBe("https://vb.example.ch");
    // Gross/klein und der Punkt am Ende ändern nichts
    expect(customerPortalUrl("Kunde-A-UM.Mgmt.Example.CH.")).toBe(
      "https://kunde-a.mgmt.example.ch",
    );
  });

  it.each([
    "magister.example.ch", // eigene Installation
    "localhost",
    "kunde-a.mgmt.example.ch", // die Startseite selbst
    "kunde-a-doc.mgmt.example.ch",
    "um.example.ch",
    "-um.example.ch", // ohne Kurzname
    "kunde-a-um.ch", // Domain mit nur einem Label
    "kunde-a-um", // ohne Domain
    "kunde-a-um.mgmt..example.ch",
    "kunde-a-um.mgmt.example.ch/x",
    "kunde_a-um.example.ch", // kein DNS-Label
    "start-um.example.ch", // reserviert im Front-Proxy
    "kunde-nb-um.example.ch", // Endung eines Werkzeugs
    "kunde-a-um-x.example.ch",
    "",
  ])("sonst kein Link: %s", (host) => {
    expect(customerPortalUrl(host)).toBeNull();
  });
});
