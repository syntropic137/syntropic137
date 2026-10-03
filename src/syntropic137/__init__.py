"""Syntropic137 - workspace root."""

#: NO ``__version__`` HERE. This package had one, hardcoded "0.3.0", while its
#: pyproject.toml said 0.29.0 - a second home for the release number that
#: `just bump-version` does not write and therefore could only ever be wrong.
#: That is the drift #1380 is about; the packages that must REPORT a running
#: build (syn-api, syn-collector) read it from importlib.metadata through one
#: accessor, and a library that reports nothing does not need a copy at all.
