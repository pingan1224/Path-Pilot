# Path Pilot

An AI-enhanced redesign of NYU's Albert student information system, implemented from a
graduate coursework RFP response. This is a personal portfolio project — not a real NYU
system, and it must never present itself as one.

## The one-line goal

Turn a paper proposal into a running system that **measures whether it meets the accuracy
numbers the proposal promised**. The eval harness is the point, not an afterthought.

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Frontend | React + Vite (JS) | `web/`. Plain JS, not TS — see the UI stack note below |
| UI | Tailwind v4 + shadcn/ui | Components are copied into `web/src/components/ui/`, not imported |
| Backend | FastAPI (Python 3.13) | `api/`. All business logic and AI lives here |
| Database | Postgres + pgvector | Business data and embeddings in the same database |
| ORM | SQLAlchemy 2.x | Typed `Mapped[]` style, not legacy declarative |
| LLM | Anthropic Claude API | Added in P3 |
| Deploy | Vercel (web) + Render (api) | |

Do **not** add LangChain, LlamaIndex, or any RAG framework. Retrieval, chunking, and
prompt assembly are written directly. Ripping out the abstraction later is more expensive
than writing 200 lines now.

## UI stack (adopted 2026-08-07)

shadcn/ui over Tailwind v4, chosen after a spike that landed on this branch. The reason it
fits rather than fights: shadcn copies component *source* into the repo instead of shipping a
dependency, so the components are editable in place and there is no library version to fight
when a card needs to behave differently.

Three things about the setup that are not obvious and will bite if forgotten:

- **`src/tailwind.css` aliases, it does not define.** `@theme inline` maps shadcn's expected
  tokens onto the palette already in `App.css`. There is exactly one palette. Never add a
  hex value to `tailwind.css` — put it in `App.css` and alias it.
- **`src/index.css` must stay inside `@layer path-pilot-reset`.** Unlayered CSS beats layered CSS
  regardless of specificity, so an unwrapped reset silently overrides every Tailwind utility.
  This cost real debugging time; the file says so at the top.
- **`npx shadcn add` is not self-sufficient here.** In plain-JS mode it generates components
  importing `cn`, `clsx`, `tailwind-merge`, and `class-variance-authority` while installing
  none of them and scaffolding no `lib/utils.js`. Expect to add missing deps by hand after
  pulling a new component.

Every student view is now shadcn over Tailwind; the migration deleted eighteen orphaned
`App.css` families along the way (`.msg`, `.mstep`, `.decoder__*`, `.seq__*`, the
`.course-*` family, …), and removing the staff views took another twenty with them (the
`.topbar`/`.subbar`/`.whoami` shell, `.case*`, `.queue*`, `.stat*`, `.table*`). What is
left in `App.css` is the token block, the `.nx-*` Nocturne signatures, shared semantic
families every surface uses (`.finding`, `.passage`, `.ev`, `.tag`, `.visually-hidden`),
and the login and student-dashboard styles, which are demo/portfolio scope and were
deliberately left on the old shell.

**There is one palette and it is global.** `--accent` and friends live on `:root`; nothing
is scoped to a container any more, and the theme flips through
`prefers-color-scheme` with a `[data-theme]` override that beats it in both directions.
Two rules when touching colour:

- **Never hardcode a hex in a component.** A stock Tailwind colour (`border-amber-500`)
  is invisible to the theme toggle — that bug shipped once in the intake OCR notice.
  Reach for `--good`/`--warn`/`--danger` or their `-soft` pairs.
- **Text on a filled accent or danger background uses `--on-filled`, never `#fff`.** White
  on the dark-mode accent measures 3.06:1. `--on-filled` is white in light and near-black
  in dark, and every combination in the palette clears 4.5:1 on all three surfaces in both
  themes — verified by sweeping the painted DOM, not by eye.

## Non-negotiable architecture rules

These come from the source RFP. Violating one breaks the project's whole premise.

1. **The AI layer never queries the database directly.** Student-specific data reaches the
   model only through a permission-checked tool layer that returns scoped facts. No raw SQL
   in prompts, no table names in model context.

