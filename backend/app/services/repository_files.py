"""
File discovery and filtering service for cloned repositories.
"""

from dataclasses import dataclass
import os
from pathlib import Path

# Directories that should not normally participate in code analysis
IGNORED_DIRECTORIES: frozenset[str] = frozenset({
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "out",
    "coverage",
    ".nyc_output",
    ".next",
    ".nuxt",
    "target",
    "bin",
    "obj",
    ".idea",
    ".vscode",
})

# Obviously non-code / binary file extensions that should be ignored
IGNORED_EXTENSIONS: frozenset[str] = frozenset({
    # Images and graphics
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".bmp", ".tiff",
    # Audio and video
    ".mp3", ".mp4", ".wav", ".ogg", ".mov", ".avi", ".flac", ".webm",
    # Archives and compressed files
    ".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".xz",
    # Compiled objects, binaries, and executables
    ".exe", ".dll", ".so", ".dylib", ".bin", ".iso", ".o", ".obj", ".class",
    ".pyc", ".pyo", ".pyd", ".wasm",
    # Fonts
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    # Proprietary document / spreadsheet formats
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Database and lock binaries
    ".sqlite", ".db",
})


@dataclass(frozen=True)
class DiscoveredFile:
    """Represents a discovered and filtered source file."""

    relative_path: str
    extension: str
    size_bytes: int


def discover_repository_files(
    repo_root: Path,
    max_file_size_bytes: int = 2 * 1024 * 1024,
) -> list[DiscoveredFile]:
    """Recursively discover and filter files in a repository directory.

    Guarantees:
      - Ignores non-code directories (.git, node_modules, build artifacts, etc.)
      - Ignores binary, media, and archive file types
      - Enforces file size limits (skipping files larger than max_file_size_bytes)
      - Strictly prevents path traversal or symlinks escaping repo_root
      - Returns files with normalized POSIX relative paths, sorted deterministically
    """
    resolved_root = repo_root.resolve()
    if not resolved_root.is_dir():
        raise FileNotFoundError(f"Repository root directory does not exist: {resolved_root}")

    discovered: list[DiscoveredFile] = []

    for current_root_str, dirnames, filenames in os.walk(resolved_root):
        current_root = Path(current_root_str)

        # Prune ignored directories in-place so os.walk does not traverse into them
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORED_DIRECTORIES and not d.startswith(".git")
        ]

        for filename in filenames:
            file_path = current_root / filename

            # Path traversal & symlink escape protection:
            # resolve() follows symlinks to their real target
            try:
                resolved_file = file_path.resolve()
            except (OSError, RuntimeError):
                continue

            # Ensure the resolved file is strictly located inside resolved_root
            if not resolved_file.is_relative_to(resolved_root):
                continue

            # Skip if it is not a regular file (e.g. sockets, pipes, broken links)
            if not resolved_file.is_file():
                continue

            ext = file_path.suffix.lower()
            if ext in IGNORED_EXTENSIONS:
                continue

            # Check file size
            try:
                stat_info = resolved_file.stat()
                size = stat_info.st_size
            except OSError:
                continue

            if size > max_file_size_bytes:
                continue

            # Generate normalized POSIX relative path from repository root
            rel_path = file_path.relative_to(resolved_root).as_posix()

            discovered.append(
                DiscoveredFile(
                    relative_path=rel_path,
                    extension=ext,
                    size_bytes=size,
                )
            )

    # Sort deterministically by relative path
    discovered.sort(key=lambda f: f.relative_path)
    return discovered
