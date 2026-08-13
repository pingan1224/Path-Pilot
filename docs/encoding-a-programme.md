# Encoding a degree programme

How to add a programme to `ingest/requirements.py`, and the traps that have already cost
time. Twenty-two of the twenty-three SPS graduate degrees are encoded; the twenty-third
cannot be, for a reason worth reading before assuming it was skipped.

Encoding is hand work on purpose. The requirements table is prose and layout — an area
header, an indented list, a footnote that redefines "elective" — and a parser guessing at it
would be guessing at the thing the whole planner depends on.

## The procedure

1. **Read every section of the programme page, not the ones you expect.** Course groups are
   published under four different headings across the 23 pages: `Concentrations`,
   `Areas of Study`, `Tracks`, and `Specializations`. Query by excluding the known
   non-requirement sections (`Admissions`, `Learning Outcomes`, `Policies`,
   `Sample Plan of Study`) rather than by listing the ones you have seen.

2. **Transcribe into a `RequirementSpec` list** and add a `ProgramSpec` to `PROGRAMS`.

3. **Validate before writing**: `python -m ingest.requirements --dry-run --only <CODE>`.
   Every course code must exist in the catalogue and the credits must reconcile to the
   stated total. A set that does not add up is a transcription error and fails loudly.

4. **Write**: same command without `--dry-run`.

5. **Add the code to `ENCODED_PROGRAMS`** in `app/services/profile.py` *and* update the
   assertion in `tests/test_program_scope.py`. That test is written to fail on any change,
   so adding a programme is a decision rather than a side effect.

6. **Run the suite and the probes**: `pytest`, `scripts.authz_probe`,
   `scripts.mission_probe`.

## The four rule types, and which shape needs which

| Bulletin wording | Rule |
|---|---|
| A list with no choice in it | `all_of` |
| "Select N credits from the following" | `credits` with `min_courses` |
| "Select one of the following concentrations" | `one_track` |
| "…and complete three courses" (pool smaller than listed) | `one_track` + `TrackSpec(min_courses=…)` |
| "Required course X, then select five of the following" | `one_track` + `TrackSpec(required=[X], min_courses=5)` |
| Capstone stated as "A **or** B" | `one_track`, one course per track |

| "3 credits from each of the three areas, and 3 more from any" | one `credits` requirement per area, then one more for the extra — see below |

Judgements the wording does not make for you:

**A pool is not always worth enumerating.** Financial Planning lists five per concentration
and asks for three — naming the three describes the requirement. Global Security lists
thirty-eight and asks for five; naming five would be the tool choosing a degree plan nobody
asked it to choose, so that one stays a `credits` requirement with a placeholder in the
sequence. The line is roughly: a small surplus is a description, a large one is a
recommendation.

**Group headings are sometimes presentation.** Executive Coaching's "Module 1 / Module 2"
order a cohort's residencies rather than offering a choice, and Entrepreneurship's three
named specialisations are optional groupings of elective courses. Neither is a requirement,
and encoding them as tracks would invent a rule the bulletin does not state.

**Where the capstone lives.** Global Affairs and Public Relations list their capstones inside
the core table. Both are still encoded as their own `capstone` requirement, because that kind
is what tells the sequence planner a capstone needs a term to itself. The requirement kinds
describe the degree, not the page's layout. The converse also happens: neither Real Estate
degree states a capstone at all — the "Applied Project" that ends each concentration is a
course inside it — and inventing one would assert a structure the bulletin does not have.

**A pool of mixed credit values cannot state a course count.** Human Capital Management asks
for "6 credits" from a list running 1.5 to 3, which is two courses or four depending on
which. Those pools carry no `min_courses` and say so in the caveat. Only a uniform pool —
Project Management's seven 3-credit courses, HCAT's seven 1.5-credit ones — can state a
count. This is also why "Select six of the following: 9" is not a typo.

