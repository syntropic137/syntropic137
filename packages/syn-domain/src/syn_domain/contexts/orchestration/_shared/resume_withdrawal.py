"""The refusal a resumed child's start raises when its parent withdrew the resume (#1677).

Shared because two slices meet on it: ``execute_workflow`` opens the child and
raises it, ``start_resume`` asked for the start and settles it.
"""

from __future__ import annotations


class ResumeWithdrawnError(Exception):
    """A resumed child opened after its parent's resume was withdrawn (#1677).

    The child is recorded cancelled before this is raised, so it never runs.
    """
