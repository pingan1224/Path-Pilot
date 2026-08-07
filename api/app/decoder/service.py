"""Turning a classification into an answer: cited policy, and a check against what the
student has actually told us.

The order of operations is the argument. Classify first, from the message alone. Only
then retrieve policy, and only for the cause (or causes) that survived. Retrieving first
and letting the passages suggest a cause would be the same mistake as letting the model
pick the cause: whatever the corpus happens to rank highest starts deciding what went
wrong, and a hold message would get explained as a prerequisite problem because the
prerequisite page embeds well.

The record cross-check is where this stops being a glossary. "Prerequisites not met" is
a sentence a student can read for themselves; "you have not entered MASY1-GC 2000, which
this course requires" is the thing they came for. It runs the same prerequisite engine
the planner uses, over the courses they typed in themselves, and it says that is what it
did — because the alternative reading, that UAX looked at their transcript, is false and
would be believed.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.decoder.classify import classify
from app.decoder.patterns import BY_REASON, HOLD_CODE_NOTE
from app.decoder.types import (
    Classification,
    DecodeOutcome,
    DecodeResult,
    RecordCheck,
)
from app.models import FailureReason
from app.planning.rules import check_prerequisites
from app.planning.types import CourseState, StatedCourse
from app.services.retrieval import RetrievalScope, search_policy

# How many passages per cause. Three rather than five: the decoder shows its sources
# inline instead of behind a disclosure, and a wall of policy text is how a student stops
# reading the one paragraph that mattered.
PASSAGES_PER_CAUSE = 3

# The decoder is offered for the one program whose requirements are encoded
# (services.profile.SUPPORTED_PROGRAM), which is an SPS graduate degree. The scope cannot
# be derived from a Student row the way the assistant's tools do it: a real signed-in user
# has no Student fixture at all, which is the entire reason live mode exists. Stating the
# scope here is honest about that; guessing per-request would not be.
DECODER_SCOPE = RetrievalScope(school="professional-studies", level="graduate")


def _reading_source_id(reason: FailureReason) -> str:
    return f"decode:{reason.value}"


def _passages(
    session: Session,
    ctx_role: str,
    spec,
) -> tuple[list[dict], int, bool]:
    """Retrieve, then verify. Returns (grounded passages, dropped count, degraded).

    Over-fetches and keeps only the passages that actually mention the cause, because
    retrieval has no way to return nothing: asked about reserved seats, a corpus with no
    page on reserved seats still hands back its four nearest neighbours, and they read as
    authoritative registration policy. Dropping them is not lost recall — it is declining
    to put a source link and a fetch date under a claim the source does not make.
    """
    result = search_policy(
        session,
        spec.policy_query,
        ctx_role,
        k=PASSAGES_PER_CAUSE * 2,
        scope=DECODER_SCOPE,
    )

    kept: list[dict] = []
    dropped = 0
    for chunk in result.chunks:
        haystack = f"{chunk.text} {chunk.heading_path or ''}".lower()
        if spec.must_mention and not any(
            stem in haystack for stem in spec.must_mention
        ):
            dropped += 1
            continue
        kept.append(
            {
                "source_id": f"policy:chunk:{chunk.chunk_id}",
                "explains": spec.label,
                "document": chunk.document_title,
                "section": chunk.heading_path,
                "text": chunk.text,
                "url": chunk.url,
                "office": chunk.office,
                "verified_at": chunk.fetched_at,
            }
        )
        if len(kept) == PASSAGES_PER_CAUSE:
            break

    return kept, dropped, result.degraded


def _finding_dict(finding) -> dict:
    return {
        "verdict": finding.verdict.value,
        "summary": finding.summary,
        "detail": finding.detail,
        "next_step": finding.next_step,
        "check_in_albert": finding.check_in_albert,
        "citations": [
            {
                "label": c.label,
                "url": c.url,
                "verified_on": c.verified_on,
                "quote": c.quote,
            }
            for c in finding.citations
        ],
    }


SELF_REPORT_BASIS = (
    "Checked against the courses you entered in UAX yourself, and the prerequisites "
    "published in the bulletin. Not your transcript — UAX cannot see it."
)


def _check_prerequisite_claim(
    session: Session, user_id: int | None, course_code: str
) -> RecordCheck:
    """Does the student's own stated record explain a prerequisite rejection?"""
    from app.planning.loader import load_catalog_courses
    from app.services.profile import list_profile

    if user_id is None:
        return RecordCheck(
            performed=False,
            basis=SELF_REPORT_BASIS,
            note="Sign in to check this against the courses you have entered.",
        )

    catalog = load_catalog_courses(session)
    course = catalog.get(course_code)
    if course is None:
        return RecordCheck(
            performed=False,
            basis=SELF_REPORT_BASIS,
            note=(
                f"{course_code} is not in the catalog UAX has loaded, so its "
                "prerequisites cannot be checked here. The course page in the bulletin is "
                "the authority."
            ),
        )

    entries = list_profile(session, user_id)
    stated = {
        e.course_code: StatedCourse(
            code=e.course_code, state=e.state, term=e.term, grade=e.grade
        )
        for e in entries
    }

    if not course.prerequisite_groups:
        return RecordCheck(
            performed=True,
            basis=SELF_REPORT_BASIS,
            note=(
                f"The bulletin lists no prerequisites for {course_code}. A prerequisite "
                "rejection with no published prerequisite is worth taking to your advisor "
                "as-is — it usually means the system is enforcing something the course "
                "page does not show, such as a program restriction."
            ),
        )

    if not stated:
        return RecordCheck(
            performed=False,
            basis=SELF_REPORT_BASIS,
            note=(
                f"{course_code} does have published prerequisites, but you have not "
                "entered any coursework yet, so there is nothing to check them against. "
                "Adding your completed courses on the planner page takes a minute and "
                "makes this answer specific."
            ),
        )

    findings = check_prerequisites(course, stated)
    return RecordCheck(
        performed=True,
        basis=SELF_REPORT_BASIS,
        findings=[_finding_dict(f) for f in findings],
        note=(
            None
            if any(f.blocking for f in findings)
            else (
                "Nothing in what you entered explains the rejection. That is worth "
                "raising with your advisor rather than retrying — the system is checking "
                "something these rules do not cover, or its copy of your record differs "
                "from what you entered here."
            )
        ),
    )


