"""The leakage probes have to be able to detect a leak.

A probe phrase that student-visible policy also states cannot tell a leak from an honest
answer — and it does not fail quietly, it reports a *leak*, which sends the reader looking
for a breach in the tool layer that never happened. That is what B24 did on 2026-08-07:
it read the public SPS residency policy, cited it, paraphrased "a maximum of two courses
may be substituted" as "a maximum of two substitutions allowed", and tripped a probe whose
phrase had been unique to the restricted fixture back when the corpus was 15 hand-written
chunks.

These tests cover the mechanical half of the check. The substantive half — a phrase the
corpus does not contain but does license by paraphrase — is a judgement recorded in the
comment above OVERRIDE_LEAK, and the last test here is that specific case pinned down.
"""

from eval.golden import OVERRIDE_LEAK, validate_leak_phrases


class FakeSession:
    """Stands in for the corpus query in validate_leak_phrases."""

    def __init__(self, chunks):
        self._chunks = chunks

    def execute(self, _statement):
        return self

    def all(self):
        return [(text,) for text in self._chunks]


def test_a_phrase_the_public_corpus_states_is_reported():
    session = FakeSession(["Advisors may act without department sign-off in some cases."])
    problems = validate_leak_phrases(session)
    assert any("without department sign-off" in p for p in problems)


def test_a_phrase_absent_from_the_public_corpus_passes():
    session = FakeSession(["Students should discuss substitutions with their adviser."])
    assert validate_leak_phrases(session) == []


def test_the_check_is_case_insensitive():
    """Policy pages capitalise headings; a leak does not stop being one in title case."""
    session = FakeSession(["Denied Appeal Procedures"])
    assert any("denied appeal" in p for p in validate_leak_phrases(session))


def test_the_report_names_the_case_so_the_stale_probe_is_findable():
    session = FakeSession(["... denied appeal ..."])
    problems = validate_leak_phrases(session)
    assert problems and all(p.split(":")[0].startswith("B") for p in problems)


def test_the_public_substitution_rule_no_longer_trips_a_probe():
    """The exact sentence that caused the false leak, verbatim from chunk 4689.

    A regression test on the probe set rather than on the system: if someone re-adds a
    phrase that this public passage states or plainly licenses, this fails.
    """
    public = (
        "Students who can demonstrate advanced competency of the subject matter in any of "
        "the core courses offered at NYU-SPS should discuss course substitutions with the "
        "program adviser during the first semester as a matriculated student: a maximum of "
        "two courses may be substituted. Substitutions do not reduce the number of credits "
        "required, but allow students to take electives in their place."
    )
    assert validate_leak_phrases(FakeSession([public])) == []
    # And the substance bar, which no validator can check: none of the surviving phrases
    # is about how many substitutions are allowed, because public policy answers that.
    assert not any("two" in phrase for phrase in OVERRIDE_LEAK)
