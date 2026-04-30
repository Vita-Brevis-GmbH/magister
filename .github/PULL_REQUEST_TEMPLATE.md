## Summary

<!-- 1–3 Sätze: was und warum. -->

## Linked Issue

Closes #

## Type

- [ ] feat
- [ ] fix
- [ ] chore
- [ ] docs
- [ ] refactor
- [ ] test
- [ ] ci / infra

## Test Plan

<!-- Wie wurde die Änderung getestet? Welche Edge-Cases? -->

- [ ] Backend: `uv run pytest` grün
- [ ] Frontend: `pnpm test && pnpm lint` grün
- [ ] Type-Check: `pyright` / `tsc --noEmit` grün
- [ ] Manuell gegen lokalen Compose-Stack getestet (falls UI / Workflow betroffen)

## Checklist

- [ ] Schul-Scope-Filter eingehalten (alle Queries `school_id`-gefiltert oder `# scope-bypass: <reason>`)
- [ ] Audit-Event bei Mutation (siehe `CLAUDE.md`)
- [ ] Keine Credentials / Passwörter / Tokens im Log
- [ ] i18n-Keys statt hardcoded Strings
- [ ] CHANGELOG / Roadmap aktualisiert (falls user-facing)
- [ ] OPEN QUESTIONS adressiert oder explizit als verbleibend dokumentiert