2. **Every factual claim carries a source and a timestamp.** Generation uses a structured
   output schema where assertions require `source_id` and `verified_at`. An uncited claim
   must be structurally impossible to emit — never rely on prompt instructions alone.

3. **RBAC filters before retrieval, never after.** Permission scoping is applied as a
   pre-filter on the vector search and the SQL tool layer. Out-of-scope data must never
   enter the candidate set, so it can never leak into a prompt.

4. **Staleness is disclosed, not hidden.** Every source has its own freshness policy
   (financial balance 15 min, degree audit 24 h, policy docs 30 days). Past that threshold
   the answer says so explicitly rather than presenting stale data as current.

5. **Uncertainty escalates to a human.** When evidence is missing, conflicting, stale, or
   the intent is high-stakes (graduation timing, substitutions, appeals, holds, financial
   posting, academic standing), the bot does not guess. It states what it can and cannot
   verify, then routes to the responsible office with a case number.

6. **No silent failures.** Every external dependency has a defined degradation path, and
   degraded mode is visible to the user. Embedding service down → keyword fallback with a
   lowered-confidence notice. Student data unavailable → policy questions only, with an
   explicit note about what is unavailable.

7. **Every AI interaction is logged replayably.** Query, retrieved chunks with scores,
   assembled prompt, response, citations, escalation decision, and acting role. The audit
   log doubles as the eval dataset source.

8. **The AI never mutates official records.** It can create support cases and draft
   summaries. It cannot clear holds, waive prerequisites, approve exceptions, or change
   enrollment.

## Persona

One: the student. "Am I ready to register, and will I graduate on time?"

There were four. `advisor`, `registrar`, and `finance` each had a dashboard landing on its
own question, and each was scoped so that finance saw no advising context and the registrar
saw no individual financial detail. Those three product surfaces were removed on
2026-08-08. Read this as a scope decision, not as a claim that the scoping was wrong: the
staff views cost three more places to maintain for every change to the thing this product
is actually for, and a portfolio project that does four jobs adequately is worth less than
one that does a single job properly.

`advisor` survives as a role on `User`, deliberately, in two places that are not a UI:

- A student's record names their advisor, and the handoff — the product's actual output —
  is an email addressed to that person.
- Retrieval scopes documents by audience (rule 3), and the leak probes prove a student
  cannot reach the advisor-only override procedure. An audience filter with exactly one
  audience in it proves nothing; `advisor` is what keeps that a real test.

An advisor account cannot sign in — `password_hash` is null in the seed — so there is no
staff surface behind any door. `scripts/authz_probe.py` checks both halves: the routes are
404 rather than 403, and the login itself is refused.

FERPA minimum-necessary now means one sentence: a caller reaches their own record and no
other. That is checked from both sides, with two signable students.

## UI principles

From the RFP's UI/UX section. Applies to every screen.

- **One question, not a menu.** The product opens on where registration stands, not on a
  list of things it can do. (This was "role-first, not feature-first" when there were four
  roles; the principle survived the roles.)
- **Status hierarchy before detail.** Critical blockers render above general information.
- **Plain language with provenance.** Every status shows what it means, where it came from,
  when it was last verified, and the next action.
- **Never color alone.** Every red state also reads "Action required", every yellow
  "Review recommended", every green "No immediate action". WCAG 2.1 AA is a baseline.
- **The bot is never modal.** The dashboard stays visible while asking questions.

## Conventions

- Python: `snake_case`, full type hints, `ruff` defaults. Routers in `api/app/routers/`,
  one module per resource.
- React: function components, colocated CSS modules, no global state library until there is
  a demonstrated need.
- API shape: `/api/v1/...`, plural nouns, errors as
  `{"error": {"code": str, "message": str}}` with a human-readable `message`.
- Timestamps: UTC ISO-8601 everywhere in the backend. Localize only at render time.
- Seed data uses realistic but clearly fictional student names. No real NYU student data,
  ever.
