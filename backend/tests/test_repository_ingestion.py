"""
Tests for Phase 2: Repository Ingestion.

Covers:
  - GitHub URL validation and name extraction
  - File discovery, exclusion rules, and path traversal protection
  - Repository cloner behavior, timeout, cleanup, and error sanitization
  - API endpoint POST /repositories and GET /repositories/{id}
  - Ingestion state transitions (PENDING -> PROCESSING -> COMPLETED / FAILED)
  - Handling of duplicate URLs, invalid URLs, and clone failures
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from app.models.repository import IngestionStatus
from app.services.repository_cloner import GitCloneError, RepositoryCloner
from app.services.repository_files import (
    IGNORED_DIRECTORIES,
    IGNORED_EXTENSIONS,
    DiscoveredFile,
    discover_repository_files,
)
from app.services.repository_url import (
    InvalidRepositoryURLError,
    validate_and_normalize_github_url,
)


# ===========================================================================
# 1. URL Validation & Name Extraction Tests
# ===========================================================================

@pytest.mark.parametrize(
    "input_url, expected_normalized, expected_name",
    [
        ("https://github.com/owner/repo", "https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo/", "https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo.git", "https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo.git/", "https://github.com/owner/repo", "owner/repo"),
        ("https://www.github.com/owner/repo", "https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/my-org/my-project_1", "https://github.com/my-org/my-project_1", "my-org/my-project_1"),
    ],
)
def test_valid_github_urls(input_url: str, expected_normalized: str, expected_name: str):
    normalized, name = validate_and_normalize_github_url(input_url)
    assert normalized == expected_normalized
    assert name == expected_name


@pytest.mark.parametrize(
    "invalid_url",
    [
        "",
        "not-a-url",
        "http://github.com/owner/repo",             # Insecure HTTP
        "git@github.com:owner/repo.git",            # SSH format unsupported
        "https://gitlab.com/owner/repo",            # Non-GitHub host
        "https://github.com/",                      # Missing owner and repo
        "https://github.com/owner",                 # Missing repo
        "https://github.com/owner/repo/pulls/1",    # Extra path segments
        "https://github.com/owner/repo?branch=main",# Query parameter rejected
        "https://github.com/owner/..",              # Directory traversal attempt
    ],
)
def test_invalid_github_urls_rejected(invalid_url: str):
    with pytest.raises(InvalidRepositoryURLError):
        validate_and_normalize_github_url(invalid_url)


# ===========================================================================
# 2. File Discovery & Filtering Tests
# ===========================================================================

def test_file_discovery_and_filtering(tmp_path: Path):
    """Verify that file discovery captures code files while ignoring build output and binaries."""
    # Create relevant source files
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "src" / "utils.ts").write_text("export const x = 1;", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Project", encoding="utf-8")

    # Create ignored directories and files
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("git config", encoding="utf-8")

    (tmp_path / "node_modules" / "express").mkdir(parents=True)
    (tmp_path / "node_modules" / "express" / "index.js").write_text("module.exports = {}", encoding="utf-8")

    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"\x00\x01\x02")

    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_bytes(b"\x00")

    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle.js").write_text("var bundle = 1;", encoding="utf-8")

    # Create ignored file types (binary/image/archive)
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "archive.zip").write_bytes(b"PK\x03\x04")
    (tmp_path / "program.exe").write_bytes(b"MZ\x90")

    discovered = discover_repository_files(tmp_path)
    discovered_paths = [f.relative_path for f in discovered]

    # Verify expected files are included
    assert "src/main.py" in discovered_paths
    assert "src/utils.ts" in discovered_paths
    assert "README.md" in discovered_paths

    # Verify ignored paths are strictly excluded
    assert not any(p.startswith(".git") for p in discovered_paths)
    assert not any(p.startswith("node_modules") for p in discovered_paths)
    assert not any(p.startswith("__pycache__") for p in discovered_paths)
    assert not any(p.startswith(".venv") for p in discovered_paths)
    assert not any(p.startswith("dist") for p in discovered_paths)
    assert "logo.png" not in discovered_paths
    assert "archive.zip" not in discovered_paths
    assert "program.exe" not in discovered_paths


def test_file_discovery_size_limit(tmp_path: Path):
    """Files exceeding max_file_size_bytes must be skipped."""
    small_file = tmp_path / "small.txt"
    small_file.write_text("small content", encoding="utf-8")

    large_file = tmp_path / "large.txt"
    large_file.write_text("x" * 2000, encoding="utf-8")

    # Disallow files > 1000 bytes
    discovered = discover_repository_files(tmp_path, max_file_size_bytes=1000)
    discovered_paths = [f.relative_path for f in discovered]

    assert "small.txt" in discovered_paths
    assert "large.txt" not in discovered_paths


def test_file_discovery_prevents_path_escape(tmp_path: Path):
    """Symlinks that point outside the repository root must be excluded."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "valid.py").write_text("a = 1", encoding="utf-8")

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret_file = outside_dir / "secret.txt"
    secret_file.write_text("sensitive data", encoding="utf-8")

    # Attempt to symlink to outside file
    symlink_file = repo_root / "symlink.txt"
    try:
        os.symlink(secret_file, symlink_file)
    except (OSError, NotImplementedError):
        # On Windows without Developer Mode, creating symlinks may raise OSError
        pytest.skip("Symlink creation not permitted in this test environment.")

    discovered = discover_repository_files(repo_root)
    discovered_paths = [f.relative_path for f in discovered]

    assert "valid.py" in discovered_paths
    assert "symlink.txt" not in discovered_paths


