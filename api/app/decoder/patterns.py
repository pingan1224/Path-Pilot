"""The rule table: what an error message can say, and what each phrasing means.

Three things about this file are deliberate.

**It is data, not a prompt.** Classification is a decision, and this project computes
decisions rather than generating them (CLAUDE.md: planning verdicts come from the rule
engine, the model narrates). A model asked "which of these nine causes is it" answers
fluently and unrepeatably; a table answers the same way every time, is unit-testable
case by case, and when it is wrong the fix lands at one line.

**`reading` restates the message; it never states policy.** Every line here is a
paraphrase of what the system said — "the enrollment system did not see the
prerequisite as met" — and stops there. What the university then does about it comes
from retrieved bulletin passages with source ids and fetch dates. That split is what
keeps the decoder from inventing rules that sound official: it is allowed to translate
the message, and only the corpus is allowed to explain the policy.

**Generic hold text scores for two causes on purpose.** `ERR_HOLD_ACTIVE` and "you have
a hold on your record" appear under both `financial_hold` and `other`, at the same
weight, so they tie and the classifier reports ambiguity instead of a cause. A hold
message does not say which office placed it. Reading "hold" as "financial hold" is the
single most likely way this decoder could hurt somebody: the student pays a balance they
may not owe and never learns that an advising hold was the thing blocking them.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import FailureReason, Office

# Why a hold code is extracted but never decoded.
#
# The seeded demo fixtures use codes like `SF2`, and it would be easy to ship a
# `{"SF2": bursar}` lookup that makes the demo look sharp. It would also be a fabricated
# mapping: this project has never seen NYU's hold-code table, and a student acting on an
# invented decode goes to the wrong office. The code is echoed back as a string to carry
# to Albert, which does know what it means.
HOLD_CODE_NOTE = (
    "The message includes a hold code. Path Pilot does not have the university's hold-code "
    "table and will not guess what it stands for — Albert shows the hold's name and the "
    "office that placed it next to that code."
)


@dataclass(frozen=True)
class ReasonSpec:
    """One decodable cause, with everything needed to explain and route it."""

    reason: FailureReason
    # Plain-language name for the UI. The enum values are schema, not copy.
    label: str
    # What the message means, as a message. No policy content — see the module docstring.
    reading: str
    # Error tokens a machine wrote. Near-conclusive, weighted accordingly.
    codes: tuple[str, ...] = ()
    # Sentence fragments students paste or paraphrase. A `*` stands for a short run of
    # intervening text (see classify.PHRASE_GAP), so "requisite*not met" covers "requisites
    # not met", "requisite was not met", and "requisites were not met" as one pattern
    # instead of three strings and the two nobody thought of.
    phrases: tuple[str, ...] = ()
    # Single suggestive words. Too weak to name a cause alone, by design.
    keywords: tuple[str, ...] = ()
    # Which office can actually act. None means the message does not determine it.
    office: Office | None = None
    what_to_do: tuple[str, ...] = ()
    # The query used to pull cited policy for this cause. Phrased in the corpus's own
    # register rather than the taxonomy's, which is not a style preference: measured
    # against the ingested bulletin, "reserved seats and enrollment restrictions on a
    # class section" retrieves administrative prose about registration generally, while
    # the way a student would put the same question retrieves the page that answers it.
    policy_query: str = ""
    # Distinctive stems a passage must contain to count as explaining this cause.
    #
    # Retrieval always returns its top k, and for a cause the corpus says nothing about
    # (reserved seats, time conflicts) those k passages are simply the nearest neighbours
    # of a question with no answer in the corpus — plausible registration prose that never
    # mentions the thing. Citing them would be worse than citing nothing: it puts a source
    # link and a fetch date under an assertion the source does not support. This is the
    # cheap verification step that catches it, and the absence gets reported.
    must_mention: tuple[str, ...] = ()
    # Key into agent_tools.ALBERT_ONLY_TOPICS for the part Path Pilot cannot see.
    albert_topic: str | None = None
    # Identifiers that make the answer specific instead of generic.
    needs: tuple[str, ...] = ()
    # Causes this one is genuinely hard to tell apart from, and the question that does it.
    confusable_with: tuple[FailureReason, ...] = ()
    discriminator: str | None = None
    discriminator_why: str | None = None


# Shared between `financial_hold` and `other` so neither can win on generic hold text.
# Kept as a named constant because the tie is the design, and a future edit that adds one
# of these to only one of the two specs would silently turn ambiguity into a guess.
GENERIC_HOLD_CODES = ("ERR_HOLD_ACTIVE", "ERR_HOLD")
GENERIC_HOLD_PHRASES = (
    "hold on your record",
    "hold on my record",
    "have a hold",
    "hold*prevent",
    "registration blocked",
    "registration is blocked",
    "negative service indicator",
    "service indicator",
)


SPECS: tuple[ReasonSpec, ...] = (
    ReasonSpec(
        reason=FailureReason.prerequisite_not_met,
        label="A prerequisite the system did not see as met",
        reading=(
            "The enrollment system checked this class's prerequisites against your record "
            "and did not find them satisfied."
        ),
        codes=("ERR_PREREQ", "ERR_REQUISITE"),
        phrases=(
            # One gap pattern in place of four literals: it already covers "requisites not
            # met", "prerequisites not met", and the auxiliary-verb forms of both.
            "requisite*not met",
            "requirements not met for this class",
            "not meet the requisite",
            "pre-requisite not",
        ),
        keywords=("prerequisite", "requisite", "prereq"),
        office=Office.department,
        what_to_do=(
            "Compare the class's prerequisite line — quoted below from the bulletin — "
            "against the courses you have actually completed.",
            "If you completed the prerequisite, the enrollment system may not have it: "
            "a transfer credit or an in-progress course is the usual reason.",
            "If you have not completed it, an exception comes from the program, not from "
            "the registration screen. Ask your advisor about a prerequisite waiver.",
        ),
        policy_query="course prerequisites are required before registering",
        must_mention=("prerequisit", "requisit"),
        albert_topic="registration_errors",
        needs=("course_code",),
        confusable_with=(FailureReason.permission_required,),
        discriminator=(
            "In Albert's listing for the class, does it name prerequisite courses, or "
            "does it say consent or permission is required?"
        ),
        discriminator_why=(
            "Both refusals read as 'you are not eligible', but one is settled by a "
            "transcript and the other by a person agreeing to let you in."
        ),
    ),
    ReasonSpec(
        reason=FailureReason.financial_hold,
        label="A financial hold",
        reading=(
            "A hold tied to money owed or to your student account is stopping the "
            "enrollment from going through."
        ),
        codes=GENERIC_HOLD_CODES,
        phrases=GENERIC_HOLD_PHRASES
        + (
            "financial hold",
            "bursar hold",
            "past due",
            "past-due balance",
            "outstanding balance",
            "unpaid balance",
            "tuition balance",
            "student account hold",
            "financial aid hold",
            "aid hold",
        ),
        keywords=("balance", "bursar", "tuition", "payment", "unpaid"),
        office=Office.bursar,
        what_to_do=(
            "Open the hold in Albert and read which office placed it — only that office "
            "can remove it.",
            "Settle or dispute the amount with that office; the hold is released by them, "
            "not by retrying enrollment.",
            "Seats are not held while you resolve it, so do this before your appointment "
            "if you can.",
        ),
        policy_query="I paid my balance, when does the financial hold come off",
        # "holds" plural, not "hold": the singular is a common verb, and the bare stem
        # grounded a passage about holding student government positions. Measured, not
        # theorised — the false ground showed up on the first real query.
        must_mention=("holds", "balance", "bursar", "payment"),
        albert_topic="holds",
        confusable_with=(FailureReason.other,),
        discriminator=(
            "In Albert, which office does the hold name — Bursar or Financial Aid, or "
            "somewhere else like advising, the health service, or a department?"
        ),
        discriminator_why=(
            "Only the office that placed a hold can lift it, and the message you pasted "
            "does not say which one did. Paying a balance will not clear an advising hold."
        ),
    ),
    ReasonSpec(
        reason=FailureReason.time_conflict,
        label="A time conflict with another class",
        reading=(
            "The meeting time of this class overlaps something already on your schedule, "
            "so the system refused the addition."
        ),
        codes=("ERR_CONFLICT", "ERR_TIME"),
        phrases=(
            "time conflict",
            "meeting time conflict",
            "schedule conflict",
            "conflicts with class",
            "time scheduling conflict",
            "there is a conflict with",
        ),
        keywords=("conflict", "overlaps"),
        office=Office.registrar,
        what_to_do=(
            "Find the other class in the message — the number identifies what it collides "
            "with — and check both meeting patterns in Albert.",
            "Look for another section of either class before asking anyone to override it.",
            "Overlapping enrollment normally needs written approval; your advisor or the "
            "department starts that.",
        ),
        policy_query="two of my classes meet at the same time, can I enroll in both",
        must_mention=("conflict", "same time", "overlap"),
        albert_topic="registration_errors",
        needs=("class_number",),
    ),
    ReasonSpec(
        reason=FailureReason.section_full,
        label="The section has no room",
        reading="The section had reached its enrollment limit when you tried to add it.",
        codes=("ERR_CLOSED", "ERR_FULL"),
        phrases=(
            "class is full",
            "class full",
            "section is full",
            "closed class",
            "class closed",
            "section is closed",
            "no seats available",
            "enrollment limit reached",
            "is full",
        ),
        keywords=("full", "closed", "waitlist"),
        office=Office.department,
        what_to_do=(
            "Check whether the section has a waitlist and what joining one does — the "
            "bulletin text is quoted below.",
            "Look at the other sections of the same course before waiting.",
            "Seat counts move constantly during registration; a full section now is not "
            "necessarily full tomorrow.",
        ),
        policy_query="does joining a waitlist guarantee I get into the class",
        must_mention=("waitlist", "wait list", "closed", "capacity", "full"),
        albert_topic="seats",
        needs=("course_code",),
        confusable_with=(FailureReason.reserved_seat_restriction,),
        discriminator="Did Albert show open seats in the section when it refused you?",
        discriminator_why=(
            "A genuinely full section shows no seats. A reserved-seat restriction shows "
            "open seats you are not eligible for, and the two need different people to fix."
        ),
    ),
    ReasonSpec(
        reason=FailureReason.reserved_seat_restriction,
        label="Seats reserved for a different group",
        reading=(
            "The section's open seats are held for a group you are not in, so the system "
            "would not give you one."
        ),
        codes=("ERR_RESERVE", "ERR_RESRV"),
        phrases=(
            "reserved capacity",
            "reserve capacity requirement not met",
            "reserved capacity requirement not met",
            "seats are reserved",
            "reserved for students",
            "reserved seat",
        ),
        keywords=("reserved", "reservation"),
        office=Office.department,
        what_to_do=(
            "Read the section's reserved-seat note in Albert — it names the group the "
            "seats are held for.",
            "Reservations are often released close to the start of the term; ask the "
            "department when this one lifts.",
            "The department owns the reservation, so an exception has to come from them.",
        ),
        policy_query=(
            "the seats in this section are reserved for other students, can I still enroll"
        ),
        must_mention=("reserv",),
        albert_topic="seats",
        needs=("course_code",),
        confusable_with=(FailureReason.section_full, FailureReason.permission_required),
    ),
    ReasonSpec(
        reason=FailureReason.permission_required,
        label="Someone has to authorize the enrollment",
        reading=(
            "This class does not let you add yourself; it needs consent from the "
            "department or the instructor first."
        ),
        codes=("ERR_PERM", "ERR_CONSENT"),
        phrases=(
            "consent*required",
            "department consent",
            "instructor consent",
            "permission number",
            "permission*required",
            "requires*permission",
            "add authorization",
            "department approval required",
            "instructor approval",
        ),
        keywords=("consent", "permission", "authorization"),
        office=Office.department,
        what_to_do=(
            "Ask the department or the instructor for the permission — that is a person, "
            "not a setting you can change.",
            "Have your reason ready: which program you are in and why you need this class.",
            "Once granted, you still have to enroll yourself, and the seat is not held "
            "while you wait.",
        ),
        policy_query="I need department permission or a consent number to add this class",
        must_mention=("permission", "consent", "approval", "authoriz"),
        albert_topic="registration_errors",
        needs=("course_code",),
        confusable_with=(FailureReason.reserved_seat_restriction,),
    ),
    ReasonSpec(
        reason=FailureReason.appointment_not_open,
        label="Your registration window has not opened",
        reading=(
            "Nothing is wrong with the class or your record — the system will not take "
            "any enrollment from you until your assigned appointment starts."
        ),
        codes=("ERR_APPT",),
        phrases=(
            "enrollment appointment",
            "appointment has not begun",
            "not eligible to enroll at this time",
            "registration has not opened",
            "outside your enrollment appointment",
            "enrollment period has not",
            "cannot enroll at this time",
        ),
        keywords=("appointment",),
        office=Office.registrar,
        what_to_do=(
            "Look up your appointment date in Albert under Enrollment Dates and plan "
            "around it.",
            "Have your course list and any permission numbers ready before it opens — "
            "seats go quickly and nothing is reserved for you.",
            "Clear any holds first; a hold will stop you the moment the window opens.",
        ),
        policy_query=(
            "enrollment appointment times how they are assigned and when registration opens"
        ),
        must_mention=("appointment", "registration period", "registration opens", "enrollment date"),
        albert_topic="enrollment_appointment",
        needs=("term",),
    ),
    ReasonSpec(
        reason=FailureReason.max_credits_exceeded,
        label="The class would put you over the term credit limit",
        reading=(
            "Adding this class would take your enrolled credits for the term past the "
            "maximum the system allows without approval."
        ),
        codes=("ERR_MAXUNT", "ERR_UNITS"),
        phrases=(
            "maximum term unit",
            "unit load exceeded",
            "maximum unit load",
            "exceed*maximum",
            "maximum units",
            "credit limit",
            "exceeded the maximum number of units",
            "total units exceed",
        ),
        keywords=("overload", "units"),
        office=Office.advising,
        what_to_do=(
            "Add up what you are already enrolled in for the term, including anything "
            "waitlisted — waitlisted credits often count.",
            "Drop or defer one class, or ask your advisor about an overload approval.",
            "An overload is a judgement about your workload, so expect a conversation "
            "rather than a form.",
        ),
        policy_query=(
            "how many credits can I take in one term and how do I get an overload approved"
        ),
        must_mention=("overload", "credit load", "maximum credit", "unit load", "credits per"),
        albert_topic="registration_errors",
        needs=("term",),
    ),
    ReasonSpec(
        reason=FailureReason.duplicate_enrollment,
        label="You are already in this course",
        reading=(
            "The system sees an existing enrollment in the same course, so it treated this "
            "as a duplicate."
        ),
        codes=("ERR_DUPL",),
        phrases=(
            "already enrolled",
            "duplicate enrollment",
            "you are enrolled in this class",
            "already in your schedule",
            "duplicate of a class",
        ),
        keywords=("duplicate",),
        office=Office.registrar,
        what_to_do=(
            "Check your current schedule in Albert — a different section of the same "
            "course counts as the same course.",
            "If you meant to switch sections, use the swap function rather than adding "
            "the second one.",
            "If you are repeating the course deliberately, the rules for that are quoted "
            "below and usually need approval first.",
        ),
        policy_query="repeating a course already taken and duplicate enrollment rules",
        must_mention=("repeat", "duplicate", "already enrolled"),
        albert_topic="registration_errors",
        needs=("course_code",),
    ),
    ReasonSpec(
        reason=FailureReason.other,
        label="A hold or restriction the message does not identify",
        reading=(
            "Something on your record is blocking enrollment, and the message does not say "
            "which office put it there."
        ),
        codes=GENERIC_HOLD_CODES,
        phrases=GENERIC_HOLD_PHRASES,
        keywords=("hold", "blocked", "restricted", "restriction"),
        # No office on purpose: this cause exists precisely because the message did not
        # determine one, and filling it in with a plausible guess is the failure mode.
        office=None,
        what_to_do=(
            "Open Albert and read the hold itself — it names the office and what it wants.",
            "Contact that office directly; whoever placed it is the only one who can lift it.",
            "If nothing appears under Holds, the block may be a class-level restriction "
            "instead, and the section's notes in Albert will say so.",
        ),
        policy_query="I have a hold, does it stop me registering and who removes it",
        must_mention=("holds", "restrict", "block"),
        albert_topic="holds",
        confusable_with=(FailureReason.financial_hold,),
    ),
)

BY_REASON: dict[FailureReason, ReasonSpec] = {spec.reason: spec for spec in SPECS}


# The question that separates two confusable causes. Keyed by the unordered pair, because
# "which of these two is it" does not depend on which one happened to score higher.
def discriminating_question(
    a: FailureReason, b: FailureReason
) -> tuple[str, str] | None:
    """Return (question, why) for a confusable pair, or None if there is no scripted one."""
    for first, second in ((a, b), (b, a)):
        spec = BY_REASON[first]
        if second in spec.confusable_with and spec.discriminator:
            return (spec.discriminator, spec.discriminator_why or "")
    return None


# What each missing identifier is worth asking for, and why. `why` is shown to the
# student: a question with a visible purpose gets answered, a bare prompt gets abandoned.
SLOT_QUESTIONS: dict[str, tuple[str, str]] = {
    "course_code": (
        "Which course was it? A code like MASY1-GC 2100 is enough.",
        "With the code, the published prerequisites can be checked against the courses "
        "you have entered — without it, only the general rule applies.",
    ),
    "class_number": (
        "Which class number did the message mention?",
        "The number identifies the class you already have on your schedule that this one "
        "collides with.",
    ),
    "term": (
        "Which term were you registering for?",
        "Credit limits and registration windows are set per term, so the answer differs "
        "between them.",
    ),
}

__all__ = [
    "BY_REASON",
    "GENERIC_HOLD_CODES",
    "GENERIC_HOLD_PHRASES",
    "HOLD_CODE_NOTE",
    "SLOT_QUESTIONS",
    "SPECS",
    "ReasonSpec",
    "discriminating_question",
]
