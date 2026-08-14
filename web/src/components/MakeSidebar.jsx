import { useEffect, useLayoutEffect, useRef } from "react"
import {
  BarChart2,
  Calendar,
  CheckSquare,
  Compass,
  FileText,
  LogOut,
  MessageSquare,
  Moon,
  Sun,
} from "lucide-react"
import { usePrefs } from "@/i18n"

/**
 * The design's sidebar, 1:1: gradient logo tile, spotlight program chip, five nav items
 * with a travelling active marker, amber alert card, student chip, theme and language
 * toggles. Ported from the Make source with three substitutions, all of them
 * data-for-data rather than visual:
 *
 * - Every figure is real. The nav sub-lines and badges come from the same reads as the
 *   pages; the design's hardcoded "21 / 36 credits" and badge counts are replaced by
 *   the live values, absent when the data is absent.
 * - The amber footer card is the design's "Registration opens Nov 4" slot, and that
 *   fact only Albert knows — this product must not invent it. The card keeps the exact
 *   visual (label, bold line, sub line) and carries the mission instead: term, then
 *   blocked-or-step state. No mission, no card.
 * - A sign-out control exists because sessions are real; the design has none. It rides
 *   the student chip as a quiet icon button in the design's hover language.
 *
 * The active marker is one travelling 3px violet edge — no rounded tint block. The
 * design's source draws the block too, but wires it to the same ref as the edge, so it
 * never receives a position and never renders: what the design *ships* is the edge
 * alone. A first pass here "repaired" that bug and produced a visual the design never
 * had; 1:1 means the running appearance, so the repair was reverted.
 *
 * The design also gives every item its own indicator strip at the same left edge, in
 * the same violet. Coincident with the travelling one it can only be invisible or —
 * when the two are measured against different boxes — a doubled line. It is dropped
 * here and the travelling edge is the single marker.
 */

const NAV_ITEMS = [
  { id: "chat", icon: MessageSquare },
  { id: "planner", icon: BarChart2 },
  { id: "mission", icon: CheckSquare },
  { id: "intake", icon: FileText },
  { id: "sequence", icon: Calendar },
]

function useSpotlight(ref) {
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const onMove = (e) => {
      const r = el.getBoundingClientRect()
      el.style.setProperty("--mx", `${e.clientX - r.left}px`)
      el.style.setProperty("--my", `${e.clientY - r.top}px`)
    }
    el.addEventListener("mousemove", onMove)
    return () => el.removeEventListener("mousemove", onMove)
  }, [ref])
}

