"""
Unit tests for MockLLMService: deterministic text generation, empty context handling, and protocol adherence.
"""

import pytest

from app.services.llm import LLMService, MockLLMService


def test_mock_llm_implements_interface():
    """MockLLMService must be an instance of LLMService."""
    service = MockLLMService()
    assert isinstance(service, LLMService)


async def test_mock_llm_generates_deterministic_answer():
    """MockLLMService generates deterministic output referencing question and context files."""
    service = MockLLMService()
    prompt = (
        "=== BEGIN CODE CONTEXT ===\n"
        "[Source 1]\nFile: src/auth.py\nLines: 1-10\ndef login(): pass\n"
        "=== END CODE CONTEXT ===\n\n"
        "User Question: How does authentication work?"
    )

    ans1 = await service.generate(prompt)
    ans2 = await service.generate(prompt)

    assert ans1 == ans2
    assert "[MOCK LLM RESPONSE]" in ans1
    assert "src/auth.py" in ans1
    assert "How does authentication work?" in ans1


async def test_mock_llm_handles_empty_context():
    """When context is empty or contains placeholder, MockLLMService returns explicit empty notice."""
    service = MockLLMService()
    prompt = (
        "=== BEGIN CODE CONTEXT ===\n"
        "(No relevant code chunks found)\n"
        "=== END CODE CONTEXT ===\n\n"
        "User Question: What is this repo?"
    )

    ans = await service.generate(prompt)
    assert "[MOCK LLM RESPONSE]" in ans
    assert "No relevant repository context was found" in ans
