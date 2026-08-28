#!/usr/bin/env python3
"""Entry point for ``just doctor``.

The implementation lives in ``syn_shared.doctor`` rather than here on purpose:
``scripts/`` is excluded from pytest ``testpaths`` (see
``scripts/test_testpaths_coverage.py`` and issue #858), so a module in this
directory cannot be covered by the suite. ``packages/syn-shared/tests`` is a
testpath, so the logic is tested there and this file stays a two-line shim.
"""

from __future__ import annotations

import sys

from syn_shared.doctor import main

if __name__ == "__main__":
    sys.exit(main())