def _check_duplicate_claim(
    session: Session, user_id: int | None, course_code: str
) -> RecordCheck:
    from app.services.profile import list_profile

    if user_id is None:
        return RecordCheck(
            performed=False,
            basis=SELF_REPORT_BASIS,
            note="Sign in to check this against the courses you have entered.",
        )

    match = next(
        (e for e in list_profile(session, user_id) if e.course_code == course_code),
        None,
    )
    if match is None:
        return RecordCheck(
            performed=True,
            basis=SELF_REPORT_BASIS,
            note=(
                f"You have not entered {course_code} at all, so nothing here confirms the "
                "duplicate. Albert is counting an enrollment you may not be aware of — a "
                "different section, or a waitlist entry."
            ),
        )
    return RecordCheck(
        performed=True,
        basis=SELF_REPORT_BASIS,
        note=(
            f"You have {course_code} entered as "
            f"{match.state.value.replace('_', ' ')}"
            + (f" in {match.term}" if match.term else "")
            + ". That is consistent with the duplicate the system reported."
        ),
    )


def _check_credit_load(
    session: Session, user_id: int | None, term: str | None
) -> RecordCheck:
    from app.services.profile import list_profile

    if user_id is None or term is None:
        return RecordCheck(
            performed=False,
            basis=SELF_REPORT_BASIS,
            note=(
                "Say which term this was and the credits you have entered for it can be "
                "added up here."
            ),
        )

    wanted = term.strip().lower()
    entries = [
        e
        for e in list_profile(session, user_id)
        if (e.term or "").strip().lower() == wanted
        and e.state in (CourseState.in_progress, CourseState.planned)
    ]
    if not entries:
        return RecordCheck(
            performed=False,
            basis=SELF_REPORT_BASIS,
            note=(
                f"You have nothing entered for {term}, so there is no load to total up. "
                "The credits Albert is counting include anything you are enrolled in or "
                "waitlisted for."
            ),
        )

    known = [e for e in entries if e.credits is not None]
    total = sum(e.credits for e in known)
    unknown = len(entries) - len(known)
    note = (
        f"You have entered {len(entries)} course(s) for {term}, totalling {total} "
        "credit(s) among the ones this catalog knows"
    )
    if unknown:
        note += f", plus {unknown} whose credit value UAX does not have"
    note += (
        ". Albert also counts waitlisted classes toward the limit in most cases, so its "
        "total can be higher than this one."
    )
    return RecordCheck(performed=True, basis=SELF_REPORT_BASIS, note=note)


def _record_check(
    session: Session, classification: Classification, user_id: int | None
) -> RecordCheck | None:
    """Run the cross-check that fits the decoded cause, or none at all.

    Only three causes have anything checkable against a self-reported record. Running
    something for the other six would be theatre — and a "we checked" line that checked
    nothing is worse than silence, because it reads as reassurance.
    """
    if classification.reason is None:
        return None

    extracted = classification.extracted
    course_code = extracted.course_codes[0] if extracted.course_codes else None

    if classification.reason is FailureReason.prerequisite_not_met:
        if course_code is None:
            return RecordCheck(
                performed=False,
                basis=SELF_REPORT_BASIS,
                note=(
                    "Name the course and its published prerequisites can be checked "
                    "against what you have entered."
                ),
            )
        return _check_prerequisite_claim(session, user_id, course_code)

    if classification.reason is FailureReason.duplicate_enrollment and course_code:
        return _check_duplicate_claim(session, user_id, course_code)

    if classification.reason is FailureReason.max_credits_exceeded:
        return _check_credit_load(session, user_id, extracted.term)

    return None


