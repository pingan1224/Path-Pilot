# UAX — Unified Academic Experience

An AI-enhanced redesign of NYU's Albert student information system, implemented from a
graduate coursework RFP response. This is a personal portfolio project — not a real NYU
system, and it must never present itself as one.

## The one-line goal

Turn a paper proposal into a running system that **measures whether it meets the accuracy
numbers the proposal promised**. The eval harness is the point, not an afterthought.

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Frontend | React + Vite (JS) | `web/`. Plain JS, not TS — frontend is the shell, not the focus |
| Backend | FastAPI (Python 3.13) | `api/`. All business logic and AI lives here |
| Database | Postgres + pgvector | Business data and embeddings in the same database |
| ORM | SQLAlchemy 2.x | Typed `Mapped[]` style, not legacy declarative |
| LLM | Anthropic Claude API | Added in P3 |
| Deploy | Vercel (web) + Render (api) | |

Do **not** add LangChain, LlamaIndex, or any RAG framework. Retrieval, chunking, and
prompt assembly are written directly. Ripping out the abstraction later is more expensive
than writing 200 lines now.

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

## Personas

Four roles, each with a different question and a different data scope:

- `student` — "Am I ready to register, and will I graduate on time?"
- `advisor` — "Which of my advisees needs me this week?"
- `registrar` — "Where is enrollment pressure building?"
- `finance` — "Which financial holds are blocking registration?" (Bursar / Financial Aid)

`finance` must not receive advising context; `registrar` must not receive individual
financial detail. This scoping is the FERPA minimum-necessary principle made visible, and
it is a demo feature, not just a backend detail.

## UI principles

From the RFP's UI/UX section. Applies to every screen.

- **Role-first, not feature-first.** Each role lands on its own question, not a menu.
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

Current phase: **P3 done → P4 (eval harness)**

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
