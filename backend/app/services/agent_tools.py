"""
Read-only tool implementations for the ForgeAI Agent.
"""

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.rag import ChunkRetrievalResult
from app.services.repository_files import IGNORED_DIRECTORIES
from app.services.retrieval import RetrievalService

logger = logging.getLogger(__name__)


class ToolExecutionError(Exception):
    """Controlled error raised when a tool encounters an invalid argument or execution failure."""
    pass


class PathSecurityError(ToolExecutionError):
    """Raised when a path traversal, symlink escape, or boundary violation is detected."""
    pass


@dataclass(frozen=True)
class ReadFileResult:
    """Output from the read_file tool."""

    path: str
    start_line: int
    end_line: int
    total_lines: int
    content: str


@dataclass(frozen=True)
class ListFilesResult:
    """Output from the list_files tool."""

    base_path: str
    entries: list[str]
    total_found: int
    truncated: bool


class AgentTools:
    """Provides the three strictly read-only tools for repository inspection."""

    def __init__(
        self,
        retrieval_service: RetrievalService | None = None,
        storage_root: Path | None = None,
    ) -> None:
        self.retrieval_service = retrieval_service or RetrievalService()
        self.storage_root = (storage_root or Path(settings.repository_storage_path)).resolve()

    def _get_verified_repo_root(self, repository_id: UUID) -> Path:
        """Resolve and verify that the repository directory exists within storage_root."""
        repo_root = (self.storage_root / str(repository_id)).resolve()
        if not repo_root.is_relative_to(self.storage_root):
            raise PathSecurityError("Repository path escape detected.")
        if not repo_root.is_dir():
            raise ToolExecutionError(
                f"Cloned repository directory for '{repository_id}' does not exist on disk."
            )
        return repo_root

    # =========================================================================
    # Tool 1: search_code
    # =========================================================================

    async def search_code(
        self,
        repository_id: UUID,
        query: str,
        db: AsyncSession,
        top_k: int = 5,
    ) -> list[ChunkRetrievalResult]:
        """Perform semantic code retrieval using PostgreSQL + pgvector with repository isolation."""
        if not query or not query.strip():
            raise ToolExecutionError("Search query must not be empty.")
        bounded_top_k = max(1, min(50, top_k))
        return await self.retrieval_service.search(
            repository_id=repository_id,
            query=query.strip(),
            db=db,
            top_k=bounded_top_k,
        )

    # =========================================================================
    # Tool 2: read_file
    # =========================================================================

    def read_file(
        self,
        repository_id: UUID,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> ReadFileResult:
        """Read content from an existing repository file within bounded line ranges."""
        if not path or not path.strip():
            raise ToolExecutionError("File path must not be empty.")

        clean_path = path.strip()
        raw_path_obj = Path(clean_path)

        # Reject absolute paths or paths with Windows drive letters or root slashes
        if clean_path.startswith(("/", "\\")) or raw_path_obj.is_absolute() or raw_path_obj.drive:
            raise PathSecurityError(f"Absolute paths are forbidden: '{clean_path}'")

        # Reject path components that attempt directory traversal
        parts = raw_path_obj.parts
        if any(part in ("..", "~") for part in parts):
            raise PathSecurityError(f"Directory traversal detected in path: '{clean_path}'")

        repo_root = self._get_verified_repo_root(repository_id)
        target_file = (repo_root / clean_path).resolve()

        # Invariant: Canonical target must remain strictly inside repo_root
        if not target_file.is_relative_to(repo_root):
            raise PathSecurityError(f"Path escapes repository root: '{clean_path}'")

        if not target_file.exists():
            raise ToolExecutionError(f"File not found: '{clean_path}'")

        if not target_file.is_file():
            raise ToolExecutionError(f"Path is not a regular file: '{clean_path}'")

        # File size safety check
        if target_file.stat().st_size > settings.max_file_size_bytes:
            raise ToolExecutionError(
                f"File '{clean_path}' exceeds maximum allowable size of {settings.max_file_size_bytes} bytes."
            )

        try:
            full_text = target_file.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            raise ToolExecutionError(f"Failed to read file '{clean_path}': {exc}") from exc

        lines = full_text.splitlines()
        total_lines = len(lines)

        # Validate and bound line numbers
        req_start = start_line if start_line is not None else 1
        if req_start < 1:
            raise ToolExecutionError("start_line must be >= 1.")

        if end_line is not None and end_line < req_start:
            raise ToolExecutionError(f"end_line ({end_line}) cannot be less than start_line ({req_start}).")

        if total_lines == 0:
            return ReadFileResult(
                path=target_file.relative_to(repo_root).as_posix(),
                start_line=1,
                end_line=1,
                total_lines=0,
                content="",
            )

        if req_start > total_lines:
            raise ToolExecutionError(
                f"start_line ({req_start}) exceeds total lines ({total_lines}) in '{clean_path}'."
            )

        max_read = settings.agent_max_file_read_lines
        if end_line is not None:
            if (end_line - req_start + 1) > max_read:
                raise ToolExecutionError(
                    f"Requested line range ({end_line - req_start + 1}) exceeds maximum of {max_read} lines."
                )
            req_end = min(end_line, total_lines)
        else:
            req_end = min(total_lines, req_start + max_read - 1)

        sliced_content = "\n".join(lines[req_start - 1 : req_end])
        rel_posix_path = target_file.relative_to(repo_root).as_posix()

        return ReadFileResult(
            path=rel_posix_path,
            start_line=req_start,
            end_line=req_end,
            total_lines=total_lines,
            content=sliced_content,
        )

    # =========================================================================
    # Tool 3: list_files
    # =========================================================================

    def list_files(
        self,
        repository_id: UUID,
        path: str | None = None,
        max_files: int = 100,
    ) -> ListFilesResult:
        """List repository files and subdirectories relative to repository root."""
        repo_root = self._get_verified_repo_root(repository_id)

        if path and path.strip():
            clean_subpath = path.strip()
            raw_subpath = Path(clean_subpath)
            if clean_subpath.startswith(("/", "\\")) or raw_subpath.is_absolute() or raw_subpath.drive:
                raise PathSecurityError(f"Absolute paths are forbidden: '{clean_subpath}'")
            if any(part in ("..", "~") for part in raw_subpath.parts):
                raise PathSecurityError(f"Directory traversal detected: '{clean_subpath}'")
            target_dir = (repo_root / clean_subpath).resolve()
        else:
            clean_subpath = ""
            target_dir = repo_root

        if not target_dir.is_relative_to(repo_root):
            raise PathSecurityError("Directory path escapes repository root.")

        if not target_dir.exists():
            raise ToolExecutionError(f"Directory not found: '{clean_subpath or '.'}'")

        if not target_dir.is_dir():
            raise ToolExecutionError(f"Path is not a directory: '{clean_subpath}'")

        bounded_max = max(1, min(500, max_files))
        entries: list[str] = []
        total_found = 0
        truncated = False

        for current_root_str, dirnames, filenames in os.walk(target_dir):
            # Prune ignored directories in-place
            dirnames[:] = [
                d for d in dirnames
                if d not in IGNORED_DIRECTORIES and not d.startswith(".git")
            ]

            for d in dirnames:
                total_found += 1
                dir_path = (Path(current_root_str) / d).resolve()
                if dir_path.is_relative_to(repo_root):
                    rel = dir_path.relative_to(repo_root).as_posix() + "/"
                    if len(entries) < bounded_max:
                        entries.append(rel)
                    else:
                        truncated = True

            for f in filenames:
                total_found += 1
                file_path = (Path(current_root_str) / f).resolve()
                if file_path.is_relative_to(repo_root):
                    rel = file_path.relative_to(repo_root).as_posix()
                    if len(entries) < bounded_max:
                        entries.append(rel)
                    else:
                        truncated = True

        entries.sort()
        rel_base = target_dir.relative_to(repo_root).as_posix() if target_dir != repo_root else ""

        return ListFilesResult(
            base_path=rel_base,
            entries=entries,
            total_found=total_found,
            truncated=truncated,
        )
