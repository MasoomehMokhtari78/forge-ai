"""
Unit tests for OllamaAgentLLMService mocking the HTTP layer (httpx).
Validates configuration, tool translation, message translation, native tool call parsing,
content fallback parsing, malformed output handling, network/HTTP error handling,
and provider selection.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.core.config import settings
from app.schemas.agent import (
    AgentLLMResponse,
    AgentMessage,
    AgentMessageRole,
    ToolCall,
    ToolName,
    get_agent_tool_definitions,
)
from app.services.agent_llm import (
    AgentLLMService,
    MockAgentLLMService,
    get_agent_llm_service,
)
from app.services.gemini_agent_llm import GeminiAgentLLMService
from app.services.ollama_agent_llm import (
    OllamaAPIError,
    OllamaAgentLLMService,
    OllamaConfigurationError,
)


def test_ollama_provider_configuration_defaults():
    """OllamaAgentLLMService takes defaults from application settings."""
    service = OllamaAgentLLMService()
    assert service.base_url == settings.ollama_base_url.rstrip("/")
    assert service.model == settings.ollama_model
    assert service.timeout == 60.0


def test_ollama_provider_custom_configuration():
    """OllamaAgentLLMService correctly stores custom base_url, model, and timeout."""
    service = OllamaAgentLLMService(
        base_url="http://custom-ollama:11434/",
        model="codellama:13b",
        timeout=30.0,
    )
    assert service.base_url == "http://custom-ollama:11434"
    assert service.model == "codellama:13b"
    assert service.timeout == 30.0


def test_ollama_tools_translation():
    """Normalized ForgeAI tools translate to Ollama function calling declarations."""
    tools = get_agent_tool_definitions()
    declarations = OllamaAgentLLMService._build_tools(tools)

    assert len(declarations) == 3
    tool_names = [d["function"]["name"] for d in declarations]
    assert "search_code" in tool_names
    assert "read_file" in tool_names
    assert "list_files" in tool_names

    search_decl = next(d for d in declarations if d["function"]["name"] == "search_code")
    assert search_decl["type"] == "function"
    assert "query" in search_decl["function"]["parameters"]["properties"]
    assert search_decl["function"]["parameters"]["required"] == ["query"]


def test_ollama_messages_translation():
    """Normalized ForgeAI messages translate to Ollama chat message formats."""
    messages = [
        AgentMessage(role=AgentMessageRole.SYSTEM, content="System prompt instructions."),
        AgentMessage(role=AgentMessageRole.USER, content="Where is login defined?"),
        AgentMessage(
            role=AgentMessageRole.ASSISTANT,
            content="Searching code first.",
            tool_calls=[ToolCall(tool=ToolName.SEARCH_CODE, arguments={"query": "login"})],
        ),
        AgentMessage(
            role=AgentMessageRole.TOOL,
            tool_name="search_code",
            content='{"chunks": ["chunk1"]}',
        ),
    ]

    chat_messages = OllamaAgentLLMService._build_messages(messages)
    assert len(chat_messages) == 4
    assert chat_messages[0] == {"role": "system", "content": "System prompt instructions."}
    assert chat_messages[1] == {"role": "user", "content": "Where is login defined?"}
    assert chat_messages[2]["role"] == "assistant"
    assert chat_messages[2]["content"] == "Searching code first."
    assert chat_messages[2]["tool_calls"][0]["function"]["name"] == "search_code"
    assert chat_messages[2]["tool_calls"][0]["function"]["arguments"] == {"query": "login"}
    assert chat_messages[3] == {"role": "tool", "content": '{"chunks": ["chunk1"]}'}


def test_parse_response_native_tool_calls():
    """Ollama response with message.tool_calls is parsed into AgentLLMResponse with ToolCalls."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "search_code",
                        "arguments": {"query": "jwt authentication", "top_k": 5},
                    }
                }
            ],
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].tool == ToolName.SEARCH_CODE
    assert res.tool_calls[0].arguments == {"query": "jwt authentication", "top_k": 5}
    assert res.final_text is None


