/**
 * UI chrome strings, English. The source of truth for which keys exist — zh.js must cover
 * exactly this set, and the provider falls back to this file for any key it misses.
 *
 * What is deliberately NOT here: anything the server says. Assistant answers, mission step
 * titles, blocker summaries, artifact contents and citation claims arrive in English from
 * the API and are rendered untranslated — a translation layer over model output would put
 * unverified words under the product's citation rule. The locale toggle changes the frame,
 * not the evidence.
 *
 * Values are either a string with `{name}` slots or a function of the vars object —
 * functions exist because English needs plural logic that Chinese does not, and writing
 * `count === 1` in a template string is worse than writing it in code.
 */
export const en = {
  // Shell chrome
  "app.name": "Path Pilot",
  "app.tagline": "NYU School of Professional Studies",
  "sidebar.mission.label": "Registration mission",
  "sidebar.mission.steps": "Step {done} of {total} complete",
  "palette.placeholder": "Ask Path Pilot or jump to…",
  "palette.navigate": "navigate",
  "palette.go": "go",
  "palette.close": "close",
  "shell.skip": "Skip to content",
  "shell.back": "← Back to assistant",
  "shell.signout": "Sign out",
  "pane.label": "Side pane",
  "pane.drawer": "Readiness",
  "pane.focused": "Conversation only",
  "pane.audit": "What was checked",

  // Navigation: five slots, and each sub-line is *live state*, not a description — the
  // nav doubles as the dashboard, which is the source design's interaction logic. A
  // static sub survives only where there is no state yet (or none to have: the chat).
  // decoder / program / dashboard keep their label keys for page titles — they left the
  // nav, not the app: the chat decodes a pasted error, the program chip opens the
  // picker, and the demo dashboard is deep-link only.
  "nav.chat": "Ask Path Pilot",
  "nav.chat.sub": "Ask, paste an error, plan a term",
  "nav.planner": "Degree progress",
  "nav.planner.sub": "What is left to take",
  "nav.planner.sub.live": "{done} / {total} credits",
  "nav.mission": "Registration mission",
  "nav.mission.sub": "Get ready for one term",
  "nav.mission.sub.blocked": ({ count }) =>
    `Blocked · ${count} blocker${count === 1 ? "" : "s"}`,
  "nav.mission.sub.step": "Step {step} of {total} · {term}",
  "nav.mission.sub.ready": "Ready · {term}",
  "nav.intake": "Transcript",
  "nav.intake.sub": "PDF or photo of your record",
  "nav.intake.sub.live": ({ count }) =>
    count > 0 ? `${count} course${count === 1 ? "" : "s"} on record` : "Nothing on record yet",
  "nav.sequence": "Course planner",
  "nav.sequence.sub": "Every term to the finish",
  "nav.sequence.sub.live": "{term} sequence",
  "nav.decoder": "Decode an error",
  "nav.program": "Your program",
  "nav.dashboard": "Dashboard (demo)",
  "nav.heading": "Records & tools",
  "rail.program.eyebrow": "Enrolled program",
  "rail.program.open": "Open program settings",

  // Rail
  "rail.aria": "Registration readiness and tools",
  "rail.program.unset": "Tell us your program",
  "rail.program.unset.meta":
    "Degree progress, sequencing and missions need to know which rules apply to you.",
  "rail.program.unset.action": "Action required",
  "rail.program.choose": "Choose your program",
  "rail.program.encoded": "Requirements encoded — degree progress available",
  "rail.program.notEncoded":
    "Requirements not encoded — policy answers and error decoding only",
  "rail.program.full": "Full planning support",
  "rail.program.limited": "Limited support",
  "rail.failed": "Couldn't read your record",
  "rail.failed.meta":
    "A failed read, not an empty record — nothing here is known right now.",
  "rail.failed.retry": "Retry reading your record",
  "rail.recomputed":
    "Recomputed on every read. Your completed courses are self-reported — Path Pilot " +
    "cannot see Albert.",
  "rail.disclaimer":
    "Personal portfolio project — not an official NYU system. Students and records are " +
    "fictional; policy text is quoted from public NYU bulletins with source links.",

  // Preferences
  "prefs.theme": "Theme",
  "prefs.theme.auto": "Auto",
  "prefs.theme.light": "Light",
  "prefs.theme.dark": "Dark",
  "prefs.lang": "Language",

  // Chat — landing
  "chat.hero.title": "What should you take next?",
  "chat.hero.desc":
    "I read NYU's published rules and the courses you have entered — nothing else. " +
    "I cannot see Albert, so anything I cannot check, I name instead of guessing.",

  // Chat — computed greeting
  "greet.hi": "Hi {name} — {status}",
  "greet.recovered": "Your record is readable again — {status}",
  "greet.mission": ({ term, done, total, next }) =>
    `your ${term} mission is ${done} of ${total} steps done.` +
    (next ? ` Next: ${next}` : ""),
  "greet.courses": ({ count }) =>
    `you have ${count} course${count === 1 ? "" : "s"} on record and no term being prepared.`,
  "greet.empty": "there is nothing on record yet.",
  "greet.failed":
    "Hi {name} — I couldn't read your record just now, so I can't say where your " +
    "registration stands. That is a connection problem, not an empty record. I can " +
    "still explain registration errors and published policy — neither needs it.",

  // Chat — suggestion chips
  "chip.next": "What should I take next term?",
  "chip.suggest": "Suggest courses for my mission",
  "chip.plan": "Plan my next semester",
  "chip.delay": "Which course would delay me if I skipped it?",
  "chip.prereq": "What does ERR_PREREQ mean?",
  "chip.first": "What should I do first?",
  "chip.holds": "How do registration holds work?",

  // Chat — answer frame
  "kicker.answered": "Answered from verified sources",
  "kicker.caveat": "Answered — read the caveats",
  "kicker.escalated": "Routed to a human",
  "kicker.refused": "Outside what I can verify",
  "chat.you": "You",
  "chat.assistant": "Path Pilot",
  "chat.case":
    "Case {number} has been opened — quote it when you contact the office.",
  "chat.degraded": "Ran degraded — ",
  "chat.boundary":
    "I can read published rules, explain what your entries imply, and open a case with " +
    "the right office. I cannot clear a hold, waive a prerequisite, approve an " +
    "exception, or change your enrollment — those stay with the offices that decide them.",
  "chat.checked": "Checked: {tools}",
  "chat.citations": ({ count }) =>
    `${count} cited claim${count === 1 ? "" : "s"}`,
  "chat.error.kicker": "Could not answer",
  "chat.error.retry": "Ask again",

  // Chat — header and frame
  "chat.subtitle": "Grounded in your record and published policy",
  "chat.ready": "Ready",
  "chat.sources": "Sources",
  "chat.sourcesUsed": ({ count }) => `${count} source${count === 1 ? "" : "s"} used`,
  // The persistent line under the composer, and the only disclaimer still on screen once
  // the conversation has scrolled. It therefore has to carry the claim that matters —
  // that this is not an NYU system and cannot see Albert — because this is the text that
  // sits in the screenshot a student takes of an answer and acts on.
  "chat.footer":
    "Not an NYU system, and it cannot see Albert. Answers cite their sources — verify " +
    "anything that affects registration there.",

  // Chat — waiting
  "chat.thinking": "Checking your record, policy and plans as needed · ",
  "chat.thinking.long": " · still working, longer answers mean more lookups",

  // Chat — composer
  "chat.placeholder":
    "Ask what to take next term, paste an enrollment error, or check your degree…",
  "chat.ask": "Ask",
  "chat.ask.label": "Ask a question",
  "chat.send": "Send",
  "chat.disclaimer":
    "Answers cite what they rest on and say when something could not be verified. Not " +
    "an NYU system, and it cannot see Albert — verify anything that affects " +
    "registration there before you act on it.",

  // Audit pane
  "audit.title": "What was checked",
  "audit.desc":
    "Every lookup is scoped to your record before it runs, and written to the audit log.",
  "audit.empty": "Nothing yet — this fills in as you ask.",
  "audit.aria": "What the assistant checked",
  "audit.failed": "failed — not reflected in the answer",
  "audit.sources": ({ count }) =>
    `${count} source${count === 1 ? "" : "s"} returned`,
  "audit.noSources": "returned no citable source",
  "audit.degraded": "Ran degraded",

  // Tool labels (what the agent consulted, named for a student)
  "tool.search_policy": "policy search",
  "tool.get_course_info": "course catalog",
  "tool.get_my_plan": "your plan",
  "tool.albert_checklist": "where to look in Albert",
  "tool.decode_registration_error": "error decoder",
  "tool.get_mission_state": "mission state",
  "tool.propose_mission_candidates": "course suggestions",
  "tool.get_course_sequence": "term sequence",
}
