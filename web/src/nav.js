import { BarChart2, Calendar, CheckSquare, FileText, MessageSquare } from "lucide-react"

/**
 * The rail's five slots, in the order they are drawn. One definition, three consumers:
 * the sidebar, the ⌘K palette, and the shell's live sub-line map.
 *
 * It was three definitions, and they had already drifted — the sidebar drew
 * planner / mission / intake / sequence and the palette listed planner / intake /
 * sequence / mission, so the same five entries came back in two different orders
 * depending on how the student opened them.
 *
 * Five, not one per view. `decoder`, `program` and `dashboard` are routable and reachable
 * and deliberately hold no slot: the decoder's entry is the chat (paste the error), the
 * program page opens from the enrolled-program chip above the nav, and the dashboard is
 * the pre-shell demo overview. A slot for each would duplicate an entry point that already
 * exists. `StudentShell.VIEW_PATHS` is the routing list and is intentionally a different
 * set from this one.
 *
 * Order is the design's. Each slot's label comes from `nav.<id>` and its sub-line from the
 * shell's live reads, so nothing user-visible is hardcoded here beyond the icon.
 */
export const NAV_ITEMS = [
  { id: "chat", icon: MessageSquare },
  { id: "planner", icon: BarChart2 },
  { id: "mission", icon: CheckSquare },
  { id: "intake", icon: FileText },
  { id: "sequence", icon: Calendar },
]

export const NAV_IDS = NAV_ITEMS.map((item) => item.id)
