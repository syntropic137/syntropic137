"""Syn137 API — Programmatic interface to the Syntropic137.

Usage:
    import syn_api

    result = await syn_api.v1.workflows.list_workflows()
    match result:
        case Ok(workflows):
            for wf in workflows:
                print(wf.name)
        case Err(error):
            print(f"Error: {error}")
"""

from syn_api import v1
from syn_api.auth import AuthContext
from syn_api.types import Err, Ok, Result

__all__ = ["AuthContext", "Err", "Ok", "Result", "v1"]
__version__ = "0.1.0"