**Two rules the vocabulary cannot state, and which way to fail.** Integrated Marketing asks
for four courses from one concentration *or* three from one and one from another. Public
Relations does the same with its concentration electives. Both are encoded as the strict
reading, because the two ways of being wrong are not equivalent: a credit pool would accept
four courses from four different concentrations and call a student finished who is not, while
the strict reading tells a student on the mixed path that they owe a course they do not. The
second is recoverable — the caveat is carried verbatim into the finding, so they read the
bulletin's own sentence beside the tool's — and the first is the failure this engine exists
to prevent. When a rule cannot be stated exactly, fail toward "not yet" rather than "done".

## When two requirements share a pool

Global Affairs' electives are "additional credits from any of the concentrations" — the same
courses the concentration requirement is built from. Encode the union anyway; that is what
the bulletin says. The engine, not the encoding, is what keeps a course from being spent
twice: requirements are evaluated in the bulletin's order, each one takes the courses it
needs, and a `credits` pool counts only what is left (`planning.rules.courses_applied`).
Rules that name their courses are untouched by this — nothing can take a named course away
from the requirement that names it.

The failure this prevents is worth stating, because it looks like a pass: before it, a
student who had finished the core and a concentration — thirty of forty-two credits — was
told that only the thesis remained, and the sequence gave them a finish date a term early.

Publishing is the shape this makes possible. Its three Areas of Study are not a choice —
three credits are required from *each*, plus three more from any one of them, plus six
elective credits the page also allows to be drawn from the areas. That is four `credits`
requirements over overlapping pools, stated in the bulletin's order, and it is only correct
because each one spends what it takes: the areas take three each, the additional-credits
requirement sees what is left, the electives see what is left after that.

## Traps that have already bitten

**Course numbers are 1–4 digits.** `EMSC1-GC 10` through `300` are real codes. A four-digit
pattern read all seventeen of that catalogue as zero courses and reported success, because
every check in the parser fires on a course it half-understood and there was no course. A
page yielding zero courses is now itself an error.

**Credits are halves.** 129 courses are worth 1.5, and `Course.credits` /
`Requirement.min_credits` are floating point for that reason. Event Management's core
curriculum is 16.5. Integer truncation under-counted a degree and told students they owed
credits they had earned.

**Some courses have no fixed credit value.** Internship and Independent Study are commonly
published without one, and `MSEM1-GC 2050` is published as "1.5-3". Say so in the caveat
rather than picking a number.

**Prerequisites are sometimes stated as course titles.** Three capstones do this. Resolving
titles to codes is deliberately not attempted — a title can match courses under four
prefixes, the AND separator also occurs inside titles ("Quantitative Methods and Metrics"),
and the published text carries truncations. Those courses carry
`courses.prerequisite_unparsed` so the planner can say it cannot verify them.

**Prefixes are not degrees.** Real Estate and Real Estate Development share three course
prefixes; Global Affairs and Global Security share two. A degree's requirements can draw on
several catalogues, and these two name each other as legitimate sources of electives.

**A page can list a course that does not exist.** Real Estate Development's elective table
contains `DEVE1-GC 3024` with no title beside it and no entry in any course catalogue. It is
left out of the encoding and named in the caveat. Validation refuses a code it cannot find,
which is the right default — the fix is to say what was dropped, not to relax the check.

## What is left

Twenty-two of the twenty-three are encoded. The twenty-third is not a backlog item.

**The HCM/HCAT dual degree cannot be encoded from its page.** It states 45 credits, says
students complete the HCM degree and then the HCAT degree, and gives its learning outcomes as
the union of the two. It publishes no requirements table. Since HCM is 30 credits and HCAT is
30, something worth 15 credits is shared or waived, and the page does not say what. Encoding
it would mean inventing the overlap. It stays out of `ENCODED_PROGRAMS`, where it reads to a
student as "this tool cannot audit your programme" — which is true, and better than a
confident audit against requirements nobody published.

Overlapping options also cost the rule engine a distinction it did not have. Global Affairs'
eight concentrations share most of their courses, so one course "starts" six of them. That
now reads as "which option is not yet clear" rather than "courses spread across tracks",
which is reserved for a record no single option can account for. The verdict is the same
either way; the difference is whether a student is told they have done something they have
not.
