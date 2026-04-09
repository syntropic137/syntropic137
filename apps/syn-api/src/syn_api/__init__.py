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

from syn_api.types import Err, Ok, Result

__all__ = ["Err", "Ok", "Result"]
__version__ = "0.1.0"
