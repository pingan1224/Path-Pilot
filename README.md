# UAX — Unified Academic Experience

A registration-readiness and academic-planning tool for NYU SPS graduate students, built
from a graduate coursework RFP response into a running, measured system.

> **Not an NYU system.** This is an independent personal project, not affiliated with,
> endorsed by, or connected to New York University. It has no access to Albert and cannot
> see your real record. Every student, hold, and case in the demo is fictional. Policy text
> is quoted from the public NYU Bulletins with a source link and a fetch date beside it.
> **Albert is always authoritative** — treat anything here as a prompt to go check, never
> as the answer.

## Why it exists

The original deliverable was a design proposal — diagrams and specifications, no code. It
promised specific numbers: *90% escalation accuracy for high-stakes cases*, an *85%
confidence threshold*. Those were design judgments with nothing behind them.

This project implements the proposal and then **measures whether it hits those numbers**.
The evaluation harness is the centrepiece, not a footnote — and it has repaid the effort by
catching real defects, several of them in code that had already shipped.

## What it does

Signing in decides what you see; there is no role switcher.

| Role | The question it answers |
|---|---|
| Student | Am I ready to register, and will I graduate on time? |
| Advisor | Which of my advisees needs me this week? |
| Registrar | Where is enrollment pressure building? |
| Finance | Which financial holds are blocking registration? |

