"""
Tests verifying that both MockAgentLLMService and GeminiAgentLLMService
strictly conform to the provider-independent AgentLLMService contract.
"""

import pytest

from app.schemas.agent import (
    AgentLLMResponse,
    AgentMessage,
    AgentMessageRole,
    AgentToolDefinition,
    ToolCall,
    ToolName,
    get_agent_tool_definitions,
)
from app.services.agent_llm import AgentLLMService, MockAgentLLMService, get_agent_llm_service
from app.services.gemini_agent_llm import GeminiAgentLLMService, GeminiConfigurationError
from app.services.ollama_agent_llm import OllamaAgentLLMService, OllamaConfigurationError


def test_mock_agent_llm_conforms_to_contract():
    """MockAgentLLMService is an instance of AgentLLMService ABC."""
    mock_service = MockAgentLLMService()
    assert isinstance(mock_service, AgentLLMService)


def test_gemini_agent_llm_conforms_to_contract():
    """GeminiAgentLLMService is an instance of AgentLLMService ABC."""
    gemini_service = GeminiAgentLLMService(api_key="dummy-test-key")
    assert isinstance(gemini_service, AgentLLMService)


def test_get_agent_llm_service_factory_mock():
    """Factory returns MockAgentLLMService when provider is 'mock' or default."""
    service = get_agent_llm_service(provider="mock")
    assert isinstance(service, MockAgentLLMService)


def test_get_agent_llm_service_factory_gemini():
    """Factory returns GeminiAgentLLMService when provider is 'gemini'."""
    service = get_agent_llm_service(provider="gemini", api_key="dummy-key")
    assert isinstance(service, GeminiAgentLLMService)
    assert service.api_key == "dummy-key"


async def test_mock_agent_llm_generate_returns_agent_llm_response():
    """Calling generate on MockAgentLLMService returns a normalized AgentLLMResponse."""
    service = MockAgentLLMService()
    messages = [
        AgentMessage(role=AgentMessageRole.USER, content="Where is the authentication logic?")
    ]
    tools = get_agent_tool_definitions()

    res = await service.generate(messages=messages, tools=tools)
    assert isinstance(res, AgentLLMResponse)
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].tool == ToolName.SEARCH_CODE


def test_ollama_agent_llm_conforms_to_contract():
    """OllamaAgentLLMService is an instance of AgentLLMService ABC."""
    ollama_service = OllamaAgentLLMService(base_url="http://localhost:11434", model="qwen2.5-coder:7b")
    assert isinstance(ollama_service, AgentLLMService)


def test_get_agent_llm_service_factory_ollama():
    """Factory returns OllamaAgentLLMService when provider is 'ollama'."""
    service = get_agent_llm_service(
        provider="ollama",
        base_url="http://localhost:11434",
        model="qwen2.5-coder:7b",
    )
    assert isinstance(service, OllamaAgentLLMService)
    assert service.base_url == "http://localhost:11434"
    assert service.model == "qwen2.5-coder:7b"


def test_gemini_raises_configuration_error_when_api_key_missing():
    """Attempting to access client without GEMINI_API_KEY raises GeminiConfigurationError."""
    service = GeminiAgentLLMService(api_key=None)
    # Clear any config fallback for test
    service.api_key = None
    with pytest.raises(GeminiConfigurationError, match="GEMINI_API_KEY is not configured"):
        service._get_client()


def test_ollama_raises_configuration_error_when_url_or_model_missing():
    """Attempting to access client without base_url or model raises OllamaConfigurationError."""
    service_no_url = OllamaAgentLLMService(base_url="", model="qwen2.5-coder:7b")
    with pytest.raises(OllamaConfigurationError, match="Ollama base URL is not configured"):
        service_no_url._get_client()

    service_no_model = OllamaAgentLLMService(base_url="http://localhost:11434", model="")
    with pytest.raises(OllamaConfigurationError, match="Ollama model is not configured"):
        service_no_model._get_client()