- Commit messages: imperative mood, scoped prefix (`api:`, `web:`, `eval:`, `docs:`).

## Phases

`P0` scaffold · `P1` schema + seed · `P2` API + wire frontend · `P3` RAG bot ·
`P4` eval harness · `P5` RBAC + audit · `P6` case study + demo

Current phase: **M7 complete (A: agent-first shell, B: one-shot execution, C: transcript
intake); M8 closed the B26 retrieval give-up finding with a measured search budget; M9 built
fault injection and took degradation coverage 0/4 → 4/4, finding three real bugs including
a keyword fallback that had never once executed successfully; M10 added OCR, where the work
went into what it is *not* allowed to do — no row read from an image can ever reach
`matched`. The server then took over deciding what the chat renders, retiring the card
inference the frontend used to do from `tool_trace`; the trace is back to being an audit
record, which is all it was ever meant to be. The product is student-only.**

**Nothing is deployed.** Every number in this repo was measured on a laptop against a dev
database, which means the production shape — Vercel rewriting `/api/*`, the session cookie
surviving that, whether the proxy buffers SSE — is assumption rather than evidence. Open
gaps, in the order they block a real user: deployment and the M12 beta hardening around it
(rate limits, a per-user cost ceiling, real secrets in place of the dev defaults), the
tool-event stream (PRD FR-13 — the frontend still shows a timed waiting message rather than
what the agent is actually doing), and M11's multi-turn context budgeting.

## Agent-first shell (`web/src/views/ChatHome.jsx`, M7-A)

The chat is the student's default tab; the floating Ask Path Pilot panel is gone. Three rules:

- **Cards render authoritative state, not snapshots.** After each answer the tool trace
  says what was consulted; ChatHome re-fetches the mission / re-runs the deterministic
  sequence and decoder endpoints and renders those as inline cards
  (`web/src/components/chat/cards.jsx`). "No stored status, recompute on read" applied to
  the UI: what the student acts on must be what is true now.
- **Card buttons call the same student-authenticated endpoints as the full pages.**
  Confirming an AI-proposed course happens inside the chat; the server's recomputed
  mission replaces the card state. The propose/confirm boundary is unchanged — the card
  is just the confirm surface moved to where the proposal happened.
- **The greeting is computed, not generated.** Profile + mission state → deterministic
  greeting and context-aware suggestion chips. No LLM call for "hello".

The old views (decoder/mission/sequence/planner) survive as secondary tabs — the "let me
look at the records myself" path. Do not remove them.

## One-shot execution (M7-B)

"Help me get ready to register" does the whole job in one turn: read the plan, open a
mission if there is none, propose the courses that fit, sequence the remaining terms, name
what only Albert knows, and end with what is left for the student to decide — not with a
question about whether to start. Rule 8 in the system prompt says so explicitly.

**`start_mission` is the second write tool, approved 2026-08-07** after being raised as a
boundary question rather than assumed. The reasoning is structural: an empty container
asserts nothing about the plan, its only parameter is a term the student sees immediately
and can change, and every decision inside it stays student-only and unreachable from any
tool. `missions.created_by` records the origin and the UI badges it. Omitting the term
defaults to `next_registerable_term()` and returns `term_was_assumed: true` so the model
must disclose it.

**Any new write tool must be added to `eval/golden.WRITE_TOOLS`.** CI asserts those names
still resolve, but nothing can detect a write tool left *out* of the list — the comment
there is the only guard.

**Conversation history is text only, capped at 6 turns.** Prior tool calls and results are
deliberately never replayed: a stale seat count from two turns ago would sit in context
looking exactly as authoritative as this turn's lookup, and the rule that every claim cites
a source returned *this turn* would quietly stop holding. History carries what was said;
the tools re-establish what is true. It is client-supplied and untrusted, which is
acceptable because it grants no data access — the worst a forged history does is mislead
the model about earlier dialogue, which a user can already do by typing it.

Durable state does not need history: profile, mission, and accepted risks are persistent
and recomputed on read, so the agent already knows where things stand. History exists for
one narrow job — resolving what "that one" refers to.