def test_parse_response_native_tool_calls_stringified_arguments():
    """Ollama tool_calls with stringified JSON arguments are properly parsed into dict."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({"path": "src/auth.py", "start_line": 1, "end_line": 50}),
                    }
                }
            ],
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].tool == ToolName.READ_FILE
    assert res.tool_calls[0].arguments == {"path": "src/auth.py", "start_line": 1, "end_line": 50}
    assert res.final_text is None


def test_parse_response_plain_text_final_answer():
    """Ollama response with plain text and no tool calls returns final_text."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": "The authentication logic is implemented in src/auth.py (src_1).",
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 0
    assert res.final_text == "The authentication logic is implemented in src/auth.py (src_1)."


def test_parse_response_json_tool_call_in_content():
    """Model that outputs JSON decision in content is parsed as a tool call."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": '{"type": "tool", "tool": "search_code", "arguments": {"query": "database"}}',
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].tool == ToolName.SEARCH_CODE
    assert res.tool_calls[0].arguments == {"query": "database"}
    assert res.final_text is None


def test_parse_response_fenced_markdown_json_tool_call():
    """Model that wraps JSON decision in markdown ```json code block is parsed as a tool call."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": (
                "I should inspect the repository files first.\n"
                "```json\n"
                "{\n"
                '  "type": "tool",\n'
                '  "name": "list_files",\n'
                '  "arguments": {"path": "src"}\n'
                "}\n"
                "```"
            ),
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].tool == ToolName.LIST_FILES
    assert res.tool_calls[0].arguments == {"path": "src"}
    assert res.final_text is None


def test_parse_response_fenced_markdown_final_answer():
    """Model that formats final answer inside a JSON block with type: final."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": '```json\n{"type": "final", "answer": "The token is validated via JWT middleware."}\n```',
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 0
    assert res.final_text == "The token is validated via JWT middleware."


def test_parse_response_unrecognized_tool_safely_ignored():
    """Unrecognized tool name is ignored and not added to tool_calls."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": "Running an unauthorized command",
            "tool_calls": [
                {
                    "function": {
                        "name": "delete_database",
                        "arguments": {},
                    }
                }
            ],
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 0
    assert res.final_text == "Running an unauthorized command"


def test_parse_response_qwen_tool_call_tag():
    """Qwen <tool_call> tag is parsed into structured ToolCall and final_text is None."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": (
                '<tool_call>\n'
                '{"name":"search_code","arguments":{"query":"README"}}\n'
                '</tool_call>'
            ),
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].tool == ToolName.SEARCH_CODE
    assert res.tool_calls[0].arguments == {"query": "README"}
    assert res.final_text is None


def test_parse_response_qwen_tool_response_compatibility_tag():
    """Observed Qwen <tool_response> compatibility format with preamble is parsed into ToolCall."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": (
                "I apologize for the oversight. Let's proceed with inspecting the repository files...\n\n"
                "<tool_response>\n"
                '{"name": "search_code", "arguments": {"query": "README.md CONTRIBUTING.md"}}\n'
                "</tool_response>"
            ),
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].tool == ToolName.SEARCH_CODE
    assert res.tool_calls[0].arguments == {"query": "README.md CONTRIBUTING.md"}
    # Preamble must be stripped and not become final_text
    assert res.final_text is None


def test_parse_response_tagged_unknown_tool_safely_ignored():
    """Unknown tool name inside tag is rejected and does not become an executable ToolCall."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": (
                '<tool_call>\n'
                '{"name":"delete_repository","arguments":{}}\n'
                '</tool_call>'
            ),
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 0
    assert res.final_text is not None


def test_parse_response_tagged_malformed_json_safely_ignored():
    """Malformed JSON inside tag safely remains non-executable."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": (
                '<tool_call>\n'
                '{"name":"search_code","arguments":\n'
                '</tool_call>'
            ),
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 0
    assert res.final_text is not None


