"""
Unit and security tests for Agent read-only tools: search_code, read_file, and list_files.
"""

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.schemas.rag import ChunkRetrievalResult
from app.services.agent_tools import (
    AgentTools,
    PathSecurityError,
    ToolExecutionError,
)
from app.services.retrieval import RetrievalService


@pytest.fixture
def temp_storage(tmp_path: Path):
    """Set up a mock repository storage tree."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    return storage_root


@pytest.fixture
def repo_dir(temp_storage: Path):
    repo_id = uuid4()
    r_dir = temp_storage / str(repo_id)
    r_dir.mkdir()

    # Create sample repository structure
    src_dir = r_dir / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("def main():\n    print('hello world')\n", encoding="utf-8")
    (src_dir / "auth.py").write_text(
        "\n".join([f"line_{i} = {i}" for i in range(1, 101)]),
        encoding="utf-8",
    )
    (r_dir / "README.md").write_text("# Project Readme\n", encoding="utf-8")

    # Ignored directories
    git_dir = r_dir / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("git config", encoding="utf-8")

    node_dir = r_dir / "node_modules"
    node_dir.mkdir()
    (node_dir / "pkg.json").write_text("{}", encoding="utf-8")

    return repo_id, r_dir


# ===========================================================================
# 1. read_file Tests
# ===========================================================================

def test_read_file_success_whole_file(temp_storage, repo_dir):
    repo_id, _ = repo_dir
    tools = AgentTools(storage_root=temp_storage)

    result = tools.read_file(repository_id=repo_id, path="src/main.py")
    assert result.path == "src/main.py"
    assert result.start_line == 1
    assert result.end_line == 2
    assert "def main():" in result.content


def test_read_file_line_slice(temp_storage, repo_dir):
    repo_id, _ = repo_dir
    tools = AgentTools(storage_root=temp_storage)

    result = tools.read_file(repository_id=repo_id, path="src/auth.py", start_line=10, end_line=15)
    assert result.path == "src/auth.py"
    assert result.start_line == 10
    assert result.end_line == 15
    assert "line_10 = 10" in result.content
    assert "line_15 = 15" in result.content
    assert "line_9 = 9" not in result.content
    assert "line_16 = 16" not in result.content


def test_read_file_non_existent_file(temp_storage, repo_dir):
    repo_id, _ = repo_dir
    tools = AgentTools(storage_root=temp_storage)

    with pytest.raises(ToolExecutionError, match="File not found"):
        tools.read_file(repository_id=repo_id, path="src/missing.py")


def test_read_file_directory_target_rejected(temp_storage, repo_dir):
    repo_id, _ = repo_dir
    tools = AgentTools(storage_root=temp_storage)

    with pytest.raises(ToolExecutionError, match="not a regular file"):
        tools.read_file(repository_id=repo_id, path="src")


def test_read_file_invalid_line_ranges(temp_storage, repo_dir):
    repo_id, _ = repo_dir
    tools = AgentTools(storage_root=temp_storage)

    with pytest.raises(ToolExecutionError, match="start_line must be >= 1"):
        tools.read_file(repository_id=repo_id, path="src/main.py", start_line=0)

    with pytest.raises(ToolExecutionError, match="cannot be less than start_line"):
        tools.read_file(repository_id=repo_id, path="src/main.py", start_line=10, end_line=5)

    with pytest.raises(ToolExecutionError, match="exceeds total lines"):
        tools.read_file(repository_id=repo_id, path="src/main.py", start_line=500)


# ===========================================================================
# 2. Path Traversal & Security Invariant Tests
# ===========================================================================

@pytest.mark.parametrize("bad_path", [
    "../secret.txt",
    "../../etc/passwd",
    "src/../../outside.py",
    "/etc/shadow",
    "C:\\Windows\\System32\\calc.exe",
    "~/.ssh/id_rsa",
])
def test_read_file_path_traversal_forbidden(temp_storage, repo_dir, bad_path):
    repo_id, _ = repo_dir
    tools = AgentTools(storage_root=temp_storage)

    with pytest.raises(PathSecurityError):
        tools.read_file(repository_id=repo_id, path=bad_path)


@pytest.mark.parametrize("bad_subpath", [
    "../",
    "../../",
    "/etc",
    "C:\\Windows",
    "~",
])
def test_list_files_path_traversal_forbidden(temp_storage, repo_dir, bad_subpath):
    repo_id, _ = repo_dir
    tools = AgentTools(storage_root=temp_storage)

    with pytest.raises(PathSecurityError):
        tools.list_files(repository_id=repo_id, path=bad_subpath)


# ===========================================================================
# 3. list_files Tests
# ===========================================================================

def test_list_files_root(temp_storage, repo_dir):
    repo_id, _ = repo_dir
    tools = AgentTools(storage_root=temp_storage)

    result = tools.list_files(repository_id=repo_id)
    assert "README.md" in result.entries
    assert "src/main.py" in result.entries
    assert "src/auth.py" in result.entries
    # Ensure ignored directories (.git, node_modules) are excluded
    assert not any(".git" in e for e in result.entries)
    assert not any("node_modules" in e for e in result.entries)


def test_list_files_subdirectory(temp_storage, repo_dir):
    repo_id, _ = repo_dir
    tools = AgentTools(storage_root=temp_storage)

    result = tools.list_files(repository_id=repo_id, path="src")
    assert "src/main.py" in result.entries
    assert "src/auth.py" in result.entries
    assert "README.md" not in result.entries


# ===========================================================================
# 4. search_code Tests
# ===========================================================================

async def test_search_code_delegates_to_retrieval(temp_storage):
    mock_retrieval = AsyncMock(spec=RetrievalService)
    repo_id = uuid4()
    mock_chunk = ChunkRetrievalResult(
        chunk_id=uuid4(),
        file_id=uuid4(),
        path="src/service.py",
        content="code snippet",
        start_line=1,
        end_line=10,
        similarity=0.91,
    )
    mock_retrieval.search.return_value = [mock_chunk]

    tools = AgentTools(retrieval_service=mock_retrieval, storage_root=temp_storage)
    db_mock = AsyncMock()

    results = await tools.search_code(
        repository_id=repo_id,
        query="auth service",
        db=db_mock,
        top_k=5,
    )

    assert len(results) == 1
    assert results[0].path == "src/service.py"
    mock_retrieval.search.assert_called_once_with(
        repository_id=repo_id,
        query="auth service",
        db=db_mock,
        top_k=5,
    )


async def test_search_code_empty_query_rejected(temp_storage):
    tools = AgentTools(storage_root=temp_storage)
    with pytest.raises(ToolExecutionError, match="must not be empty"):
        await tools.search_code(repository_id=uuid4(), query="   ", db=AsyncMock())