export default function MakeSidebar({
  view,
  onNavigate,
  me,
  onSignOut,
  program,
  programUnknown,
  mission,
  blockers,
  subs,
  onOpenProgram,
}) {
  const { theme, setTheme, locale, setLocale, t } = usePrefs()
  const chipRef = useRef(null)
  useSpotlight(chipRef)

  // The shared travelling marker (see the header comment for the repair).
  const itemRefs = useRef(new Map())
  const navRef = useRef(null)
  const sliderRef = useRef(null)
  const settledRef = useRef(false)
  useLayoutEffect(() => {
    const slider = sliderRef.current
    const nav = navRef.current
    if (!slider || !nav) return
    const el = itemRefs.current.get(view)
    if (!el) {
      slider.style.opacity = "0"
      return
    }
    slider.style.opacity = "1"
    const apply = () => {
      // Measured against the nav's own box, the way the design does it. `el.offsetTop`
      // is relative to the items' wrapper, while the marker is positioned on the nav —
      // and the nav's py-2 sits between them, so offsetTop put the marker 8px high and
      // it read as a second line beside each item's own strip.
      const offset = el.getBoundingClientRect().top - nav.getBoundingClientRect().top + nav.scrollTop
      slider.style.transform = `translateY(${offset}px)`
      slider.style.height = `${el.offsetHeight}px`
    }
    if (!settledRef.current) {
      slider.style.transition = "none"
      apply()
      settledRef.current = true
      void slider.offsetHeight
      slider.style.transition =
        "transform 240ms cubic-bezier(0.22,1,0.36,1), height 240ms cubic-bezier(0.22,1,0.36,1), opacity 160ms ease"
      return
    }
    apply()
  }, [view, locale])

  const initials = (me.full_name ?? "?")
    .split(" ")
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase()

  const missionBadge = blockers.length > 0 ? String(blockers.length) : null
  const done = mission ? mission.steps.filter((s) => s.state === "done").length : 0

  return (
    <aside
      className="flex w-full flex-none flex-col border-b transition-colors duration-200 md:max-h-none md:w-64 md:border-b-0"
      style={{ background: "var(--color-surface)", borderRight: "1px solid var(--color-rail)" }}
      aria-label={t("rail.aria")}
    >
      {/* Logo */}
      <div className="px-4 pt-5 pb-4" style={{ borderBottom: "1px solid var(--color-rail)" }}>
        <div className="flex items-center gap-2.5">
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl"
            style={{
              background: "linear-gradient(135deg, var(--color-violet) 0%, var(--color-violet-dim) 100%)",
            }}
          >
            <Compass size={15} className="text-white" aria-hidden="true" />
          </div>
          <div>
            <div
              className="text-[14px] font-semibold tracking-tight"
              style={{ color: "var(--color-ink)", fontFamily: "var(--font-display)" }}
            >
              {t("app.name")}
            </div>
            <div className="mt-0.5 text-[10px] leading-none" style={{ color: "var(--color-ink-3)" }}>
              {t("app.tagline")}
            </div>
          </div>
        </div>
      </div>

      {/* Program chip — the program surface; clicking opens the picker (real behaviour). */}
      <div className="px-4 py-3" style={{ borderBottom: "1px solid var(--color-rail)" }}>
        <button
          ref={chipRef}
          type="button"
          onClick={onOpenProgram}
          aria-current={view === "program" ? "page" : undefined}
          className="pp-spotlight w-full rounded-lg px-3 py-2 text-left"
          style={{
            background: "var(--color-surface-2)",
            border: `1px solid ${view === "program" ? "rgba(124,58,237,0.4)" : "var(--color-rail-strong)"}`,
          }}
        >
          <div className="mb-0.5 text-[10px] font-medium" style={{ color: "var(--color-ink-3)" }}>
            {t("rail.program.eyebrow")}
          </div>
          <div className="text-[12px] leading-snug font-medium" style={{ color: "var(--color-ink)" }}>
            {programUnknown
              ? t("rail.program.unset")
              : (program?.program_name ?? "…")}
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            {programUnknown ? (
              <span
                className="rounded px-1.5 py-0.5 text-[10px]"
                style={{ background: "var(--color-amber-muted)", color: "var(--color-amber)" }}
              >
                {t("rail.program.unset.action")}
              </span>
            ) : program ? (
              <span
                className="rounded px-1.5 py-0.5 text-[10px]"
                style={
                  program.is_encoded
                    ? { background: "var(--color-emerald-muted)", color: "var(--color-emerald)" }
                    : { background: "var(--color-amber-muted)", color: "var(--color-amber)" }
                }
              >
                {program.is_encoded ? t("rail.program.full") : t("rail.program.limited")}
              </span>
            ) : null}
          </div>
        </button>
      </div>

      {/* Nav */}
      <nav
        ref={navRef}
        className="relative min-h-0 flex-1 overflow-y-auto px-2 py-2"
        aria-label={t("nav.heading")}
      >
        {/* The travelling edge — the whole marker (see the header note). */}
        <div
          ref={sliderRef}
          aria-hidden="true"
          className="pointer-events-none absolute left-2"
          style={{ top: 0, height: 0 }}
        >
          <span
            className="absolute top-1/2 -translate-y-1/2 rounded-r-sm"
            style={{ left: 0, width: 3, height: "60%", background: "var(--color-violet)" }}
          />
        </div>

        <div className="relative space-y-0.5">
          {NAV_ITEMS.map(({ id, icon: Icon }) => {
            const active = view === id
            const badge = id === "mission" ? missionBadge : null
            return (
              <button
                key={id}
                ref={(el) => {
                  if (el) itemRefs.current.set(id, el)
                  else itemRefs.current.delete(id)
                }}
                type="button"
                onClick={() => onNavigate(id)}
                aria-current={active ? "page" : undefined}
                className="group relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left"
                style={{
                  transition: "transform 160ms ease-out",
                  background: "transparent",
                  border: "1px solid transparent",
                }}
                onMouseEnter={(e) => {
                  if (!active) e.currentTarget.style.transform = "translateX(2px)"
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = "translateX(0)"
                }}
              >
                <Icon
                  size={15}
                  aria-hidden="true"
                  style={{
                    color: active ? "var(--color-violet-light)" : "var(--color-ink-3)",
                    flexShrink: 0,
                    transform: active ? "scale(1.06)" : "scale(1)",
                    transition: "transform 180ms cubic-bezier(0.34,1.56,0.64,1), color 160ms ease",
                  }}
                />
                <div className="min-w-0 flex-1">
                  <div
                    className="text-[13px] leading-tight font-medium"
                    style={{
                      color: active ? "var(--color-ink)" : "var(--color-ink-2)",
                      transition: "color 160ms ease",
                    }}
                  >
                    {t(`nav.${id}`)}
                  </div>
                  <div className="mt-0.5 text-[11px] leading-tight" style={{ color: "var(--color-ink-3)" }}>
                    {subs?.[id] ?? t(`nav.${id}.sub`)}
                  </div>
                </div>
                {badge && !active ? (
                  <span
                    className="pp-badge-pop flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold"
                    style={{ background: "var(--color-amber)", color: "#000" }}
                  >
                    {badge}
                  </span>
                ) : null}
              </button>
            )
          })}
        </div>
      </nav>

      {/* Footer */}
      <div className="px-3 pb-3" style={{ borderTop: "1px solid var(--color-rail)", paddingTop: 12 }}>
        {/* The design's amber alert slot, carrying the mission (real) instead of a
            registration window (unknowable). Absent when there is no mission. */}
        {mission ? (
          <div
            className="mb-3 rounded-lg px-3 py-2"
            style={{ background: "var(--color-amber-muted)", border: "1px solid rgba(180,83,9,0.2)" }}
          >
            <div className="text-[10px] font-medium" style={{ color: "var(--color-amber)" }}>
              {t("sidebar.mission.label")}
            </div>
            <div className="text-[12px] font-semibold" style={{ color: "var(--color-amber)" }}>
              {mission.term}
            </div>
            <div className="mt-0.5 text-[10px]" style={{ color: "var(--color-ink-3)" }}>
              {blockers.length > 0
                ? t("nav.mission.sub.blocked", { count: blockers.length })
                : t("sidebar.mission.steps", { done, total: mission.steps.length })}
            </div>
          </div>
        ) : null}

        {/* Student chip + sign out */}
        <div className="mb-3 flex items-center gap-2.5 px-1 py-1.5">
          <div
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold text-white"
            style={{ background: "linear-gradient(135deg, var(--color-violet), var(--color-violet-dim))" }}
            aria-hidden="true"
          >
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[12px] font-medium" style={{ color: "var(--color-ink)" }}>
              {me.full_name}
            </div>
            <div className="truncate text-[10px]" style={{ color: "var(--color-ink-3)" }}>
              {me.student_number ?? me.role}
            </div>
          </div>
          <button
            type="button"
            onClick={onSignOut}
            title={t("shell.signout")}
            className="shrink-0 rounded-md p-1.5 transition-colors"
            style={{ color: "var(--color-ink-3)" }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = "var(--color-ink)"
              e.currentTarget.style.background = "var(--color-surface-2)"
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = "var(--color-ink-3)"
              e.currentTarget.style.background = "transparent"
            }}
          >
            <LogOut size={12} aria-hidden="true" />
            <span className="sr-only">{t("shell.signout")}</span>
          </button>
        </div>

        {/* Controls: theme + language */}
        <div className="flex items-center gap-1.5">
          <div
            className="flex flex-1 items-center gap-0.5 rounded-lg p-0.5"
            style={{ background: "var(--color-surface-2)", border: "1px solid var(--color-rail-strong)" }}
            role="group"
            aria-label={t("prefs.theme")}
          >
            {["dark", "light"].map((mode) => (
              <button
                key={mode}
                type="button"
                aria-pressed={theme === mode}
                onClick={() => setTheme(mode)}
                className="flex flex-1 items-center justify-center gap-1 rounded-md py-1 text-[11px] font-medium"
                style={{
                  background: theme === mode ? "var(--color-surface-3)" : "transparent",
                  color: theme === mode ? "var(--color-ink)" : "var(--color-ink-3)",
                  transition: "background 220ms ease, color 220ms ease",
                }}
              >
                {mode === "dark" ? <Moon size={11} aria-hidden="true" /> : <Sun size={11} aria-hidden="true" />}
                {mode === "dark" ? t("prefs.theme.dark") : t("prefs.theme.light")}
              </button>
            ))}
          </div>
          <div
            className="flex items-center gap-0.5 rounded-lg p-0.5"
            style={{ background: "var(--color-surface-2)", border: "1px solid var(--color-rail-strong)" }}
            role="group"
            aria-label={t("prefs.lang")}
          >
            {[
              ["en", "EN"],
              ["zh", "中文"],
            ].map(([id, label]) => (
              <button
                key={id}
                type="button"
                aria-pressed={locale === id}
                onClick={() => setLocale(id)}
                className="rounded-md px-2 py-1 text-[11px] font-semibold"
                style={{
                  background: locale === id ? "var(--color-surface-3)" : "transparent",
                  color: locale === id ? "var(--color-ink)" : "var(--color-ink-3)",
                  transition: "background 220ms ease, color 220ms ease",
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* The one sentence this portfolio project owes every screen — kept (real claim). */}
        <p className="mt-3 text-[9px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
          {t("rail.disclaimer")}
        </p>
      </div>
    </aside>
  )
}