Students land in a chat. It greets from computed state ("your Spring 2027 mission is 4 of
5 steps done — next: the advisor handoff"), answers with citations, and renders what the
agent did as **cards you can act on in place**: a proposed course arrives with its
rationale and an "Add to my plan" button wired to the same student-authenticated endpoint
as the full mission page. The agent proposes; the click that decides is yours, and it
happens where the proposal happened instead of three tabs away.

Ask it to get you ready to register and it does the whole job in one turn — reads your
plan, opens a mission if you have none, proposes the courses that fit, sequences the
remaining terms, says what only Albert can tell you — then ends with the decisions that are
yours. Measured on a real run: 12 tool calls, 5 model turns, 18 seconds, one reviewable
answer. Four proposed courses, one "Add all" click, and the audit trail still records that
the assistant suggested them and you confirmed.

It explains registration blockers in plain language, cites where every fact came from and
when it was last verified, and escalates to a human — with a case number — whenever it
cannot verify an answer.

**The error decoder** is the way in. Paste the message Albert refused you with and it names
the cause, shows which words in your own text it based that on, quotes the bulletin passage
that explains it, and checks the published prerequisites against the courses you have
entered. Nothing has to be filled in first, which is the point: every other view needs a
dozen courses before it can say anything.

Its most-used answer is a question. "You have a hold on your record" does not say which
office placed one, so the decoder says both readings are live and asks which office Albert
names — because reading that as a financial hold would send a student to pay a balance
while an advising hold went on blocking them.

**A registration mission** is the task that entry point leads into: five steps from an
empty record to a summary you can send your advisor, resumable weeks later. Its progress is
never stored — it is recomputed from what you have entered, chosen, and decided, so it
cannot drift out of step with the facts underneath it.

The assistant can suggest courses for it and can report what is left. It cannot confirm one,
accept a risk, or finish the mission, and it cannot un-finish one either. Those are actions
with a person's name on them.

**The term sequence** answers the question you cannot work out on paper: in what order can
the remaining requirements actually be taken, given that prerequisites have an order, courses
only run in certain terms, one concentration has to be finished in full, and there is a limit
to what you will carry in a term. When those cannot all be satisfied, it names which one is
in the way — established by removing it and re-solving, not guessed:

> No sequence fits. Any one of these would be enough to unblock it on its own: the term you
> want to finish by; the credits you are willing to take per term.

Each placement says what it rests on. Two-thirds of the catalog publishes when a course runs;
for the rest the term is a guess and is labelled one, per course, because a single caveat
under the grid does not tell you which two courses to go and check.

**Try it:** `/demo` signs you in as any role with one click. Everything there is fictional,
and each role is blocked from the others' data — which you are invited to test.

## Design rules that shape the architecture

1. The AI layer never queries the database directly; student data arrives through a
   permission-checked tool layer, and **no tool accepts a student id from the model**.
2. Every factual claim carries a source and a timestamp, enforced by output schema and
   validated server-side against what the tools actually returned.
3. Permission filtering happens *before* retrieval, so out-of-scope data never enters the
   candidate set.
4. Stale data is disclosed, never presented as current.
5. Uncertain or high-stakes questions escalate to a human instead of being guessed at.
6. Every dependency has a visible degradation path — no silent failures.
7. Every AI interaction is logged replayably; the audit log doubles as eval data.
8. The AI can open cases and draft summaries. It can never change an official record.

Full detail in [CLAUDE.md](CLAUDE.md).

## Measured

Latest full run — see `api/eval/results/` for the reports.

| Metric | Value | Gate |
|---|---|---|
| Agent behaviour cases passed | 35/35 | — |
| High-stakes escalation recall | 1.00 | ≥ 0.90 *(the RFP's promise)* |
| Over-escalation rate | 0.00 | ≤ 0.40 |
| Citation coverage on answers | 0.91 | ≥ 0.90 |
| Restricted-document leakage | 0 | = 0 |
| Retrieval recall@5 / MRR | 0.91 / 0.815 | ≥ 0.85 / 0.75 |
| Decoder cases passed | 28/32 | — |
| Decoder accuracy when it names a cause | 1.00 | = 0 wrong |
| Decoder coverage (labelled causes named) | 0.83 | ≥ 0.80 |
| Decoder ambiguity held (hold office never invented) | 1.00 | = 1.00 |
| Authorization boundary checks | 32/32 | all |
| Mission end-to-end probe | 33/33 | all |
| Unit tests (rule engine, decoder, missions, sequence) | 157/157 | all |
| Readiness consistency (two implementations) | 48/48 | 0 mismatches |
| Assistant latency p50 / p95 | 4.7s / 17.2s | reported |
| Forbidden (write) tool calls | 0 | = 0 |
| Repeated identical tool calls | 0.00 | ≤ 0.20 |
| Tool calls per run / per iteration | 3.11 / 0.94 | reported |
| Runs with uncited lookups | 0.40 | reported |
| Path ratio (8 labelled cases) | 2.12 | reported |

### Trajectory — how it got there, not just whether it arrived

Every metric above is satisfiable by an agent that blunders to the right answer: one that
looks up four courses to cite one, or takes five turns over what fits in two. The tool
surface grew from five to nine across three milestones with nothing watching tool choice, so
that got its own instrument — repeated calls, lookups whose sources are never cited, calls
per iteration, and calls against a labelled minimum, all scored from the recorded trace.

Two things are gated and the rest is reported. The one **write** tool in the surface must
never fire on a question that did not ask for one (hard zero, banned by default across the
behavior set and opted into per case). Repeated identical calls sit under a loose ceiling as
a tripwire. Uncited lookups are deliberately *not* gated — checking three courses and citing
the one that mattered is diligence, and penalising it would reward padding citations.

`scripts.trajectory_report` applies the same scoring to the audit log retroactively, so
there is a baseline without spending a token — the log was always meant to double as eval
data. It also spans this project's own schema history: the two oldest rows still carry tool
names that no longer exist and a `student_id` argument from before that parameter was
removed, so the scorer reads both trace formats and the report says how many rows predate
per-call attribution instead of quietly scoring them as clean.

**It found something on the first run.** The three leakage probes ask about a document their
role cannot see. All three pass — zero leakage, correct refusal — and the trajectory is
awful: the agent searches, gets unrelated passages back, and searches again. **B26 spent 13
tool calls and 8 uncited policy searches to arrive at one refusal.** Nothing in the loop
tells it that repeated empty-handed retrieval means stop. Outcome metrics called that a pass
for months; this is the number that noticed, and it is the next thing to fix.

Two ablations, both reported as measured rather than as hoped:

- **Home-school scope boost** — recall@5 0.7367 → 0.9100, MRR 0.504 → 0.8383. Nine of
  twelve retrieval misses had returned the semantically correct section from the wrong
  school. Boost value chosen at the MRR peak of a sweep, not by feel.
- **Hybrid BM25 + vector via RRF** — a wash (0.9233/0.8057 against 0.9100/0.8283). It fixes
  two cases and costs ranking quality, so it ships behind a flag with its numbers recorded
  rather than being adopted because hybrid is fashionable.
- **Decoder gap patterns** — coverage 0.7500 → 0.8333. Allowing a short run of intervening
  words inside a pattern ("requisite\*not met" catches "the requisites *were* not met") was
  motivated by one paraphrase case and recovered a held-out case nobody had written a
  pattern for. Adding that case's wording to the table would have moved the same number
  without meaning anything, which is why coverage and accuracy are reported separately.

Two of the nine causes — reserved-seat restrictions and time conflicts — have **no policy
source in the ingested corpus at all**. Retrieval cannot return nothing, so it hands back
plausible registration prose that never mentions them; the decoder verifies each passage
actually mentions the cause and, when none does, says there is no source rather than citing
the nearest neighbours. An unsourced explanation labelled unsourced is usable. The same
explanation propped up by three unrelated links is not.

## Data

| Source | What |
|---|---|
| NYU Bulletins (35 pages) | 1,252 policy chunks, embedded, cited with fetch dates |
| MASY1-GC catalog | 57 real courses, 21 prerequisite edges, parsed |
| Management & Analytics (MS) | 5 encoded degree requirements, 4 concentration tracks |
| Seeded fixtures | 48 fictional students for the demo scenarios |

Real catalog data and demo fixtures coexist and are kept strictly separate by a `source`
column: planning for a real student must never traverse an invented course.

## Stack

React + Vite · FastAPI (Python 3.13) · Postgres + pgvector · Moonshot Kimi · OpenAI
embeddings · GitHub Actions

No RAG framework. Chunking, retrieval, and prompt assembly are written directly so each
behaviour is inspectable and testable — and because the ablations above are only possible
when you own the pipeline.

## Local development

**API**

```bash
cd api
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cp .env.example .env          # fill in DATABASE_URL and the API keys
.venv/Scripts/python -m scripts.init_db
.venv/Scripts/python -m scripts.migrate
.venv/Scripts/python -m scripts.seed --reset
.venv/Scripts/uvicorn app.main:app --reload
```

**Web**

```bash
cd web
npm install
npm run dev
```

Both must run: the dev server proxies `/api` so the browser and API stay same-origin, which
is what lets the session cookie work.

**Corpus** (optional — the repo ships the extracted snapshot)

```bash
cd api
.venv/Scripts/python -m ingest.fetch          # polite, cached, respects robots.txt
.venv/Scripts/python -m ingest.extract
.venv/Scripts/python -m ingest.chunk --compare
.venv/Scripts/python -m ingest.load --all --embed
.venv/Scripts/python -m ingest.catalog        # course + prerequisite graph
.venv/Scripts/python -m ingest.requirements   # degree rules, validated before write
```

## Testing

```bash
cd api
.venv/Scripts/python -m pytest tests/ -q      # rule engine + decoder classifier, no I/O
.venv/Scripts/python -m scripts.authz_probe   # 29 adversarial permission checks
.venv/Scripts/python -m scripts.mission_probe # 33 checks: a mission end to end, plus cheating at it
.venv/Scripts/python -m scripts.smoke         # authenticated happy path
.venv/Scripts/python -m scripts.run_eval --only-decoder   # decoder alone, seconds, no LLM
.venv/Scripts/python -m scripts.trajectory_report --by-tool  # trajectory over the audit log, free
.venv/Scripts/python -m scripts.run_eval --gate   # full eval, ~4 min, calls the LLM
```

`authz_probe` is the one to read: 16 of its 29 checks assert that a **forbidden** action
fails. A permissions test that only confirms allowed actions succeed proves nothing about
the claim being made.

Ablations: `scripts.ablate_chunking`, `scripts.ablate_scope`, `scripts.ablate_hybrid`.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| P0–P4 | Scaffold, schema, API, bounded agent, eval harness | ✅ |
| RAG | Real corpus, chunking/scope/hybrid ablations | ✅ |
| P5 / M1 | Server-side identity, role-scoped APIs, login, real catalog + degree rules | ✅ |
| M2 | Self-reported profile, deterministic planning rule engine | ✅ |
| M3 | Student portal, what-if planner, advisor handoff | ✅ |
| M4 | Error decoder: paste-and-explain entry, ambiguity as a first-class outcome | ✅ |
| M5 | Registration mission: derived task state, a decidable end, agent proposes only | ✅ |
| M6 | Sequence planner: constraint solving over terms, with infeasibility attributed | ✅ |
| M7-A | Agent-first shell: chat as the front door, tool results as actionable inline cards | ✅ |
| M7-B | One-shot execution: one reviewable plan per ask, lightweight conversation history | ✅ |
| M7-C | Transcript PDF intake: upload → parse → three-state review → batch confirm | ◻ Next |
| M8 | Invite-only beta, rate limits, deployment | ◻ |

## Honest limitations

- **No Albert integration, by design and by necessity.** A real user's completed courses
  are self-reported. The product is "tell me what you have taken and I will tell you how
  the published rules apply", not "I can see your record".
- **High-confidence planning covers one program.** Other SPS programs get policy answers
  and registration guidance, not a degree audit.
- **Agent behaviour was tuned against its 35 eval cases.** That set is a regression gate,
  not proof of generalization; held-out cases are needed for that claim.
- **A sequence is only as good as the offering data, and a third of the catalog has none.**
  18 of 57 courses do not say when they run and 2 say "occasionally". Those placements are
  marked as guesses rather than quietly treated as available every term, and the per-term
  credit cap is the student's own number — the corpus has caps for Stern's MBA programs and
  nothing for SPS.
- **A mission proves preparation, not availability.** Finishing one means every published
  rule the tool can check is satisfied or knowingly accepted. It says nothing about whether
  a seat exists, whether your appointment has opened, or whether a hold is waiting — none
  of which UAX can see.
- **The decoder recognises the phrasings in its table and no others.** It matches patterns,
  so a message worded in a way nobody has written down comes back undecoded — 4 of 32
  labelled cases do, and the eval lists them as the backlog rather than rounding coverage
  up. Undecoded is the safe failure: it asks for the message verbatim instead of guessing.
- **The corpus is a dated snapshot.** Every citation carries its fetch date, and the
  staleness machinery says so, but the bulletin can change underneath it.
- **Model comparison is indicative, n=1 per scenario.** Not a benchmark.

## License

MIT
