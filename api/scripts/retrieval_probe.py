"""Compare what each chunking strategy retrieves for the same query.

    .venv/Scripts/python -m scripts.retrieval_probe

Not a measurement — labelled retrieval cases come next. This is the qualitative look you
take before writing labels, so the labels are informed by what the corpus actually
contains rather than by what you assumed it contains.
"""

from app.db.session import get_sessionmaker
from app.services.retrieval import search_policy

QUERIES = [
    ("student", "what happens if I miss the deadline to drop a course"),
    ("student", "how many credits do I need to be a full time graduate student"),
    ("student", "what are the prerequisites for the data driven decision making course"),
    ("student", "my GPA fell below 3.0, what happens now"),
    ("advisor", "who signs off on a course substitution"),
]

STRATEGIES = ["heading", "section", "fixed"]


def main() -> None:
    with get_sessionmaker()() as session:
        for role, query in QUERIES:
            print(f"\n{'=' * 92}\n[{role}] {query}\n{'=' * 92}")
            for strategy in STRATEGIES:
                result = search_policy(session, query, role, k=3, strategy=strategy)
                print(f"\n  -- {strategy}")
                if not result.chunks:
                    print("     (nothing)")
                for c in result.chunks:
                    school = c.url.split("/")[4] if len(c.url.split("/")) > 4 else "?"
                    path = (c.heading_path or "")[:78]
                    print(f"     {c.score:.3f}  [{school:<28}] {path}")


if __name__ == "__main__":
    main()