## Transcript intake (`app/intake/`, M7-C)

Upload a PDF, review what was read, confirm what is right. Removes the largest friction in
the product (typing a dozen courses before anything else works) without changing what the
data *is*: a transcript-sourced course enters `profile_courses` as a self-reported claim,
identical to a typed one, with no "imported" marker — the file was never verified either.

**OCR exists (M10), and the interesting part is what it is not allowed to do.** It was
built on the product judgement that students photograph their transcripts whatever the
upload form says — which is true, and the pre-OCR behaviour was worse than "no OCR": a
`.jpg` could not even be opened, so the likeliest real upload got the least useful answer in
the product.

- **Vision endpoint, not tesseract.** Chosen with the privacy cost stated rather than
  buried: the image is sent to OpenAI, disclosed to the student *before* they upload. A
  local tesseract keeps data on the machine but needs a system binary everywhere this
  deploys and is markedly worse on phone photos, which is the entire motivating case.
- **No OCR row can ever be `matched`.** `service._as_reviewed` forces every one to
  `needs_review`, and there is deliberately no confidence threshold that promotes one — a
  score from a model that cannot see the original is a claim about its own certainty.
- **The measurement that justifies it.** Three photo fixtures (clean / skewed / low-res),
  all five rows read in each. On the downscaled JPEG the reader returns `A-` for a course
  the page grades `A` — **reproducibly, three runs of three**, with nothing in the reading
  looking any different. Had OCR rows reached `matched`, a batch confirm writes a silent
  one-notch grade downgrade into a degree audit.
- **`silently_wrong` cannot measure OCR**, because nothing OCR produces is ever vouched
  for. That metric would read zero however badly the images were parsed, so
  `ocr_field_errors` is reported separately and is *not* gated at zero — its job is to say
  how much checking the student is really being asked to do. Currently 1.

The prompt asks for transcription, never interpretation: a model told to "read this
transcript" repairs course codes into ones that exist and drops rows it thinks are headers,
producing a clean record of a document nobody has.

**Real transcripts are never committed.** The reader met its first one on 2026-08-07 and
read it 12/12 — a genuine Albert export, in a shape none of the four invented fixtures had.
The document carried a name, birthdate and student number and stayed out of the repo;
`transcript_sis_export.pdf` (case T06) reproduces its *layout* with invented data. Do the
same with any future one: copy the shape, never the record.

**Parsing anchors on the course code**, because that is the only field every layout preserves
intact. Three measured findings drove this and are all defended by tests:

- Table extraction emits **one cell per line**, so a row arrives as five separate lines. The
  obvious line-regex approach reads nothing.
- **Empty cells vanish from the stream entirely.** A blank-grade row runs into its neighbour;
  before the row window was bounded on a *second credits token*, an in-progress course
  absorbed the next row's "TR" and reported a grade the student never earned.
- **Term association is directional.** A labelled term (`Term: Fall 2024`) follows its
  course; an unlabelled one is a header sitting above its courses. Preferring either
  direction alone mis-assigned every row of the other layout. In side-by-side columns the
  linear order carries no association at all, so the term is **dropped rather than guessed**
  — it is optional in the profile, so blank costs nothing and wrong puts a course in the
  wrong semester.

`matched` means the reader vouches for every field; a test asserts a matched row can never
carry an unresolved one. Off-scale grades (S/U/P/TR/W/I) are recognised and flagged rather
than read as "no grade", which would silently report finished coursework as in progress. The
review UI pre-selects only `matched` rows — pre-selecting a flagged row would turn "please
check this" into "we checked this".

Gated at `intake_silently_wrong = 0`; row recall merely has a floor. The asymmetry is the
point: a row read wrong and accepted is invisible damage, a row missed is visible.

## Product direction (as of 2026-08)

Path Pilot is becoming a real, read-only planning tool for NYU SPS graduate students, not only a
portfolio demo. Consequences that shape every decision from here:

