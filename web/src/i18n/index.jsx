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
 * Theme is two-state and always stamps `data-theme`: the source design has no
 * system-preference path, App.css carries no `prefers-color-scheme` block, and the owner
 * took the design as drawn on this branch. The cost is real and is the reason this
 * paragraph exists rather than being deleted: a light-preference OS user lands in dark
 * with no auto option. Restoring auto means an "auto" state here *and* a media block in
 * App.css — one without the other is a toggle that reads the OS and cannot override it.
 */

const STRINGS = { en, zh }
const PrefsContext = createContext(null)

// Storage is optional, not assumed. `localStorage` throws SecurityError on access — not
// on write — where site data is blocked (Chrome's "block all cookies", a sandboxed
// iframe), and setItem can throw on quota. Both happen inside this provider, which is the
// outermost thing that runs, so an unguarded access blanks the app rather than losing a
// preference. Falling back to the default is the right degradation: the session works,
// the choice just does not survive a reload.
function read(key, allowed, fallback) {
  try {
    const v = localStorage.getItem(key)
    return allowed.includes(v) ? v : fallback
  } catch {
    return fallback
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Preferences do not persist in this browser. Nothing else changes.
  }
}

export function PrefsProvider({ children }) {
  const [locale, setLocale] = useState(() => read("pp-locale", ["en", "zh"], "en"))
  // The source design's theme model, adopted verbatim on the 1:1 branch: two states,
  // dark by default, an explicit attribute always set. The three-state auto mode (and
  // with it the prefers-color-scheme contract) was the adapted skin's; the design has
  // no system-preference path and the owner chose the design exactly as drawn.
  const [theme, setTheme] = useState(() => read("pp-theme", ["light", "dark"], "dark"))

  useEffect(() => {
    write("pp-locale", locale)
    document.documentElement.setAttribute("lang", locale === "zh" ? "zh-Hans" : "en")
  }, [locale])

  useEffect(() => {
    write("pp-theme", theme)
    document.documentElement.setAttribute("data-theme", theme)
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
