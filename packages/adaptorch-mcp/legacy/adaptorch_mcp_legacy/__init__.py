"""In-process engine bridge kept for maintainer parity tests.

These modules import the private ``adaptorch`` engine at module level, so they live
outside ``src/`` and are never part of the published ``adaptorch-mcp`` wheel. The
public client is ``adaptorch_mcp.thin_runtime``.
"""
