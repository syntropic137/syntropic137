"""AEF API — Programmatic interface to the Agentic Engineering Framework.

Usage:
    import aef_api

    result = await aef_api.v1.workflows.list_workflows()
    match result:
        case Ok(workflows):
            for wf in workflows:
                print(wf.name)
        case Err(error):
            print(f"Error: {error}")
"""

from aef_api import v1
from aef_api.auth import AuthContext
from aef_api.types import Err, Ok, Result

__all__ = ["AuthContext", "Err", "Ok", "Result", "v1"]
__version__ = "0.1.0"
