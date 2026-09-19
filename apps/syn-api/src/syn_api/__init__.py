"""Syn137 API — Programmatic interface to the Syntropic137.

Usage:
    from syn_api.routes.workflows import list_workflows

    result = await list_workflows()
    match result:
        case Ok(workflows):
            for wf in workflows:
                print(wf.name)
        case Err(error):
            print(f"Error: {error}")
"""

from syn_api.build_info import get_build_info
from syn_api.types import Err, Ok, Result

__all__ = ["Err", "Ok", "Result"]

#: The installed release, not a literal. This was "0.1.0" - a third spelling of
#: this package's version, disagreeing with both pyproject.toml and the "0.5.1"
#: that main.py served - and `scripts/import_check.py` prints it, so the wrong
#: number was being reported to a human every time that ran (#1380).
__version__ = get_build_info().version
