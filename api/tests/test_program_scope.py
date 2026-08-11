"""A student is planned against their own program's rules, or against none at all.

Until 2026-08-11 `program_code` defaulted to a single hardcoded constant in three services,
and nothing above them ever passed anything else — there was no per-user program to pass.
Every real user was therefore audited against Management & Analytics MS whether or not they
were enrolled in it, and the answer came back correctly cited and confidently wrong.

These tests are the program-level analogue of the cross-school and cross-student probes:
the boundary is architectural (no caller can reach another program's rules without naming
its code), and this is what keeps that claim honest as programs are added.

Pure unit tests over a stubbed session — the resolution logic is the thing under test, not
SQLAlchemy.
"""

import pytest

from app.services import profile as profile_service
from app.services.profile import (
    ENCODED_PROGRAMS,
    ProgramNotStatedError,
    UserProgram,
    program_for_user,
)


class _Program:
    def __init__(self, code, name="A Program", school="School of Professional Studies",
                 level="graduate"):
        self.code = code
        self.name = name
        self.school = school
        self.level = level


class _User:
    def __init__(self, program=None):
        self.program = program


class _Session:
    """Just enough of a Session: `get` returns the user, `scalars` the student (or none)."""

    def __init__(self, user, student=None):
        self._user = user
        self._student = student

    def get(self, _model, _pk):
        return self._user

    def scalars(self, _stmt):
        student = self._student

        class _Result:
            def first(self):
                return student

        return _Result()


def _resolve(user, student=None):
    return program_for_user(_Session(user, student), user_id=1)


def test_live_user_resolves_from_their_own_program():
    program = _Program("SOMETHING-ELSE", name="Applied Urban Science", level="undergraduate")
    resolved = _resolve(_User(program))

    assert resolved.code == "SOMETHING-ELSE"
    assert resolved.level == "undergraduate"


def test_demo_user_falls_back_to_the_student_fixture():
    """A seeded account carries its program on the Student row, not on the user."""

    class _Student:
        program = _Program("MASY-MS-REAL")

    resolved = _resolve(_User(program=None), student=_Student())
    assert resolved.code == "MASY-MS-REAL"


def test_a_user_who_stated_nothing_raises_rather_than_defaulting():
    """The failure mode this whole change exists to prevent.

    The tempting behaviour is to fall back to the one encoded program. That produces a
    fully-cited degree audit against a degree the student is not enrolled in, and nothing
    downstream can detect it — the rules are real, the courses are real, the answer is
    about someone else's program.
    """
    with pytest.raises(ProgramNotStatedError):
        _resolve(_User(program=None), student=None)


def test_an_unencoded_program_is_reported_not_substituted():
    resolved = _resolve(_User(_Program("URBAN-BS", name="Applied Urban Science BS")))

    assert resolved.is_encoded is False
    # The point: it still resolves to the student's *own* program. Nothing silently
    # rewrites it to an encoded one.
    assert resolved.code == "URBAN-BS"


def test_encoded_programs_is_a_gate_not_a_default():
    """Membership decides whether audit features are offered, never which rules are used."""
    encoded = _resolve(_User(_Program(sorted(ENCODED_PROGRAMS)[0])))
    assert encoded.is_encoded is True


def test_scope_carries_level_so_undergraduates_are_not_scoped_as_graduates():
    """Level used to be inferred as `degree in ("MS", "MA", "PhD")`, reading every
    undergraduate program as graduate. Level is half the retrieval scope, so that
    inference hands an undergraduate the graduate credit-load rules with a real citation
    attached — the wrong-level twin of the cross-school failure."""
    undergrad = _resolve(_User(_Program("URBAN-BS", level="undergraduate")))

    assert undergrad.scope.level == "undergraduate"
    assert undergrad.scope.school == "professional-studies"


def test_an_unmapped_school_yields_no_scope_signal_rather_than_a_wrong_one():
    resolved = _resolve(_User(_Program("X", school="Some School Not In The Corpus")))

    # None means "no signal either way" and must never be read as a match.
    assert resolved.corpus_slug is None
    assert resolved.scope.school is None


def test_unencoded_program_is_not_silently_added_to_the_gate():
    """A guard on the gate itself: growing ENCODED_PROGRAMS is hand work that follows
    encoding and validating a program's requirements (see ingest/requirements.py on why a
    parser is not acceptable). A name appearing here without that work is the bug."""
    assert ENCODED_PROGRAMS == frozenset({"MASY-MS-REAL"}), (
        "ENCODED_PROGRAMS changed. Confirm the new program's requirements are actually "
        "encoded and validated, then update this assertion."
    )
