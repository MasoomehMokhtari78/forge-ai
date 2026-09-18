"""
LLM service abstraction and deterministic mock implementation for Phase 4 RAG.
"""

from abc import ABC, abstractmethod
import re


class LLMService(ABC):
    """Abstract interface for Language Model text generation."""

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """Generate a text response given a structured prompt."""
        pass


class MockLLMService(LLMService):
    """Deterministic mock LLM provider for tests, local development, and Phase 4.

    Constraints:
      - Zero network calls / zero credentials.
      - Never accesses the database.
      - Does not attempt to generate authoritative citations (citations are
        strictly constructed by the RAG orchestrator from chunk metadata).
      - Returns reproducible, deterministic text based solely on the prompt.
    """

    async def generate(self, prompt: str) -> str:
        # Check if the prompt contains context
        context_match = re.search(
            r"=== BEGIN CODE CONTEXT ===\s*(.*?)\s*=== END CODE CONTEXT ===",
            prompt,
            re.DOTALL,
        )
        context_body = context_match.group(1).strip() if context_match else ""

        if not context_body or "(No relevant code chunks found)" in context_body:
            return (
                "[MOCK LLM RESPONSE] No relevant repository context was found to "
                "answer this question."
            )

        # Extract user question from prompt
        question_match = re.search(r"User Question:\s*(.*?)$", prompt, re.DOTALL)
        question = question_match.group(1).strip() if question_match else "the question"

        # Deterministically extract the first few source references mentioned in the context text
        # for human-readable answer context, without fabricating or inventing references
        source_headers = re.findall(r"\[Source \d+\]\s*File:\s*([^\n]+)", context_body)
        files_summary = ", ".join(source_headers[:3]) if source_headers else "the provided files"

        return (
            f"[MOCK LLM RESPONSE] Based on the provided repository context ({files_summary}), "
            f"here is the information addressing '{question}':\n\n"
            f"The codebase contains relevant definitions and configuration in {files_summary}. "
            f"Refer to the cited source blocks for exact implementation details."
        )


def get_default_llm_service() -> LLMService:
    """Factory to provide the active LLM service."""
    return MockLLMService()
