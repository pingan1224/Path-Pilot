# UAX — Unified Academic Experience

An AI-enhanced redesign of a university student information system, built from a graduate
coursework RFP response into a running, measured system.

> **This is a personal portfolio project.** It is not affiliated with, deployed at, or
> endorsed by NYU, and it contains no real student data. All records are fictional.

## Why this exists

The original deliverable was a design proposal — diagrams and specifications, no code. It
promised specific numbers: *90% escalation accuracy for high-stakes cases*, an *85%
confidence threshold*. Those were design judgments with nothing behind them.

This project implements that proposal and then **measures whether it actually hits those
numbers**. The evaluation harness is the centerpiece, not a footnote.

## What it does

Four roles, each answering a different question against the same data, scoped by
permission:

| Role | Question it answers |
|---|---|
| Student | Am I ready to register, and will I graduate on time? |
| Advisor | Which of my advisees needs me this week? |
| Registrar | Where is enrollment pressure building? |
| Finance | Which financial holds are blocking registration? |

Plus a grounded AI assistant that explains registration blockers in plain language, cites
where every fact came from and when it was last verified, and escalates to a human — with
a case number — whenever it cannot verify an answer.

## Design rules that shape the architecture

1. The AI layer never queries the database directly; student data arrives through a
   permission-checked tool layer.
2. Every factual claim carries a source and a timestamp, enforced by output schema rather
   than by prompt instruction.
3. Permission filtering happens *before* retrieval, so out-of-scope data never enters the
   candidate set.
4. Stale data is disclosed, never presented as current.
5. Uncertain or high-stakes questions escalate to a human instead of being guessed at.
6. Every dependency has a visible degradation path — no silent failures.
7. Every AI interaction is logged replayably; the audit log doubles as eval data.
8. The AI can open cases and draft summaries. It can never change an official record.

Full detail in [CLAUDE.md](CLAUDE.md).

## Stack

React + Vite · FastAPI (Python 3.13) · Postgres + pgvector · Anthropic Claude API

No RAG framework. Chunking, retrieval, and prompt assembly are written directly so each
behavior is inspectable and testable.

## Local development

**API**

```bash
cd api
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cp .env.example .env
.venv/Scripts/uvicorn app.main:app --reload
```

Serves on `http://127.0.0.1:8000`. Check `GET /api/v1/health/ready` — it reports which
dependencies are configured and which are missing.

**Web**

```bash
cd web
npm install
npm run dev
```

Serves on `http://localhost:5173`.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| P0 | Workspace, scaffolds, health checks | ✅ Done |
| P1 | Postgres schema and seed data | ◻ Next |
| P2 | API layer, frontend wired to real data | ◻ |
| P3 | RAG assistant with forced citation and escalation | ◻ |
| P4 | Eval harness — retrieval, citation, and escalation metrics | ◻ |
| P5 | Role-based access control and audit log | ◻ |
| P6 | Case study, demo video, deployment | ◻ |

## License

MIT
