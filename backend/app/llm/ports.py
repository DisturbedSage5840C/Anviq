"""What the AI modules need from a model client, so tests can swap in a scripted one."""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from app.llm.client import Reply, SystemBlock

T = TypeVar("T", bound=BaseModel)


class StructuredClient(Protocol):
    async def complete_json(
        self,
        purpose: str,
        *,
        model: str,
        system: Sequence[SystemBlock],
        messages: Sequence[Mapping[str, Any]],
        schema: type[T],
        max_tokens: int = 1024,
    ) -> T: ...


class TextClient(Protocol):
    async def complete_text(
        self,
        purpose: str,
        *,
        model: str,
        system: Sequence[SystemBlock],
        messages: Sequence[Mapping[str, Any]],
        max_tokens: int = 512,
    ) -> str: ...


class RawClient(Protocol):
    async def complete(
        self,
        purpose: str,
        *,
        model: str,
        system: Sequence[SystemBlock],
        messages: Sequence[Mapping[str, Any]],
        max_tokens: int = 1024,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: Mapping[str, Any] | None = None,
    ) -> Reply: ...
