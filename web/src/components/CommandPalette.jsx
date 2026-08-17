import { useEffect, useRef, useState } from "react"
import { Search } from "lucide-react"
import { usePrefs } from "@/i18n"
import { NAV_ITEMS } from "@/nav"

/**
 * The design's ⌘K palette, 1:1 — backdrop blur, sliding panel, keyboard navigation,
 * staggered rows, kbd footer. One substitution: the design hardcodes each row's
 * description ("21 / 36 credits"); here the caller passes `subs` — the same live
 * sub-lines the sidebar computes from real reads — so the palette states facts the
 * server just recomputed instead of a screenshot of one afternoon.
 *
 * Rows are the rail's own slots in the rail's own order (`@/nav`). This file kept a second
 * copy of that list until 2026-08-16 and had it in a different order from the sidebar, so
 * the same five entries came back differently depending on how they were opened.
 */
const ACTIONS = NAV_ITEMS

export default function CommandPalette({ open, onClose, onNavigate, subs }) {
  const { t } = usePrefs()
  const [query, setQuery] = useState("")
  const [focused, setFocused] = useState(0)
  const inputRef = useRef(null)

  const filtered = ACTIONS.filter((a) =>
    t(`nav.${a.id}`).toLowerCase().includes(query.toLowerCase()),
  )

  useEffect(() => {
    if (open) {
      setQuery("")
      setFocused(0)
      setTimeout(() => inputRef.current?.focus(), 60)
    }
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      // An IME drives Enter and the arrow keys itself while a candidate window is up:
      // the Enter that commits 拼音 would otherwise navigate and close the palette, so
      // Chinese could never be typed into it at all — in a build that ships a zh locale.
      // The chat composer guards the same way. keyCode 229 is the legacy signal for
      // engines that leave isComposing unset on the commit keystroke.
      if (e.isComposing || e.keyCode === 229) return
      if (e.key === "Escape") {
        onClose()
        return
      }
      if (e.key === "ArrowDown") {
        e.preventDefault()
        setFocused((f) => Math.min(f + 1, filtered.length - 1))
      }
      if (e.key === "ArrowUp") {
        e.preventDefault()
        setFocused((f) => Math.max(f - 1, 0))
      }
      if (e.key === "Enter") {
        const a = filtered[focused]
        if (a) {
          onNavigate(a.id)
          onClose()
        }
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, filtered, focused, onClose, onNavigate])

  if (!open) return null

  const kbd = (label) => (
    <kbd
      className="rounded px-1.5 py-0.5 text-[10px] font-medium"
      style={{
        background: "var(--color-surface-2)",
        color: "var(--color-ink-3)",
        fontFamily: "var(--font-mono)",
      }}
    >
      {label}
    </kbd>
  )

  return (
    <div
      className="fixed inset-0 flex items-start justify-center pt-[18vh]"
      style={{
        background: "rgba(0,0,0,0.45)",
        backdropFilter: "blur(6px)",
        zIndex: 9999,
        animation: "pp-cmd-bg 160ms ease both",
      }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-md overflow-hidden rounded-2xl shadow-2xl"
        style={{
          background: "var(--color-surface)",
          border: "1px solid var(--color-rail-strong)",
          animation: "pp-cmd-panel 200ms cubic-bezier(0.22,1,0.36,1) both",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div
          className="flex items-center gap-3 px-4 py-3.5"
          style={{ borderBottom: "1px solid var(--color-rail)" }}
        >
          <Search size={15} style={{ color: "var(--color-ink-3)", flexShrink: 0 }} />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setFocused(0)
            }}
            placeholder={t("palette.placeholder")}
            className="flex-1 bg-transparent text-[14px] outline-none"
            style={{ color: "var(--color-ink)" }}
          />
          {kbd("ESC")}
        </div>

        {/* Actions */}
        <div className="py-1.5">
          {filtered.map((action, i) => {
            const Icon = action.icon
            const active = i === focused
            return (
              <button
                key={action.id}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-all"
                style={{
                  background: active ? "var(--color-violet-muted)" : "transparent",
                  animation: `pp-slide-up 200ms cubic-bezier(0.22,1,0.36,1) ${i * 30}ms both`,
                }}
                onMouseEnter={() => setFocused(i)}
                onClick={() => {
                  onNavigate(action.id)
                  onClose()
                }}
              >
                <div
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
                  style={{
                    background: active ? "var(--color-violet-muted)" : "var(--color-surface-2)",
                  }}
                >
                  <Icon
                    size={14}
                    style={{ color: active ? "var(--color-violet-light)" : "var(--color-ink-3)" }}
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <div
                    className="text-[13px] font-medium"
                    style={{ color: active ? "var(--color-ink)" : "var(--color-ink-2)" }}
                  >
                    {t(`nav.${action.id}`)}
                  </div>
                  <div className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
                    {subs?.[action.id] ?? t(`nav.${action.id}.sub`)}
                  </div>
                </div>
                {active ? kbd("↵") : null}
              </button>
            )
          })}
        </div>

        {/* Footer */}
        <div
          className="flex items-center gap-4 px-4 py-2"
          style={{ borderTop: "1px solid var(--color-rail)" }}
        >
          {[
            ["↑↓", t("palette.navigate")],
            ["↵", t("palette.go")],
            ["esc", t("palette.close")],
          ].map(([key, label]) => (
            <div key={key} className="flex items-center gap-1.5">
              {kbd(key)}
              <span className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
                {label}
              </span>
            </div>
          ))}
          <div className="ml-auto flex items-center gap-1.5">{kbd("⌘K")}</div>
        </div>
      </div>
    </div>
  )
}
