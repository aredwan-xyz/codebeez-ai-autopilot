"""Tests must explicitly mock provider calls and cannot use real credentials."""

import pytest

from src.utils.llm import LLMClient


@pytest.fixture(autouse=True)
def prohibit_unmocked_llm(monkeypatch):
    async def blocked(*args, **kwargs):
        raise AssertionError("Test attempted an unmocked LLM request")

    monkeypatch.setattr(LLMClient, "complete", blocked)
