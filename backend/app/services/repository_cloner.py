"""
Dedicated repository cloning service using the system git executable.
"""

import asyncio
import logging
from pathlib import Path
import shutil
import subprocess
from uuid import UUID

logger = logging.getLogger(__name__)


class GitCloneError(Exception):
    """User-safe exception raised when repository cloning fails."""
    pass


class RepositoryCloner:
    """Handles secure git clone operations into isolated directories."""

    def __init__(self, storage_root: Path, timeout_seconds: int = 120) -> None:
        self.storage_root = storage_root.resolve()
        self.timeout_seconds = timeout_seconds

    def get_repository_dir(self, repo_id: UUID) -> Path:
        """Derive the deterministic and safe filesystem path for a repository."""
        # Using the UUID as the path segment guarantees no directory traversal
        # and eliminates collisions across repositories.
        repo_dir = (self.storage_root / str(repo_id)).resolve()
        if not repo_dir.is_relative_to(self.storage_root):
            raise GitCloneError("Security violation: Repository path escapes storage root.")
        return repo_dir

    def cleanup(self, repo_id: UUID) -> None:
        """Safely remove a repository directory from the filesystem."""
        try:
            target_dir = self.get_repository_dir(repo_id)
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
                logger.info("Cleaned up directory for repository %s", repo_id)
        except Exception as exc:
            logger.warning("Failed to clean up repository directory for %s: %s", repo_id, exc)

    async def clone(self, url: str, repo_id: UUID) -> Path:
        """Clone a public repository into its isolated directory.

        Security considerations:
          - Never uses shell=True
          - Applies a strict timeout
          - Clones with --depth 1 to reduce storage and bandwidth
          - Cleans up partially cloned files on any failure
          - Never executes code from the cloned repository
        """
        target_dir = self.get_repository_dir(repo_id)

        # Ensure clean initial state
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)

        self.storage_root.mkdir(parents=True, exist_ok=True)

        # Arguments executed directly by OS kernel (never passed to a shell)
        cmd = [
            "git",
            "clone",
            "--depth",
            "1",
            "--no-tags",
            "--single-branch",
            url,
            str(target_dir),
        ]

        logger.info("Starting git clone for repository %s from %s", repo_id, url)

        def _execute_git() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )

        try:
            completed = await asyncio.to_thread(_execute_git)
        except FileNotFoundError:
            logger.error("Git executable not found on system PATH.")
            raise GitCloneError("Git is not installed or available on the server.")
        except subprocess.TimeoutExpired:
            logger.warning("Git clone timed out after %s seconds for %s", self.timeout_seconds, repo_id)
            self.cleanup(repo_id)
            raise GitCloneError(f"Cloning repository timed out after {self.timeout_seconds} seconds.")
        except Exception as exc:
            logger.exception("Failed to execute git clone process: %s", exc)
            self.cleanup(repo_id)
            raise GitCloneError("Failed to initiate repository clone.")

        if completed.returncode != 0:
            self.cleanup(repo_id)
            stderr_text = completed.stderr.strip()
            logger.warning("Git clone failed (exit code %s): %s", completed.returncode, stderr_text)

            # Map raw git errors to user-safe messages without leaking local paths
            lower_err = stderr_text.lower()
            if "not found" in lower_err or "could not resolve host" in lower_err:
                raise GitCloneError("Repository not found or network is unreachable.")
            elif "authentication failed" in lower_err or "terminal prompts disabled" in lower_err:
                raise GitCloneError("Repository requires authentication or is private.")
            else:
                raise GitCloneError("Failed to clone repository. Ensure the repository is public and accessible.")

        logger.info("Successfully cloned repository %s into %s", repo_id, target_dir)
        return target_dir