- **There is no Albert integration and there will not be one.** A real user's completed
  courses are self-reported. The product promise is "tell me what you have taken and I will
  tell you how the published rules apply" — never "I can see your record". Tools that read
  holds or registration attempts exist for demo fixtures only; for real users those
  questions become policy answers plus an Albert self-check list.
- **Planning verdicts are computed by a deterministic rule engine, never by the model.**
  The LLM narrates results and cites sources. A rule engine that is wrong can be fixed and
  regression-tested at one point; a model that miscalculates is wrong probabilistically,
  which is unacceptable for a student acting on the answer.
- **Real catalog data and demo fixtures are strictly separated** by `courses.source` and
  `programs.source`. Planning for a real student must never traverse an invented course.
- **`/` is the real sign-in, `/demo` is the portfolio entrance.** Fictional identities do
  not share a door with real ones.
- **Disclaimers live where the advice is**, not only in a footer — the assistant panel
  carries one, because that is the text a student screenshots and acts on.
- **The error decoder is the entry point.** Every other student view needs a record entered
  before it can say anything, which is a wall in front of someone who is stuck at the
  registration screen right now. A student with an empty profile lands on the decoder; one
  with courses entered lands on the planner.

## The decoder (`app/decoder/`, M4)

Three rules, and they are the same rules as everywhere else in a new shape:

- **Classification is computed, not generated.** A rule table in `patterns.py` scores the
  message; the model narrates the result and may not overrule it. Same reason the planner
  works this way — a wrong table entry is fixable at one line and covered by a test, and a
  model that misclassifies is wrong probabilistically.
- **Ambiguity is an outcome, not a failure.** Generic hold text scores identically for
  `financial_hold` and `other` by construction, so the decoder returns both readings plus
  the question that separates them. Never encode a hold-code → office mapping; this project
  has never seen the university's hold-code table, and a plausible guess sends a student to
  pay a balance while an advising hold keeps blocking them.
- **A retrieved passage is not a source until it mentions the cause.** Retrieval always
  returns its top k, so `must_mention` stems verify each passage and the absence gets
  reported (`no_policy_note`). Two of the nine causes have no coverage in the corpus at all;
  citing the nearest neighbours instead would put a fetch date under an unfounded claim.

Follow-up answers are appended to the message and the whole thing is re-classified. There is
no decoder session state — the second reading cannot differ except through what the student
added, and there is nothing to expire or diverge between two open tabs.

## Registration missions (`app/missions/`, M5)

A resumable task: get ready to register for one term, in five steps, each needing a human
act. What it gives the rest of the system is a **termination condition** — every turn
before this was a stateless question and answer, so "done" was not a concept the agent had.

- **No status column, anywhere.** Progress is recomputed from facts on every read
  (`steps.compute_state`). A stored status is a second source of truth that drifts from the
  profile and the candidate list, and drifts invisibly, because it still looks
  authoritative while it lies. `missions`, `mission_candidates`, and `mission_decisions`
  store only things somebody did at a time.
- **The agent proposes; only the student decides.** `propose_mission_candidates` writes
  rows with `confirmed_at IS NULL` and has no parameter that could change that — the same
  design as no tool accepting a `student_id`. This boundary has two directions and both are
  probed: a proposal cannot complete a step, and a proposal cannot un-complete a finished
  mission either (a pending suggestion is not a material change).
- **Termination is decidable.** Every blocker on the *confirmed* courses is resolved or
  accepted by name. Degree-level gaps are reported separately and never block, or the
  mission would be unfinishable for anyone who has not already graduated.
- **Acceptance is per finding, by key.** `Finding.key` is stable across re-evaluations and
  independent of both verdict and wording, so "I know about this one" still points at the
  same thing next week. When the wording changes the acceptance holds but is flagged, and a
  handoff produced before a later change re-opens its step rather than being flagged —
  that document gets sent to a human who acts on it.

