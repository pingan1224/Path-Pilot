import { useEffect, useState } from "react"
import { api } from "@/api"

/**
 * Debounced catalogue search, shared by the record editor and the mission's add-a-course
 * field.
 *
 * It is a hook rather than a component because the two callers need the same lookup and
 * genuinely different result rows — the planner offers three states to file a course
 * under, the mission offers one Add — so sharing the markup would mean a prop that only
 * switches between two layouts.
 *
 * A failed search is swallowed on purpose: both callers keep a plain code field beside
 * this, so search being down costs autocomplete, not the ability to add a course.
 */
export function useCourseSearch({ limit = 8, minLength = 2 } = {}) {
  const [query, setQuery] = useState("")
  const [results, setResults] = useState([])

  useEffect(() => {
    if (query.trim().length < minLength) {
      setResults([])
      return undefined
    }
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const found = await api.catalogSearch(query)
        if (!cancelled) setResults(found.slice(0, limit))
      } catch {
        /* non-fatal — the manual code field still works */
      }
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query, limit, minLength])

  function clear() {
    setQuery("")
    setResults([])
  }

  return { query, setQuery, results, clear }
}