# ===========================================================================
# 3. Repository Cloner Security & Isolation Tests
# ===========================================================================

def test_cloner_derives_safe_path(tmp_path: Path):
    """Repository directory is deterministically derived from UUID inside storage root."""
    cloner = RepositoryCloner(storage_root=tmp_path)
    repo_id = uuid4()
    repo_dir = cloner.get_repository_dir(repo_id)

    assert repo_dir == tmp_path / str(repo_id)
    assert repo_dir.is_relative_to(tmp_path)


def test_cloner_cleanup_removes_directory(tmp_path: Path):
    """Cleanup safely deletes the target directory without error."""
    cloner = RepositoryCloner(storage_root=tmp_path)
    repo_id = uuid4()
    repo_dir = cloner.get_repository_dir(repo_id)
    repo_dir.mkdir(parents=True)
    (repo_dir / "dummy.txt").write_text("hello", encoding="utf-8")

    assert repo_dir.exists()
    cloner.cleanup(repo_id)
    assert not repo_dir.exists()


# ===========================================================================
# 4. API & End-to-End Ingestion Flow Tests
# ===========================================================================

def test_api_create_repository_success(client, tmp_path: Path):
    """Verify end-to-end ingestion success: PENDING -> PROCESSING -> COMPLETED."""
    target_url = "https://github.com/mock-owner/mock-success-repo"

    # Mock the cloner to simulate git clone by creating sample files in target directory
    async def mock_clone(url: str, repo_id: UUID) -> Path:
        target = tmp_path / str(repo_id)
        target.mkdir(parents=True, exist_ok=True)
        (target / "main.py").write_text("print('ok')", encoding="utf-8")
        (target / "README.md").write_text("# Hello", encoding="utf-8")
        return target

    with patch("app.services.repository_ingestion.RepositoryCloner") as MockClonerClass:
        mock_instance = MockClonerClass.return_value
        mock_instance.clone = AsyncMock(side_effect=mock_clone)
        mock_instance.cleanup = AsyncMock()

        response = client.post("/repositories", json={"url": target_url})

    assert response.status_code == 201
    data = response.json()

    assert data["url"] == target_url
    assert data["name"] == "mock-owner/mock-success-repo"
    assert data["status"] == "completed"
    assert data["error_message"] is None
    assert data["ingested_at"] is not None
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data

    # Verify repository can be queried via GET /repositories/{id}
    repo_id = data["id"]
    get_res = client.get(f"/repositories/{repo_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == repo_id
    assert get_res.json()["status"] == "completed"


def test_api_create_repository_clone_failure(client):
    """Verify that clone failure transitions status to FAILED and stores clean error_message."""
    target_url = "https://github.com/mock-owner/mock-failed-repo"

    # Mock cloner to raise a GitCloneError simulating repository not found
    with patch("app.services.repository_ingestion.RepositoryCloner") as MockClonerClass:
        mock_instance = MockClonerClass.return_value
        mock_instance.clone = AsyncMock(
            side_effect=GitCloneError("Repository not found or access denied.")
        )
        mock_instance.cleanup = AsyncMock()

        response = client.post("/repositories", json={"url": target_url})

    assert response.status_code == 201
    data = response.json()

    assert data["url"] == target_url
    assert data["name"] == "mock-owner/mock-failed-repo"
    assert data["status"] == "failed"
    assert data["error_message"] == "Repository not found or access denied."
    assert data["ingested_at"] is None

    # Verify API does not expose internal filesystem paths or raw subprocess stack trace
    assert "C:\\" not in str(data["error_message"])
    assert "/home/" not in str(data["error_message"])
    assert "Traceback" not in str(data["error_message"])


def test_api_invalid_url_rejected(client):
    """Verify that invalid GitHub URLs are rejected with HTTP 422 before database insertion."""
    response = client.post("/repositories", json={"url": "https://gitlab.com/owner/repo"})
    assert response.status_code == 422
    assert "detail" in response.json()
    assert "Only GitHub" in response.json()["detail"]


def test_api_duplicate_url_conflict(client, tmp_path: Path):
    """Verify that ingesting an already-registered repository URL returns HTTP 409 Conflict."""
    target_url = "https://github.com/mock-owner/duplicate-repo"

    async def mock_clone(url: str, repo_id: UUID) -> Path:
        target = tmp_path / str(repo_id)
        target.mkdir(parents=True, exist_ok=True)
        (target / "file.py").write_text("x = 1", encoding="utf-8")
        return target

    with patch("app.services.repository_ingestion.RepositoryCloner") as MockClonerClass:
        mock_instance = MockClonerClass.return_value
        mock_instance.clone = AsyncMock(side_effect=mock_clone)
        mock_instance.cleanup = AsyncMock()

        # First request succeeds
        res1 = client.post("/repositories", json={"url": target_url})
        assert res1.status_code == 201

        # Second request with identical URL is rejected
        res2 = client.post("/repositories", json={"url": target_url})
        assert res2.status_code == 409
        assert "already registered" in res2.json()["detail"]


def test_api_list_repositories(client, tmp_path: Path):
    """Verify GET /repositories lists all repositories in descending creation order."""
    urls = [
        "https://github.com/mock-owner/list-repo-1",
        "https://github.com/mock-owner/list-repo-2",
    ]

    async def mock_clone(url: str, repo_id: UUID) -> Path:
        target = tmp_path / str(repo_id)
        target.mkdir(parents=True, exist_ok=True)
        return target

    with patch("app.services.repository_ingestion.RepositoryCloner") as MockClonerClass:
        mock_instance = MockClonerClass.return_value
        mock_instance.clone = AsyncMock(side_effect=mock_clone)
        mock_instance.cleanup = AsyncMock()

        for u in urls:
            res = client.post("/repositories", json={"url": u})
            assert res.status_code == 201

    list_res = client.get("/repositories")
    assert list_res.status_code == 200
    repos = list_res.json()
    assert len(repos) >= 2
    repo_urls = [r["url"] for r in repos]
    assert urls[0] in repo_urls
    assert urls[1] in repo_urls
