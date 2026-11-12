// ESLint für die Konsole.
//
// Es gab schon vorher ein `pnpm lint` in package.json — aber keine
// Konfiguration. Der Befehl brach also mit „no configuration found" ab, und
// niemand hat es gemerkt, weil ihn auch niemand aufgerufen hat. Ein
// Prüfschritt, der nie läuft, ist schlimmer als keiner: er steht in der
// Anleitung und suggeriert, dass geprüft wird.
//
// Bewusst knapp: die empfohlenen Regelsätze von ESLint und typescript-eslint,
// dazu die Hook-Regeln von React. Letztere sind der Grund, aus dem es hier
// überhaupt ein Lint braucht — ein bedingt aufgerufener Hook ist ein Fehler,
// den TypeScript nicht sieht und der sich erst als merkwürdiges Verhalten
// zeigt.

import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      globals: { ...globals.browser },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Eine ungenutzte Variable ist ein Hinweis, kein Weltuntergang — aber
      // ein mit `_` benannter Parameter ist Absicht.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
);
