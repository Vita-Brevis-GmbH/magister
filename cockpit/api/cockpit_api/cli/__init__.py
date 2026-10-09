"""Werkzeuge, die **nicht** auf dem Anwendungsserver laufen (ADR-0016 D2).

Wiederherstellen und Prüfen brauchen den privaten Backup-Schlüssel. Dass der
auf dem Anwendungsserver nie liegt, ist die Zusage aus ADR-0016 D2 — also
laufen diese Schritte dort, wo er liegt: auf dem Backup-Host. Die Konsole
nimmt nur das Ergebnis entgegen.

Deshalb sind es Kommandozeilenwerkzeuge und keine Endpunkte. Ein Endpunkt
wäre bequemer und würde bedeuten, dass ein übernommener Anwendungsserver alle
alten Sicherungen lesen kann.
"""
