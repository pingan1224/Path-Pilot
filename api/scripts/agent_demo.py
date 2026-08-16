"""Run the agent against the three hero scenarios and print full traces.

    .venv/Scripts/python -m scripts.agent_demo [--case N]

Each question maps to one of the demo narratives:
1. Alex — "why is my registration blocked" → holds tool + policy, cited answer
2. Alex — "I already uploaded it" → unverifiable claim → escalation with case number
3. Priya — prerequisite question → catalog + policy, multi-tool
4. Diego — "why at risk with 27 credits" → progress tool, the wrong-credits explanation
5. Student asks about overrides → the restricted doc is invisible; answer from public
   policy only (rule 3 under real fire)
"""

import argparse
import json

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import Student, User, UserRole
from app.services.agent import run_agent

QUESTIONS = [
    ("Alex Chen", "Why is my registration blocked?"),
    ("Alex Chen", "I already uploaded the verification worksheet last week. Can you confirm you received it and clear the hold?"),
    ("Priya Raman", "I tried to add MASY-GC 2200 and it was rejected. What happened and what should I take instead?"),
    ("Diego Morales", "I have 27 credits out of 36. Why does my dashboard say I am at risk of not graduating on time?"),
    ("Priya Raman", "How do course substitution overrides get approved internally? Who signs off?"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=int, default=0, help="run only case N (1-based)")
    args = parser.parse_args()

    with get_sessionmaker()() as session:
        by_name = {
            name: sid
            for sid, name in session.execute(
                select(Student.id, User.full_name).join(User, User.id == Student.user_id)
            ).all()
        }

        selected = (
            [QUESTIONS[args.case - 1]] if args.case else QUESTIONS
        )
        for i, (who, question) in enumerate(selected, start=args.case or 1):
            print(f"\n{'=' * 88}\n[{i}] {who}: {question}\n{'=' * 88}")
            result = run_agent(
                session,
                question=question,
                acting_role=UserRole.student,
                subject_student_id=by_name[who],
            )
            print(f"decision   : {result.decision.value}   intent={result.intent}   confidence={result.confidence}")
            print(f"iterations : {result.iterations}   latency={result.latency_ms}ms   degraded={result.degraded_modes}")
            print(f"tools      : {[t['tool'] for t in result.tool_trace]}")
            if result.referral:
                r = result.referral
                print(f"referred   : {r.get('office')} — {r.get('question')}")
            print(f"\n{result.answer}\n")
            if result.citations:
                print("citations:")
                for c in result.citations:
                    print(f"  - [{c['source_id']}] {c['claim'][:90]}")


if __name__ == "__main__":
    main()
