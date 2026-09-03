# ORC — read CLAUDE.md

The constitution of this project is **`CLAUDE.md`**. Read that file.

This file exists because the Codex CLI looks for `AGENTS.md` the way Claude Code
looks for `CLAUDE.md`, and a review step here may be answered by either vendor.

It is a POINTER, never a copy. It was a copy once: the constitution was
duplicated into it verbatim, 193 lines, by a review step that was supposed to be
read-only. Two copies of a protocol document is how a protocol rots -- one of
them gets an amendment and nothing tells the other. `tests/test_protocol.py::
test_the_agent_pointer_is_not_a_second_constitution` fails if this file ever
grows a copy again.