Add a step only if a student can work on it. An earlier draft had a sixth ("run the
prerequisite checks") that completed itself the instant the previous one did; a step nobody
can act on is a progress bar pretending to be a checklist.

## Sequence planner (`app/sequence/`, M6)

Backtracking search assigning remaining courses to future terms under five things at once:
prerequisite order, the bulletin's offering pattern, a per-term credit cap, one
concentration taken in full, and a term to finish by. Hand-written, not a solver library —
the problem is 3-8 courses over 3-8 terms, and the explanation is most of the value, where
a library returns UNSAT and UNSAT is not something you can tell a student.

- **Infeasibility is attributed by relaxation, never inferred.** Drop one constraint,
  re-solve, and report the ones whose removal actually produces a sequence. A hand-written
  diagnosis would be wrong exactly when the schedule is complicated enough to need help.
  Cheap only because the search is cheap. If no single relaxation helps, say that rather
  than blaming one.
- **Silence about offerings is not availability.** 18 of the 57 catalog courses have no
  `typically_offered` text and 2 say "occasionally". Those are searched as any-term and
  reported as `unstated` / `irregular`, and every placement resting on one is marked
  individually — not with one caveat under the grid, which tells the student nothing about
  *which* two courses to go and check.
- **The per-term credit cap is the student's number, not a rule.** The ingested corpus has
  caps for Stern's MBA programs only; quoting one at an SPS student would be the mistake the
  home-school retrieval boost exists to prevent, and worse here because it would be buried
  in a constraint instead of visible as a citation. Default is conservative and always
  disclosed as assumed.
- **`credits` requirements cannot be sequenced.** The elective scope is an open set, so a
  shortfall enters as a credit placeholder with no identity and no prerequisites checked —
  dropping it would make every finish date a course too early.
- **A `one_track` requirement is a choice, not a constraint.** Each concentration is
  sequenced separately and compared; tracks that do not fit are reported with their reason,
  because "Risk Analytics fits your deadline and Business Analytics does not" is a decision
  only the student can make.

Objective: finish soonest; among ties, prefer the plan resting on fewer guesses, then name
order so two runs on the same data give the same schedule.

## Trajectory evaluation (`eval/trajectory.py`)

The behavior eval scores outcomes, and every outcome metric is satisfiable by an agent that
blunders to the right answer — one that looks up four courses to cite one, or spends five
turns doing what fits in two. That agent costs more, is slower, and degrades as the tool
surface grows. The surface went from five tools to nine across M4-M6 with no instrument on
tool choice, so this is the instrument, and it exists *before* multi-turn because multi-turn
will move these numbers.

Scored per run from the recorded trace: repeated identical calls, lookups whose sources are
never cited, failed calls, calls per iteration, and calls against a labelled minimum.

- **Only two things are gated.** `forbidden_tool_calls` at zero — the one write tool in the
  surface (`propose_mission_candidates`) must not fire on a question that did not ask for a
  write; it is banned by default across the behavior set and opted into per case via
  `allow_write_tools`. And `redundant_call_rate` under a loose ceiling, as a tripwire.
- **Uncited lookups are reported, never gated.** Checking three courses and citing the one
  that mattered is diligence; gating it would reward padding citations, which is the exact
  padding the decoder's grounding check refuses.
- **`min_tool_calls` is labelled only where the floor is unambiguous** (8 of 35). Path ratio
  is reported over that subset with its size stated. A guessed minimum makes the ratio look
  rigorous and mean nothing.
- **Rates are per run, not per call**, so one clean twelve-call run cannot absorb a
  two-call run that repeated itself — the second is the one worth reading.

`scripts.trajectory_report` runs the same scoring over `ai_interactions` retroactively, for
free. That is rule 7 being cashed in: the audit log was always meant to double as eval data.
It also spans this project's own schema changes — the two oldest rows use a `name` key and
tool names that no longer exist — so the scorer reads both keys and the report states how
many rows predate per-call attribution rather than smoothing over it.

## Fault injection (`app/faults.py`, `scripts/fault_probe.py`, M9)

Rule 6 promises every dependency a visible degraded path. Measured across 121 audited
turns before this existed, those paths had executed **zero times**. An `except` branch that
has never run is a guess with good intentions.

`app/faults.py` arms named faults at the real dependency boundaries — embeddings, the chat
model, tool dispatch, retrieval, freshness — and `scripts/fault_probe.py` runs the **real
agent loop** on top of them and reads what the student ends up with. Two safety properties:
`settings.fault_injection` defaults False and nothing can be armed while it is off, and the
armed set is a ContextVar so a fault cannot leak into a concurrent request. Unknown fault
names raise rather than injecting nothing.

The checks are the user-visible contract: the degradation reached `degraded_modes`, the
turn did not come back as a clean `answered`, a case was opened where the request could not
be served, and — the load-bearing one — **no citation names a source no tool returned**. An
assistant that loses its evidence and keeps its confidence is worse than one that fails.

**Degradation coverage went 0/4 → 4/4.** The metric reads `ai_interactions`, not the current
invocation, so narrowing the probe with `--only` cannot reset it to zero.

**What the first run found, in order of severity:**

1. **The keyword fallback had never worked.** `unnest(:terms)` without a cast is an
   ambiguous function in Postgres, so the whole fallback raised on its first statement —
   the documented degraded path for an embeddings outage would itself have failed, in the
   one situation it exists for.
2. **A failed tool poisoned the transaction, so the escalation failed too.** The safety net
   broke in exactly the case it exists for; the student would have got a 500 instead of a
   case number. `session.rollback()` in the tool-error handler, which is safe because the
   write tools commit as they go.
3. **The fallback still carried a bug the dense path fixed months ago** — a home-school-only
   boost that buries every unaffiliated document. Dead code does not get patched. Its first
   real answer handed an SPS student the School of Social Work's waitlist procedure, in
   confident prose, with nothing marking it as degraded.

Degraded retrieval now has a measured size instead of the adjective "less relevant":
**recall@5 0.91 → 0.66, MRR 0.825 → 0.521** (`scripts/measure_degraded_retrieval.py`,
re-swept 2026-08-11 — the gap widened as the corpus grew), and
the tool tells the model those numbers plus "check the passage is actually about this
student's school" rather than a vague caveat.

## The policy-search budget (`MAX_POLICY_SEARCHES`, M8)

The defect the trajectory eval found: retrieval cannot return nothing — it always returns
its five nearest chunks — so an empty-handed search is indistinguishable from a productive
one from inside the loop, and B26 spent 13 tool calls and 8 uncited searches rewording its
way towards a document its role cannot see.

**The fix is a count, not a judgement, and that is the whole point.**
`scripts/measure_giveup.py` tested three content signals against the 50 labelled queries and
every multi-search turn in the audit log. A relevance floor does not separate (answerable
min 0.5894 vs unanswerable max 0.6480). Query similarity and result novelty separate
*backwards* — the most repetitive turn in the log is four prerequisite lookups for four
different courses. Only the count separates: max 4 searches on any productive turn, 8/9/13
on the three circling ones. The cap is 5, one above the observed productive maximum.

- The sixth call is **refused before retrieval runs** — no embedding, no fresh passages to
  tempt another reformulation — and returns the queries already tried.
- Every result carries `searches_remaining_this_turn`, and a note near the end, so running
  out is a stop the model saw coming rather than a wall it hits.
- Exhaustion records `retrieval_budget_exhausted` in `degraded_modes`, so the audit row
  shows a turn that answered on less evidence than it wanted.
- Repeats are **not** deduplicated and low scores are **not** filtered. Both would be the
  quality judgement the measurement says cannot be made.
- The decoder's own retrieval is not budgeted: it verifies a passage mentions the cause and
  says so when none does, so it cannot circle.

Result: B24/B25/B26 fell from 8/9/13 tool calls to a mean of 3.67, same outcomes.

**Leakage probes must fail on substance, not spelling.** Fixing the above exposed that
`"two substitutions"` could not detect a leak: it appears verbatim in none of the 3,465
student-visible chunks, but the public SPS policy states the same rule in its own words, so
an honest answer paraphrasing public policy tripped it. Probes were written against the old
15-chunk corpus and never migrated when the real one landed. `validate_leak_phrases()` now
runs before any model call and fails the run if a forbidden phrase appears in a
student-visible chunk. It cannot catch a phrase the corpus merely *licenses* by paraphrase —
that judgement stays with the author, recorded in the comment above `OVERRIDE_LEAK`.

## Data layers

- `documents` / `document_chunks` — 35 ingested bulletin pages, ~1,250 chunks per strategy
- `courses` where `source='catalog'` — 57 real MASY1-GC courses, 21 prerequisite edges
- `requirements` where the program is `source='catalog'` — 5 encoded degree rules with
  `rule` in (all_of, credits, one_track) and 4 concentration tracks
- everything `source='demo'` — the seeded scenarios the eval and screenshots depend on

P4 facts: golden set in api/eval/golden.py (15 retrieval + 35 behavior cases) plus
api/eval/decoder_cases.py (32 error messages); runner is scripts/run_eval.py (--gate for
thresholds, --only for subsets, --only-decoder for the model-free part, --reseed to restore
the demo db). Official run 2026-08-11 (SPS program corpus, 1,461 heading chunks): 34/35,
high-stakes recall 1.0, leakage 0, over-escalation 0.0714, tool calls/run 2.37,
forbidden 0, gate PASS. The one failure is B20 flipping to escalate on a borderline call —
1 of 3 on re-run, the same shape as B05 before it. Previous baseline, 2026-08-07 on the
pre-program corpus: 34/35, recall 1.0, leakage 0, calls/run 2.34.

**Every failure this suite has produced was intermittent**, and until 2026-08-11 it could
not say so: one attempt per case, a model that rejects any temperature but 1, and a coin
flip reported as a verdict. B35's write-tool call was 2 of 6 before it was fixed; B29-B32
open a mission on some runs and not others.

`--repeat N` is the instrument. CI runs `--gate --repeat 3`. Three things it changes, and
the direction of the first is the point:

- **The hard zeros get stricter.** Leakage, forbidden calls and assistant failures are
  counted on every attempt, so one leak in nine fails the run. They are never a vote —
  a majority rule would let two clean attempts outnumber a real violation.
- **Rates become means over attempts.** Over-escalation read 0.0714 at one attempt and
  0.0238 over three; the second is the estimate, the first was a sample.
- **A third verdict, `flaky`.** A case whose attempts disagree is neither passed nor
  failed, and is reported with its decision sequence rather than gated — flakiness is a
  property of the system, and failing the build for it leaves the gate permanently red.

At `--repeat 3` on 2026-08-11: 34/35 passing every attempt, **1 flaky** (B20, 2/3,
`escalated, answered, answered`), 0 failing all three. A subset run (`--only`) now reports
`gate: n/a` instead of grading thresholds against a sample nobody chose.
Decoder run 2026-08-06: 28/32, coverage 0.8333, accuracy 1.00, 0 confidently wrong. The
decoder set's `held_out` family is written to fail — its misses are the table's backlog, and
adding those exact phrasings to the table is the one way of moving coverage that means
nothing.
The behavior prompt was tuned against these cases — treat the set as a regression gate,
and add held-out cases before claiming generalization.

P3 facts worth knowing: chat = Moonshot via OpenAI SDK (`MOONSHOT_BASE_URL` is the .cn
endpoint; never send temperature — kimi-k3 rejects anything but 1); embeddings = OpenAI
text-embedding-3-small at dimensions=1024. Agent loop: max 6 iterations, submit_answer
forced on the last, citations validated server-side against tool-returned source ids.

Model choice (measured 2026-08-03 on hero cases 1/2/5, n=1 each — indicative, not a
benchmark; P4 does this properly):
- kimi-k2.7-code-highspeed: 7-14s, correct behavior on all three → demo default
- kimi-k3: 26-62s, deepest reasoning (found the prereq chain unprompted)
- kimi-k2.6: 24-40s, over-escalated routine questions three times → avoid

## Out of scope

Real NYU integration, real student data, payment processing, mobile apps, and anything
that would make this look like a production system rather than a portfolio project.
