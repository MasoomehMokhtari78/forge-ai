"""
GitHub URL validation and normalization service.
"""

import re
from urllib.parse import urlparse

# GitHub username: 1-39 alphanumeric characters or single hyphens, not starting/ending with hyphen
GITHUB_OWNER_REGEX = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$")
# GitHub repo name: 1-100 alphanumeric characters, hyphens, underscores, or periods
GITHUB_REPO_REGEX = re.compile(r"^[a-zA-Z0-9_.-]{1,100}$")


class InvalidRepositoryURLError(ValueError):
    """Raised when a repository URL is not a valid public GitHub URL."""
    pass


def validate_and_normalize_github_url(url: str) -> tuple[str, str]:
    """Validate and normalize a public GitHub repository URL.

    Accepts formats such as:
      - https://github.com/owner/repo
      - https://github.com/owner/repo/
      - https://github.com/owner/repo.git
      - https://github.com/owner/repo.git/

    Returns:
      (normalized_url, repository_name)
      Example: ('https://github.com/torvalds/linux', 'torvalds/linux')

    Raises:
      InvalidRepositoryURLError if the URL format is invalid or unsupported.
    """
    if not url or not isinstance(url, str):
        raise InvalidRepositoryURLError("Repository URL must be a non-empty string.")

    cleaned_url = url.strip()

    try:
        parsed = urlparse(cleaned_url)
    except Exception as exc:
        raise InvalidRepositoryURLError(f"Malformed URL: {exc}") from exc

    # Only HTTPS is supported for public repository ingestion
    if parsed.scheme.lower() != "https":
        raise InvalidRepositoryURLError("Only public GitHub repositories over HTTPS are supported.")

    # Hostname must be github.com (or www.github.com)
    netloc = parsed.netloc.lower()
    if netloc not in {"github.com", "www.github.com"}:
        raise InvalidRepositoryURLError("Only GitHub (github.com) repositories are supported.")

    # Reject URLs with query parameters or fragments
    if parsed.query or parsed.fragment:
        raise InvalidRepositoryURLError("Repository URL must not contain query parameters or fragments.")

    # Process path segments
    path = parsed.path.strip("/")
    if not path:
        raise InvalidRepositoryURLError("URL must contain repository owner and name.")

    segments = path.split("/")
    if len(segments) != 2:
        raise InvalidRepositoryURLError(
            "URL must contain exactly an owner and repository name (e.g. https://github.com/owner/repo)."
        )

    owner, repo = segments

    # Strip optional .git suffix from repository name
    if repo.endswith(".git"):
        repo = repo[:-4]

    # Disallow empty strings or special dot paths
    if not owner or not repo or repo in {".", ".."}:
        raise InvalidRepositoryURLError("Invalid owner or repository name in URL.")

    # Validate against GitHub naming conventions
    if not GITHUB_OWNER_REGEX.match(owner):
        raise InvalidRepositoryURLError(f"Invalid GitHub owner name: '{owner}'.")

    if not GITHUB_REPO_REGEX.match(repo):
        raise InvalidRepositoryURLError(f"Invalid GitHub repository name: '{repo}'.")

    normalized_url = f"https://github.com/{owner}/{repo}"
    repository_name = f"{owner}/{repo}"

    return normalized_url, repository_name