def test_parse_response_tagged_non_dictionary_arguments_safely_ignored():
    """Non-dictionary arguments inside tag are rejected."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": (
                '<tool_call>\n'
                '{"name":"search_code","arguments":"not a dict"}\n'
                '</tool_call>'
            ),
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 0
    assert res.final_text is not None


def test_parse_response_arbitrary_json_in_prose_not_executed():
    """Arbitrary JSON embedded in ordinary prose without tags is NOT executed as a tool call."""
    raw_payload = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": (
                "Here is an example:\n\n"
                '{"name":"search_code","arguments":{"query":"README"}}\n\n'
                "I think you should search the README."
            ),
        },
        "done": True,
    }

    res = OllamaAgentLLMService._parse_response(raw_payload)
    assert len(res.tool_calls) == 0
    assert res.final_text is not None
    assert "Here is an example:" in res.final_text


def test_parse_response_malformed_data():
    """Malformed or empty payload is handled safely without raising exceptions."""
    empty_res = OllamaAgentLLMService._parse_response({})
    assert empty_res.tool_calls == []
    assert empty_res.final_text is None

    corrupt_msg = OllamaAgentLLMService._parse_response({"message": None})
    assert corrupt_msg.tool_calls == []
    assert corrupt_msg.final_text is None

    broken_json_text = {
        "message": {
            "content": "```json\n{this is invalid json}\n```"
        }
    }
    fallback_res = OllamaAgentLLMService._parse_response(broken_json_text)
    assert fallback_res.tool_calls == []
    assert "this is invalid json" in (fallback_res.final_text or "")


async def test_generate_successful_http_call():
    """Calling generate() posts payload to Ollama /api/chat and returns parsed response."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "search_code",
                        "arguments": {"query": "auth"},
                    }
                }
            ],
        },
    }
    mock_client.post.return_value = mock_resp

    service = OllamaAgentLLMService(
        base_url="http://localhost:11434",
        model="qwen2.5-coder:7b",
        client=mock_client,
    )

    messages = [AgentMessage(role=AgentMessageRole.USER, content="Where is auth?")]
    result = await service.generate(messages=messages)

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool == ToolName.SEARCH_CODE
    assert result.tool_calls[0].arguments == {"query": "auth"}

    # Verify request payload sent to /api/chat
    mock_client.post.assert_awaited_once()
    called_url, called_kwargs = mock_client.post.call_args
    assert called_url[0] == "http://localhost:11434/api/chat"
    assert called_kwargs["json"]["model"] == "qwen2.5-coder:7b"
    assert called_kwargs["json"]["stream"] is False
    assert len(called_kwargs["json"]["messages"]) == 1


async def test_generate_connection_error_raises_ollama_api_error():
    """httpx.ConnectError is caught and raised as OllamaAPIError with descriptive guidance."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")

    service = OllamaAgentLLMService(
        base_url="http://localhost:11434",
        model="qwen2.5-coder:7b",
        client=mock_client,
    )

    messages = [AgentMessage(role=AgentMessageRole.USER, content="Hello")]
    with pytest.raises(OllamaAPIError, match="Unable to connect to Ollama server at http://localhost:11434"):
        await service.generate(messages=messages)


async def test_generate_timeout_error_raises_ollama_api_error():
    """httpx.TimeoutException is caught and raised as OllamaAPIError."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.ReadTimeout("Read timed out")

    service = OllamaAgentLLMService(
        base_url="http://localhost:11434",
        model="qwen2.5-coder:7b",
        client=mock_client,
        timeout=15.0,
    )

    messages = [AgentMessage(role=AgentMessageRole.USER, content="Hello")]
    with pytest.raises(OllamaAPIError, match="timed out after 15.0s"):
        await service.generate(messages=messages)


