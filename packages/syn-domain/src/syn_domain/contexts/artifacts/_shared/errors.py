"""Errors in the artifacts context's own language, importable from its domain."""

from __future__ import annotations


class ArtifactStorageError(Exception):
    """An artifact's content could not be stored or retrieved.

    The port's failure contract, declared here so callers can name it. Without
    it the only honest catch at a call site is ``except Exception``, which also
    swallows the caller's own bugs - a typo in a keyword argument reads exactly
    like a backend outage and degrades just as quietly. Implementations raise
    this or a subclass for every failure that is the storage's, and let
    everything else through.

    Lives in ``_shared`` rather than ``ports/`` so the domain's own query
    service can name it when it reads a binary artifact's bytes (#990): the
    domain may not import from ``ports/``. The port module re-exports it.
    """
