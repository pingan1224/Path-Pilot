import { createContext, useContext, useEffect, useMemo, useState } from "react"
import { en } from "./en"
import { zh } from "./zh"

/**
 * UI preferences: locale and theme, one provider. Both are presentation state with the
 * same lifecycle — read once from localStorage, applied to the document element, flipped
 * by a control in the shell — so they share a context rather than nesting two.
 *
 * Locale changes the UI chrome only. Server-sent content stays in English (see en.js);
 * `t()` resolves against the active dictionary and falls back to English so a missing
 * translation degrades to readable text, never to a raw key on screen.
 *
 * Theme is three-state, not two: `auto` removes the data-theme attribute so the
 * `prefers-color-scheme` media block in App.css decides — the palette's own contract is
 * that an explicit choice beats the OS preference *in both directions*, which requires
 * an explicit state for "no choice". A two-way toggle defaulting to dark would silently
 * disable the system preference, which is how the source design shipped and exactly what
 * this provider exists not to do.
 */

const STRINGS = { en, zh }
const PrefsContext = createContext(null)

function read(key, allowed, fallback) {
  const v = localStorage.getItem(key)
  return allowed.includes(v) ? v : fallback
}

export function PrefsProvider({ children }) {
  const [locale, setLocale] = useState(() => read("pp-locale", ["en", "zh"], "en"))
  const [theme, setTheme] = useState(() => read("pp-theme", ["auto", "light", "dark"], "auto"))

  useEffect(() => {
    localStorage.setItem("pp-locale", locale)
    document.documentElement.setAttribute("lang", locale === "zh" ? "zh-Hans" : "en")
  }, [locale])

  useEffect(() => {
    localStorage.setItem("pp-theme", theme)
    if (theme === "auto") document.documentElement.removeAttribute("data-theme")
    else document.documentElement.setAttribute("data-theme", theme)
  }, [theme])

  const value = useMemo(() => {
    const t = (key, vars) => {
      const entry = STRINGS[locale][key] ?? en[key]
      if (entry === undefined) return key
      if (typeof entry === "function") return entry(vars ?? {})
      if (!vars) return entry
      return entry.replace(/\{(\w+)\}/g, (m, name) =>
        vars[name] !== undefined ? String(vars[name]) : m,
      )
    }
    return { locale, setLocale, theme, setTheme, t }
  }, [locale, theme])

  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>
}

export function usePrefs() {
  const ctx = useContext(PrefsContext)
  if (!ctx) throw new Error("usePrefs must be used within PrefsProvider")
  return ctx
}
