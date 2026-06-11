"""Shared cryptographic type aliases used across backend layers."""

from __future__ import annotations

from typing import NewType

# Distinct type for encrypted ciphertext strings, so plaintext and ciphertext
# cannot be silently interchanged at call sites.  NewType is transparent at
# runtime (Ciphertext is str), but mypy/basedpyright treat it as a separate type.
Ciphertext = NewType("Ciphertext", str)