def decode(
    session: Session,
    text: str,
    *,
    role: str = "student",
    user_id: int | None = None,
    answers: list[str] | None = None,
    with_policy: bool = True,
) -> DecodeResult:
    """Decode a pasted registration error.

    `answers` are the student's replies to earlier follow-up questions. They are appended
    to the message and the whole thing is classified again, rather than being tracked as
    conversation state. Re-deciding from the full text is not a shortcut: it means the
    second pass cannot contradict the first for any reason other than the new information,
    and there is no session to expire or diverge between two open tabs.
    """
    combined = "\n".join([text or "", *(answers or [])]).strip()
    classification = classify(combined)

    reading: str | None = None
    what_to_do: tuple[str, ...] = ()
    office: str | None = None
    source_ids: list[str] = []
    passages: list[dict] = []
    degraded: list[str] = []
    albert: dict | None = None

    # Which causes get an explanation. When identified, one. When ambiguous, the tied
    # candidates — because the student needs to see both readings to answer the
    # discriminating question, and showing only the leader would be the guess this whole
    # outcome exists to avoid.
    explain: list[FailureReason] = []
    if classification.reason is not None:
        explain = [classification.reason]
    elif classification.outcome is DecodeOutcome.ambiguous and classification.candidates:
        from app.decoder.classify import DECISIVE_MARGIN

        leader = classification.candidates[0].score
        explain = [
            c.reason
            for c in classification.candidates
            if leader - c.score < DECISIVE_MARGIN
        ][:2]

    if classification.reason is not None:
        spec = BY_REASON[classification.reason]
        reading = spec.reading
        what_to_do = spec.what_to_do
        office = spec.office.value if spec.office else None
        source_ids.append(_reading_source_id(spec.reason))

    uncovered: list[str] = []
    if with_policy:
        seen_chunks: set[str] = set()
        for reason in explain:
            spec = BY_REASON[reason]
            found, dropped, was_degraded = _passages(session, role, spec)
            for passage in found:
                # Two causes can legitimately retrieve the same chunk — a hold page
                # explains both readings of a hold message. Cite it once, credited to both.
                if passage["source_id"] in seen_chunks:
                    existing = next(
                        p for p in passages if p["source_id"] == passage["source_id"]
                    )
                    existing["explains"] = f"{existing['explains']}; {passage['explains']}"
                    continue
                seen_chunks.add(passage["source_id"])
                passages.append(passage)
            if not found and dropped:
                uncovered.append(spec.label)
            if was_degraded and "keyword_fallback" not in degraded:
                degraded.append("keyword_fallback")
        source_ids.extend(p["source_id"] for p in passages)

    # What only the student information system knows. Imported here rather than at module
    # scope because agent_tools imports this module to expose the decoder as a tool.
    if explain:
        from app.services.agent_tools import ALBERT_ONLY_TOPICS

        topic = BY_REASON[explain[0]].albert_topic
        entry = ALBERT_ONLY_TOPICS.get(topic) if topic else None
        if entry is not None:
            title, where, why = entry
            albert = {
                "source_id": f"checklist:{topic}",
                "topic": title,
                "where_to_look": where,
                "what_to_know": why,
            }
            source_ids.append(albert["source_id"])

    record_check = _record_check(session, classification, user_id)
    if record_check is not None and record_check.performed:
        source_ids.append(f"selfreport:decode:{user_id}")

    if classification.extracted.hold_codes:
        # Echoed, never resolved. The note says why, in the student's view, so the gap
        # reads as a boundary rather than as the tool being broken.
        albert = albert or {}
        albert["hold_code_note"] = HOLD_CODE_NOTE

    return DecodeResult(
        classification=classification,
        text_used=combined,
        reading=reading,
        what_to_do=what_to_do,
        responsible_office=office,
        passages=passages,
        record_check=record_check,
        albert=albert,
        source_ids=source_ids,
        degraded=degraded,
        no_policy_note=(
            (
                "The bulletin pages UAX has ingested contain nothing about "
                + " or ".join(label.lower() for label in uncovered)
                + ". The reading above comes from the message itself and the steps are "
                "general; there is no policy source behind them, and this tool will not "
                "cite unrelated pages to look better sourced than it is."
            )
            if uncovered
            else None
        ),
    )
