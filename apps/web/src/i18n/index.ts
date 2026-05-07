/**
 * i18next bootstrap.
 *
 * - DE is the source of truth and the default fallback.
 * - FR/IT are stubs; ``_meta._status`` flags them for native review.
 * - Browser language detection picks de/fr/it/en; everything else falls back to DE.
 */
import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import de from "./de.json";
import en from "./en.json";
import fr from "./fr.json";
import it from "./it.json";

export const SUPPORTED_LANGUAGES = ["de", "fr", "it", "en"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      de: { translation: de },
      en: { translation: en },
      fr: { translation: fr },
      it: { translation: it },
    },
    fallbackLng: "de",
    supportedLngs: SUPPORTED_LANGUAGES as readonly string[] as string[],
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false },
    detection: {
      order: ["querystring", "localStorage", "navigator", "htmlTag"],
      caches: ["localStorage"],
    },
  });

export default i18n;
