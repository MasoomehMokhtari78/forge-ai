"""
LLM service abstraction and providers for ForgeAI RAG (Mock and Ollama).
"""

from abc import ABC, abstractmethod
import logging
import re
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService(ABC):
    """Abstract interface for Language Model text generation."""

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """Generate a text response given a structured prompt."""
        pass


class MockLLMService(LLMService):
    """Deterministic mock LLM provider for tests, local development, and CI.

    Constraints:
      - Zero network calls / zero credentials.
      - Never accesses the database.
      - Citations are constructed strictly by RAG orchestrator from chunk metadata.
      - Returns reproducible, deterministic text based solely on the prompt.
    """

    async def generate(self, prompt: str) -> str:
        # Check if this is a Knowledge-Guided Analysis prompt
        if "## Repository Evidence" in prompt and "## Engineering Knowledge" in prompt:
            repo_match = re.search(
                r"## Repository Evidence\s*(.*?)\s*## Engineering Knowledge",
                prompt,
                re.DOTALL,
            )
            repo_body = repo_match.group(1).strip() if repo_match else ""

            if not repo_body or "(No relevant repository code chunks found)" in repo_body:
                return (
                    "[MOCK LLM RESPONSE] I could not find enough relevant repository evidence to "
                    "make a grounded recommendation about this implementation."
                )

            knowledge_match = re.search(
                r"## Engineering Knowledge\s*(.*?)\s*## User Question",
                prompt,
                re.DOTALL,
            )
            knowledge_body = knowledge_match.group(1).strip() if knowledge_match else ""

            if not knowledge_body or "(No relevant engineering knowledge found)" in knowledge_body:
                return (
                    "[MOCK LLM RESPONSE] The selected knowledge scope does not provide enough "
                    "evidence to support a recommendation for this question."
                )

            question_match = re.search(r"## User Question\s*(.*?)$", prompt, re.DOTALL)
            question = question_match.group(1).strip() if question_match else "the question"

            repo_sources = re.findall(r"\[source\s+([a-zA-Z0-9_]+)\]", repo_body)
            knowledge_sources = re.findall(r"\[source\s+([a-zA-Z0-9_]+)\]", knowledge_body)
            all_sources = [f"[{s}]" for s in repo_sources + knowledge_sources]
            sources_summary = ", ".join(all_sources) if all_sources else "the provided evidence"

            return (
                f"[MOCK LLM RESPONSE] Grounded Analysis:\n"
                f"- Repository Facts: The retrieved code ({', '.join(repo_sources)}) shows the implementation.\n"
                f"- Knowledge Facts: The engineering reference ({', '.join(knowledge_sources)}) defines matching patterns.\n"
                f"- Recommendation: Based on {sources_summary}, the implementation aligns with the reference patterns for '{question}'."
            )

        # Standard repository RAG prompt
        context_match = re.search(
            r"=== BEGIN CODE CONTEXT ===\s*(.*?)\s*=== END CODE CONTEXT ===",
            prompt,
            re.DOTALL,
        )
        context_body = context_match.group(1).strip() if context_match else ""

        if not context_body or "(No relevant code chunks found)" in context_body:
            return (
                "[MOCK LLM RESPONSE] No relevant repository context was found to "
                "answer this question. I couldn't find enough relevant code in this repository to answer that reliably."
            )

        # Extract user question from prompt
        question_match = re.search(r"User Question:\s*(.*?)$", prompt, re.DOTALL)
        question = question_match.group(1).strip() if question_match else "the question"

        # Deterministically extract the first few source references mentioned in the context text
        source_headers = re.findall(r"\[Source \d+\]\s*File:\s*([^\n]+)", context_body)
        files_summary = ", ".join(source_headers[:3]) if source_headers else "the provided files"

        return (
            f"[MOCK LLM RESPONSE] Based on the provided repository context ({files_summary}), "
            f"here is the information addressing '{question}':\n\n"
            f"The codebase contains relevant definitions and configuration in {files_summary}. "
            f"Refer to the cited source blocks for exact implementation details."
        )


class OllamaLLMService(LLMService):
    """Local Ollama LLM provider communicating with Ollama HTTP API."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 90.0,
    ) -> None:
        raw_url = settings.ollama_base_url if base_url is None else base_url
        self.base_url = raw_url.rstrip("/") if raw_url else "http://localhost:11434"
        self.model = settings.ollama_model if model is None else model
        self._client = client
        self.timeout = timeout
        self._owns_client = False

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            is_closed = getattr(self._client, "is_closed", False)
            if isinstance(is_closed, bool) and is_closed:
                self._client = httpx.AsyncClient(timeout=self.timeout)
                self._owns_client = True
            return self._client
        self._client = httpx.AsyncClient(timeout=self.timeout)
        self._owns_client = True
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def generate(self, prompt: str) -> str:
        client = self._get_client()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }
        endpoint = f"{self.base_url}/api/chat"
        try:
            res = await client.post(endpoint, json=payload)
        except httpx.ConnectError as exc:
            logger.error("Failed to connect to Ollama at %s: %s", self.base_url, exc)
            raise RuntimeError(
                f"Unable to connect to Ollama at {self.base_url}. Ensure Ollama is running: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            logger.error("Ollama request timed out after %ss: %s", self.timeout, exc)
            raise RuntimeError(
                f"Ollama request timed out after {self.timeout}s: {exc}"
            ) from exc
        except Exception as exc:
            logger.error("Error communicating with Ollama: %s", exc)
            raise RuntimeError(f"Ollama communication failed: {exc}") from exc

        if res.status_code != 200:
            logger.error("Ollama API returned HTTP %d: %s", res.status_code, res.text)
            raise RuntimeError(f"Ollama API returned HTTP {res.status_code}: {res.text}")

        try:
            data = res.json()
        except Exception as exc:
            raise RuntimeError(f"Failed to parse Ollama JSON response: {exc}") from exc

        content = data.get("message", {}).get("content", "")
        return content.strip()


def get_default_llm_service() -> LLMService:
    """Factory to provide the active LLM service based on settings.llm_provider."""
    provider = (settings.llm_provider or "mock").strip().lower()
    if provider == "ollama":
        return OllamaLLMService()
    return MockLLMService()
