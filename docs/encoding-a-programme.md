# Encoding a degree programme

How to add a programme to `ingest/requirements.py`, and the traps that have already cost
time. Eight of twenty-three SPS graduate degrees are encoded; the rest are the same work
repeated, which is why this is written down.

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

Two judgements the wording does not make for you:

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

**Where the capstone lives.** Global Affairs lists its thesis inside the core table. It is
still encoded as its own `capstone` requirement, because that kind is what tells the
sequence planner a capstone needs a term to itself. The requirement kinds describe the
degree, not the page's layout.

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
several catalogues.

## What is left

Encoded: Management and Analytics, Financial Planning, Global Security, Entrepreneurship and
Management, Event Management, Executive Coaching, Marketing and Strategic Communications,
Global Affairs.

Not yet encoded: Global Hospitality, Global Sport, Human Capital Management, Human Capital
Analytics and Technology, the HCM/HCAT dual degree, Integrated Marketing, Professional
Writing, Project Management, Public Relations and Corporate Communication, Publishing, Real
Estate, Real Estate Development, Sports Business, Translation and Interpreting, Travel and
Tourism Management.

Overlapping options also cost the rule engine a distinction it did not have. Global Affairs'
eight concentrations share most of their courses, so one course "starts" six of them. That
now reads as "which option is not yet clear" rather than "courses spread across tracks",
which is reserved for a record no single option can account for. The verdict is the same
either way; the difference is whether a student is told they have done something they have
not.
