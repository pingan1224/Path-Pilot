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

Plus a grounded assistant that explains registration blockers in plain language, cites
where every fact came from and when it was last verified, and escalates to a human — with a
case number — whenever it cannot verify an answer.

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
| Authorization boundary checks | 29/29 | all |
| Mission end-to-end probe | 33/33 | all |
| Unit tests (rule engine, decoder, missions) | 110/110 | all |
| Readiness consistency (two implementations) | 48/48 | 0 mismatches |
| Assistant latency p50 / p95 | 4.7s / 17.2s | reported |

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
| M6 | Sequence planner: constraint solving over terms, offering patterns, credit caps | ◻ Next |
| M7 | Invite-only beta, rate limits, deployment | ◻ |

## Honest limitations

- **No Albert integration, by design and by necessity.** A real user's completed courses
  are self-reported. The product is "tell me what you have taken and I will tell you how
  the published rules apply", not "I can see your record".
- **High-confidence planning covers one program.** Other SPS programs get policy answers
  and registration guidance, not a degree audit.
- **Agent behaviour was tuned against its 35 eval cases.** That set is a regression gate,
  not proof of generalization; held-out cases are needed for that claim.
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
