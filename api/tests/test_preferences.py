"""What the student wants, kept apart from what the product assumed.

Two properties, and the second is the one with teeth.

**Unset is a real answer.** Nothing here carries a default, because a row that quietly
reads "as soon as possible" would put words in a student's mouth and then solve against
them. A missing row and an empty one mean the same thing and neither is written on read.

**A value's source travels with it.** The solver needs a credit cap and a deadline either
way, so without this the answer cannot tell a number the student chose from one the
product guessed — and it discloses the guess on screen as "assumed, not a rule", which
only means anything if the two are distinguishable. The ingested corpus has per-term caps
for Stern's MBA alone; quoting one at an SPS student is precisely the failure the
home-school retrieval boost exists to prevent, and it would be worse buried in a
constraint than visible as a citation.
"""

import pytest
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import Program, User, UserPreferences
from app.sequence.service import sequence_for_user
from app.sequence.terms import Term
from app.services.profile import get_preferences, set_preferences

PROBE_EMAIL = "live.probe@pathpilot.example.edu"


def _db_available() -> bool:
    try:
        with get_sessionmaker()() as session:
            session.scalar(select(User.id).limit(1))
        return True
    except Exception:  # noqa: BLE001 — the suite must skip, not fail, without a database
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="needs the seeded dev database"
)


@pytest.fixture
def user_id():
    with get_sessionmaker()() as session:
        user = session.scalars(select(User).where(User.email == PROBE_EMAIL)).first()
        if user is None:
            pytest.skip("live probe account is not seeded")
        uid, original = user.id, user.program_id
        program_id = session.scalar(
            select(Program.id).where(
                Program.code == "MASY-MS-REAL", Program.source == "catalog"
            )
        )
        if program_id is None:
            pytest.skip("catalog programmes are not ingested")
        user.program_id = program_id
        session.commit()
        _clear(session, uid)
    try:
        yield uid
    finally:
        with get_sessionmaker()() as session:
            _clear(session, uid)
            user = session.scalars(select(User).where(User.email == PROBE_EMAIL)).first()
            user.program_id = original
            session.commit()


def _clear(session, uid: int) -> None:
    row = session.scalars(
        select(UserPreferences).where(UserPreferences.user_id == uid)
    ).first()
    if row is not None:
        session.delete(row)
        session.commit()


def test_saying_nothing_is_stored_as_nothing(user_id):
    """No row is created on read, and every field reads as unsaid."""
    with get_sessionmaker()() as session:
        prefs = get_preferences(session, user_id)
        assert prefs.is_empty
        assert prefs.target_finish_term is None
        assert prefs.max_credits_per_term is None
        assert prefs.summers_ok is None
        assert session.scalar(
            select(UserPreferences.id).where(UserPreferences.user_id == user_id)
        ) is None


def test_saving_one_preference_does_not_forget_the_others(user_id):
    """Three unrelated intentions share this row; a partial update must stay partial."""
    with get_sessionmaker()() as session:
        set_preferences(session, user_id, target_finish_term="Spring 2028")
        set_preferences(session, user_id, max_credits_per_term=6)
        prefs = get_preferences(session, user_id)

    assert prefs.target_finish_term == "Spring 2028"
    assert prefs.max_credits_per_term == 6


def test_an_explicit_none_still_clears(user_id):
    """"Unchanged" must not cost the caller the ability to take something back."""
    with get_sessionmaker()() as session:
        set_preferences(session, user_id, target_finish_term="Spring 2028")
        set_preferences(session, user_id, target_finish_term=None)
        assert get_preferences(session, user_id).target_finish_term is None


def test_the_cap_reports_which_of_the_three_it_used(user_id):
    """request beats saved beats assumed, and the answer says which."""
    with get_sessionmaker()() as session:
        _, meta = sequence_for_user(session, user_id)
        assert meta["credit_cap_source"] == "assumed"
        assert meta["credit_cap_was_assumed"] is True

        set_preferences(session, user_id, max_credits_per_term=6)
        _, meta = sequence_for_user(session, user_id)
        assert meta["credit_cap_source"] == "saved"
        assert meta["max_credits_per_term"] == 6
        # A saved value is the student's decision, not the product's guess. The screen
        # labels the guess "assumed, not a rule"; mislabelling theirs as assumed would
        # undersell a choice they made, and the reverse would dress a guess as a decision.
        assert meta["credit_cap_was_assumed"] is False
        assert meta["preferences_updated_at"], "a saved value carries the date it was said"

        _, meta = sequence_for_user(session, user_id, max_credits_per_term=12)
        assert meta["credit_cap_source"] == "request"
        assert meta["max_credits_per_term"] == 12


def test_a_saved_finish_term_becomes_the_deadline(user_id):
    with get_sessionmaker()() as session:
        _, meta = sequence_for_user(session, user_id)
        assert meta["deadline"] is None
        assert meta["deadline_source"] is None

        set_preferences(session, user_id, target_finish_term="Spring 2029")
        _, meta = sequence_for_user(session, user_id)

    assert meta["deadline"] == "Spring 2029"
    assert meta["deadline_source"] == "saved"


def test_a_named_deadline_beats_the_saved_one(user_id):
    """Asking a question is not the same as changing your mind about the answer."""
    with get_sessionmaker()() as session:
        set_preferences(session, user_id, target_finish_term="Spring 2029")
        _, meta = sequence_for_user(
            session, user_id, deadline=Term.parse("Fall 2027")
        )
        assert meta["deadline"] == "Fall 2027"
        assert meta["deadline_source"] == "request"
        # And the saved one is untouched: a what-if is not a write.
        assert get_preferences(session, user_id).target_finish_term == "Spring 2029"


def test_the_assumed_start_says_so(user_id):
    """The cap was labelled a guess and the start was not, three inches apart."""
    with get_sessionmaker()() as session:
        _, meta = sequence_for_user(session, user_id)
        assert meta["start_was_assumed"] is True

        _, meta = sequence_for_user(session, user_id, start_term=Term.parse("Fall 2027"))
        assert meta["start_was_assumed"] is False
        assert meta["start_term"] == "Fall 2027"
