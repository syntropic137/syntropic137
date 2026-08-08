"""Skill tree storage adapters (issue #772).

Stores skill trees in object storage, content-addressed by sha256.

- minio.py: production / development (S3-compatible)
- memory.py: unit tests only (inherits InMemoryAdapter)
- factory.py: env-driven adapter selection
"""
