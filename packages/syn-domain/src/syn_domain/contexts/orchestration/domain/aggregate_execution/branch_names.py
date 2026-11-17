"""Stand-ins written where a branch name goes when the workspace was on none.

They are for a reader, and they are persisted: `BranchObservation.branch` and
`QuarantinedRef.branch` (on `WorkflowFailedEvent`) both carry them. So a
consumer that uses either field as a git ref must recognise them first, since
no ref by either name can exist. Asking GitHub for one 404'd once a minute,
forever (#1870).
"""

from __future__ import annotations

from typing import Final

DETACHED_HEAD: Final = "(detached HEAD)"
NO_COMMITS: Final = "(no commits)"
NOT_A_BRANCH: Final = frozenset({DETACHED_HEAD, NO_COMMITS})
