You are reviewing the evaluation kernel of the ORC research project. Every
result the project has produced depends on this code being right, and a defect
here is silent by nature: it does not crash, it returns a plausible number.

Six such defects were found on 2026-09-02, all of them by accident rather than
by review. They are the pattern to look for.

- Funding settlements past the end of a panel were folded onto its final bar by
  searchsorted, putting sealed data into the development window.
- The code hash read raw bytes, so CRLF and LF checkouts of the same commit
  hashed differently and no trial ever deduped across platforms.
- A verdict reported cells as surviving without ever checking they were above
  break-even.
- A check that could not run was recorded as a failure rather than as
  unmeasured, hiding a hole in the gate behind a result that looked like the
  gate working.
- The overfitting check ran on whichever symbols the dictionary happened to
  hold first, skipping the top-ranked cell.
- A full panel build only ever wrote files, so a stale panel from an earlier
  source survived in the directory with no QA record behind it.

Read these files and look for anything of the same kind:

{files}

You are looking for silent divergences, not style. Concretely: places where an
index or a boundary is off by one and the result stays plausible; where a
future value can reach a past decision; where a NaN, an empty array or a
division by zero yields a number instead of an error; where two code paths that
should agree can disagree; where an identity or a hash depends on something
incidental; where an error is caught and turned into a value that reads as a
result.

For each finding, say what specifically goes wrong and construct the concrete
input that triggers it. A finding you cannot make concrete is a guess, and a
guess in this list makes the whole list less useful.

Reply with one JSON object and nothing else, with exactly these keys:
findings (a list, each item an object with keys file, line, severity being high
medium or low, what being the defect in one sentence, trigger being the
concrete input or state that produces it, and why_silent being why it returns a
plausible number instead of failing), reviewed (the list of files you actually
read), confidence (high, medium or low).

An empty findings list is a valid and useful answer. Do not invent findings to
fill it.
