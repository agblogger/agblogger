"""Label-related schemas."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

LABEL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

LabelIdRef = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")]


def _validate_nonempty_names(v: list[str]) -> list[str]:
    """Reject empty or whitespace-only display name strings."""
    for name in v:
        if not name.strip():
            raise ValueError("Display names must not be empty or whitespace-only")
    return v


class LabelResponse(BaseModel):
    """Label detail response."""

    id: str
    names: list[str] = Field(default_factory=list)
    is_implicit: bool = False
    parents: list[str] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)
    post_count: int = Field(default=0, ge=0)


class LabelGraphNode(BaseModel):
    """Node in the label DAG for visualization."""

    id: str
    names: list[str] = Field(default_factory=list)
    post_count: int = Field(default=0, ge=0)


class LabelGraphEdge(BaseModel):
    """Edge in the label DAG."""

    source: str  # child label_id
    target: str  # parent label_id


class LabelGraphResponse(BaseModel):
    """Full label DAG for graph visualization."""

    nodes: list[LabelGraphNode]
    edges: list[LabelGraphEdge]


class LabelCreate(BaseModel):
    """Request to create a new label."""

    id: LabelIdRef
    names: list[str] = Field(default_factory=list)
    parents: list[LabelIdRef] = Field(default_factory=list)

    @field_validator("names")
    @classmethod
    def names_must_be_nonempty_strings(cls, v: list[str]) -> list[str]:
        """Reject empty or whitespace-only name strings."""
        return _validate_nonempty_names(v)


class LabelUpdate(BaseModel):
    """Request to update a label's names and parents."""

    names: list[str] = Field(default_factory=list)
    parents: list[LabelIdRef] = Field(default_factory=list)

    @field_validator("names")
    @classmethod
    def names_must_be_nonempty_strings(cls, v: list[str]) -> list[str]:
        """Reject empty or whitespace-only name strings."""
        return _validate_nonempty_names(v)


class LabelDeleteResponse(BaseModel):
    """Response after deleting a label."""

    id: str
    deleted: bool = True
