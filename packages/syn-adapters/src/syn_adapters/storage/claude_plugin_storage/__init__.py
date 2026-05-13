"""Claude plugin tree storage adapters (issue #726).

Stores claude plugin trees in object storage, content-addressed by sha256.

- minio.py: production / development (S3-compatible)
- memory.py: unit tests only (inherits InMemoryAdapter)
- factory.py: env-driven adapter selection
"""