async def test_generate_http_error_status_raises_ollama_api_error():
    """Non-200 HTTP response is parsed and raised as OllamaAPIError with error message."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 404
    mock_resp.text = '{"error": "model \'unknown:model\' not found"}'
    mock_resp.json.return_value = {"error": "model 'unknown:model' not found"}
    mock_client.post.return_value = mock_resp

    service = OllamaAgentLLMService(
        base_url="http://localhost:11434",
        model="unknown:model",
        client=mock_client,
    )

    messages = [AgentMessage(role=AgentMessageRole.USER, content="Hello")]
    with pytest.raises(OllamaAPIError, match=r"Ollama API error \(HTTP 404\): model 'unknown:model' not found"):
        await service.generate(messages=messages)


def test_provider_selection_ollama(monkeypatch):
    """When LLM_PROVIDER=ollama in settings or parameter, factory returns OllamaAgentLLMService."""
    # Explicit parameter
    service = get_agent_llm_service(provider="ollama")
    assert isinstance(service, OllamaAgentLLMService)

    # Via settings
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    service_from_settings = get_agent_llm_service()
    assert isinstance(service_from_settings, OllamaAgentLLMService)


def test_provider_selection_mock_and_gemini_remain_selectable(monkeypatch):
    """Existing mock and gemini providers remain selectable and functional."""
    mock_service = get_agent_llm_service(provider="mock")
    assert isinstance(mock_service, MockAgentLLMService)

    gemini_service = get_agent_llm_service(provider="gemini", api_key="dummy-key")
    assert isinstance(gemini_service, GeminiAgentLLMService)

    monkeypatch.setattr(settings, "llm_provider", "mock")
    default_service = get_agent_llm_service()
    assert isinstance(default_service, MockAgentLLMService)


async def test_agent_service_loop_with_ollama_provider(db_session, tmp_path):
    """AgentService executes multi-step investigation against OllamaAgentLLMService."""
    from pathlib import Path
    from uuid import uuid4
    from app.models.code_chunk import CodeChunk
    from app.models.code_file import CodeFile
    from app.models.repository import IngestionStatus, Repository
    from app.schemas.agent import AgentStatus
    from app.services.agent import AgentService
    from app.services.agent_tools import AgentTools

    storage_root = tmp_path / "storage"
    storage_root.mkdir()

    repo_id = uuid4()
    repo = Repository(
        id=repo_id,
        url=f"https://github.com/agent-test/{repo_id.hex[:6]}",
        name="agent-test/ollama-repo",
        status=IngestionStatus.COMPLETED,
    )
    db_session.add(repo)
    await db_session.flush()

    repo_dir = storage_root / str(repo_id)
    repo_dir.mkdir(parents=True)
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "auth.py").write_text("def authenticate(token):\n    return True\n", encoding="utf-8")

    cf = CodeFile(
        repository_id=repo.id,
        path="src/auth.py",
        extension=".py",
        size_bytes=40,
    )
    db_session.add(cf)
    await db_session.flush()

    chunk = CodeChunk(
        file_id=cf.id,
        chunk_index=0,
        content="def authenticate(token):\n    return True\n",
        start_line=1,
        end_line=2,
        embedding=[0.1] * 384,
    )
    db_session.add(chunk)
    await db_session.flush()

    # Create scripted Ollama responses
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    resp1 = MagicMock(spec=httpx.Response)
    resp1.status_code = 200
    resp1.json.return_value = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "read_file",
                        "arguments": {"path": "src/auth.py", "start_line": 1, "end_line": 2},
                    }
                }
            ],
        },
    }

    resp2 = MagicMock(spec=httpx.Response)
    resp2.status_code = 200
    resp2.json.return_value = {
        "model": "qwen2.5-coder:7b",
        "message": {
            "role": "assistant",
            "content": "The authenticate function returns True in src/auth.py (src_1).",
        },
    }

    mock_client.post.side_effect = [resp1, resp2]

    ollama_llm = OllamaAgentLLMService(
        base_url="http://localhost:11434",
        model="qwen2.5-coder:7b",
        client=mock_client,
    )

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=ollama_llm,
    )

    response = await agent_service.run(
        repository_id=repo.id,
        question="How does authentication work?",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.tool_calls_count == 1
    assert response.iterations_count == 2
    assert "src/auth.py" in response.answer
    assert len(response.sources) == 1
    assert response.sources[0].path == "src/auth.py"
    assert response.sources[0].source_id == "src_1"
    assert mock_client.post.await_count == 2

