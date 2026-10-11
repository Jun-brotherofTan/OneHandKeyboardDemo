"""Collect public GitHub Python files as UTF-8 text without executing them."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"
MANIFEST_NAME = "corpus_python_manifest.csv"
MANIFEST_FIELDS = (
    "local_path",
    "repository",
    "owner",
    "repo_name",
    "github_url",
    "source_path",
    "default_branch",
    "stars",
    "size_bytes",
    "license",
    "commit_sha",
    "collected_at",
    "sha256",
)
IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".github",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "site-packages",
        "node_modules",
        "build",
        "dist",
        "vendor",
        "vendors",
        "dep",
        "deps",
        "dependencies",
        "third_party",
        "third-party",
        "generated",
        "gen",
        "migrations",
        ".tox",
        ".nox",
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)
GENERATED_FILE_PATTERNS = (
    re.compile(r"(?:^|_)pb2(?:_grpc)?\.py$", re.IGNORECASE),
    re.compile(r"(?:^|_)generated(?:_[^/]*)?\.py$", re.IGNORECASE),
)
LICENSE_UNKNOWN = {"", "NOASSERTION", "UNKNOWN"}
RATE_LIMIT_WARNING_THRESHOLD = 2


class GitHubApiError(RuntimeError):
    """A non-rate-limit GitHub API or response error."""


class RateLimitReached(GitHubApiError):
    """Raised when continuing could exhaust the GitHub REST API quota."""

    def __init__(self, remaining: int | None):
        super().__init__("GitHub API rate limit is exhausted or nearly exhausted.")
        self.remaining = remaining


@dataclass(frozen=True)
class CollectionOptions:
    repos: int = 30
    files_per_repo: int = 5
    seed: int = 7
    output_dir: Path = Path("corpus_python")
    min_stars: int = 10
    max_stars: int = 5000
    pushed_after: str | None = None
    min_file_bytes: int = 500
    max_file_bytes: int = 100_000
    require_license: bool = False
    licenses: tuple[str, ...] = ()
    diverse: bool = False
    dry_run: bool = False
    resume: bool = False
    clear_output: bool = False


@dataclass
class CollectionStats:
    repositories_searched: int = 0
    repositories_sampled: int = 0
    repositories_successfully_used: int = 0
    files_considered: int = 0
    files_downloaded: int = 0
    files_reused: int = 0
    duplicates_skipped: int = 0
    files_skipped_by_size: int = 0
    files_skipped_by_encoding: int = 0
    files_skipped_by_ignored_path: int = 0
    api_requests_used: int = 0
    rate_limit_remaining: int | None = None
    total_collected_bytes: int = 0


def candidate_pool_size(repository_target: int) -> int:
    """Fetch a broader pool than the requested sample, bounded to 100-300."""
    return min(300, max(100, repository_target * 5))


def build_search_query(options: CollectionOptions) -> str:
    parts = [
        "language:Python",
        f"stars:{options.min_stars}..{options.max_stars}",
        "fork:false",
        "archived:false",
    ]
    if options.pushed_after:
        parts.append(f"pushed:>{options.pushed_after}")
    return " ".join(parts)


def repository_license(repository: dict) -> str:
    license_info = repository.get("license") or {}
    spdx_id = license_info.get("spdx_id") or ""
    return "" if spdx_id.upper() in LICENSE_UNKNOWN else spdx_id


def filter_repositories(
    repositories: Iterable[dict],
    *,
    min_stars: int,
    max_stars: int,
    require_license: bool = False,
    licenses: Iterable[str] = (),
) -> list[dict]:
    allowed_licenses = {item.casefold() for item in licenses}
    selected = []
    for repository in repositories:
        stars = repository.get("stargazers_count", 0)
        if not isinstance(stars, int) or not min_stars <= stars <= max_stars:
            continue
        if repository.get("archived") or repository.get("fork"):
            continue
        if repository.get("size", 0) <= 0:
            continue
        license_id = repository_license(repository)
        if require_license and not license_id:
            continue
        if allowed_licenses and license_id.casefold() not in allowed_licenses:
            continue
        selected.append(repository)
    return selected


def _diversity_key(repository: dict) -> tuple[str, ...] | None:
    topics = repository.get("topics") or []
    if topics:
        return tuple(sorted(str(topic).casefold() for topic in topics))
    description = repository.get("description") or ""
    words = re.findall(r"[a-z0-9]+", description.casefold())
    generic = {"python", "project", "library", "framework", "for", "and", "the"}
    key = tuple(word for word in words if word not in generic)[:3]
    return key or None


def sample_repositories(
    repositories: list[dict],
    count: int,
    rng: random.Random,
    *,
    diverse: bool = False,
) -> list[dict]:
    ordered = sorted(repositories, key=lambda repository: repository.get("full_name", ""))
    if not diverse:
        return rng.sample(ordered, min(count, len(ordered)))

    shuffled = ordered
    rng.shuffle(shuffled)
    selected = []
    remainder = []
    seen_categories = set()
    for repository in shuffled:
        category = _diversity_key(repository)
        if category is None or category not in seen_categories:
            selected.append(repository)
            if category is not None:
                seen_categories.add(category)
        else:
            remainder.append(repository)
    return (selected + remainder)[:count]


def sample_files(files: list[dict], count: int, rng: random.Random) -> list[dict]:
    shuffled = sorted(files, key=lambda entry: entry.get("path", ""))
    rng.shuffle(shuffled)
    return shuffled[:count]


def ignored_source_path(source_path: str) -> bool:
    normalized = source_path.replace("\\", "/")
    parts = [part.casefold() for part in normalized.split("/") if part]
    if any(part.startswith(".") or part in IGNORED_DIRECTORY_NAMES for part in parts):
        return True
    if any(pattern.search(parts[-1] if parts else "") for pattern in GENERATED_FILE_PATTERNS):
        return True
    return any(
        "/".join(parts[index : index + 2]) == "docs/_build"
        for index in range(max(0, len(parts) - 1))
    )


def file_size_is_eligible(size: int | None, minimum: int, maximum: int) -> bool:
    return size is not None and minimum <= size <= maximum


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def is_duplicate_content(content: bytes, known_hashes: set[str]) -> bool:
    return content_sha256(content) in known_hashes


def _safe_component(component: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", component).strip(" .")
    return safe if safe not in {"", ".", ".."} else "item"


def output_path_for_source(
    output_dir: Path,
    owner: str,
    repo_name: str,
    source_path: str,
    digest: str | None = None,
) -> Path:
    """Flatten a Git path safely and add hashes to prevent filename collisions."""
    repository_dir = f"{_safe_component(owner)}__{_safe_component(repo_name)}"
    path_parts = [
        _safe_component(part)
        for part in source_path.replace("\\", "/").split("/")
        if part not in {"", ".", ".."}
    ]
    flattened = "__".join(path_parts) or "source.py"
    if flattened.casefold().endswith(".py"):
        flattened = flattened[:-3]
    flattened = flattened[:160]
    path_digest = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:12]
    digest_part = f"__{digest[:12]}" if digest else ""
    filename = f"{flattened}__{path_digest}{digest_part}.py"
    output_root = output_dir.resolve()
    target = (output_dir / repository_dir / filename).resolve()
    if output_root not in target.parents:
        raise ValueError("output path escapes the selected output directory")
    return target


def read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _validated_manifest_path(output_dir: Path, local_path: str) -> Path | None:
    root = output_dir.resolve()
    candidate = (output_dir / local_path).resolve()
    if root not in candidate.parents:
        return None
    return candidate


def _existing_python_files(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = [name for name in subdirectories if not name.startswith(".")]
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.lower() == ".py" and not path.is_symlink():
                yield path


def load_resume_state(
    output_dir: Path,
    manifest_rows: list[dict[str, str]],
) -> tuple[set[str], dict[tuple[str, str, str], dict[str, str]]]:
    known_hashes = set()
    for path in _existing_python_files(output_dir):
        try:
            known_hashes.add(content_sha256(path.read_bytes()))
        except OSError:
            continue

    cached_files = {}
    for row in manifest_rows:
        digest = row.get("sha256", "")
        local_path = _validated_manifest_path(output_dir, row.get("local_path", ""))
        if not digest or local_path is None or not local_path.is_file():
            continue
        try:
            if content_sha256(local_path.read_bytes()) != digest:
                continue
        except OSError:
            continue
        key = (row.get("repository", ""), row.get("source_path", ""), row.get("commit_sha", ""))
        cached_files[key] = row
        known_hashes.add(digest)
    return known_hashes, cached_files


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        opener: Callable = None,
        log: Callable[[str], None] = print,
    ):
        self.token = token
        self.opener = opener or urllib.request.urlopen
        self.log = log
        self.api_requests_used = 0
        self.rate_limit_remaining: int | None = None
        self._warned_about_rate_limit = False

    def _observe_rate_limit(self, headers) -> None:
        value = headers.get("X-RateLimit-Remaining") if headers else None
        if value is None:
            return
        try:
            self.rate_limit_remaining = int(value)
        except (TypeError, ValueError):
            return
        if (
            self.rate_limit_remaining <= RATE_LIMIT_WARNING_THRESHOLD
            and not self._warned_about_rate_limit
        ):
            self.log(
                "GitHub API rate limit is low: "
                f"{self.rate_limit_remaining} request(s) remaining; stopping before exhaustion."
            )
            self._warned_about_rate_limit = True

    def get_json(self, endpoint: str, params: dict[str, str | int] | None = None) -> dict:
        if self.rate_limit_remaining is not None and self.rate_limit_remaining <= 1:
            raise RateLimitReached(self.rate_limit_remaining)
        url = f"{API_ROOT}{endpoint}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "OneHandKeyboardDemo-corpus-collector",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        self.api_requests_used += 1
        try:
            with self.opener(request, timeout=30) as response:
                self._observe_rate_limit(response.headers)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            self._observe_rate_limit(error.headers)
            if error.code in {403, 429}:
                raise RateLimitReached(self.rate_limit_remaining) from None
            raise GitHubApiError(f"GitHub API request failed (HTTP {error.code}).") from None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GitHubApiError(
                f"GitHub API response could not be read ({type(error).__name__})."
            ) from None

    def get_raw(self, url: str) -> bytes:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "OneHandKeyboardDemo-corpus-collector"},
        )
        with self.opener(request, timeout=30) as response:
            return response.read()


class PythonCorpusCollector:
    def __init__(
        self,
        options: CollectionOptions,
        *,
        client: GitHubClient | None = None,
        token: str | None = None,
        log: Callable[[str], None] = print,
        now: Callable[[], datetime] | None = None,
    ):
        self.options = options
        self.log = log
        self.client = client or GitHubClient(token, log=log)
        self.rng = random.Random(options.seed)
        self.stats = CollectionStats()
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.output_dir = options.output_dir
        self.manifest_path = Path.cwd() / MANIFEST_NAME
        self.manifest_rows: list[dict[str, str]] = []
        self.known_hashes: set[str] = set()
        self.cached_files: dict[tuple[str, str, str], dict[str, str]] = {}

    def _prepare_output(self) -> None:
        if self.options.clear_output:
            clear_output(self.output_dir, self.manifest_path)
        self.manifest_rows = read_manifest(self.manifest_path)
        self.known_hashes, self.cached_files = load_resume_state(
            self.output_dir, self.manifest_rows
        )

    def _search_repositories(self) -> list[dict]:
        desired_pool_size = candidate_pool_size(self.options.repos)
        valid_repositories = []
        seen = set()
        page = 1
        raw_count = 0
        while len(valid_repositories) < desired_pool_size and page <= 3:
            response = self.client.get_json(
                "/search/repositories",
                {
                    "q": build_search_query(self.options),
                    "sort": "updated",
                    "order": "desc",
                    "per_page": 100,
                    "page": page,
                },
            )
            items = response.get("items", [])
            raw_count += len(items)
            self.stats.repositories_searched = raw_count
            filtered = filter_repositories(
                items,
                min_stars=self.options.min_stars,
                max_stars=self.options.max_stars,
                require_license=self.options.require_license,
                licenses=self.options.licenses,
            )
            for repository in filtered:
                full_name = repository.get("full_name", "")
                if full_name and full_name not in seen:
                    valid_repositories.append(repository)
                    seen.add(full_name)
            if len(items) < 100:
                break
            page += 1
        return valid_repositories[:desired_pool_size]

    def _fetch_tree(self, repository: dict) -> tuple[str, str, list[dict]]:
        owner = repository.get("owner", {}).get("login", "")
        repo_name = repository.get("name", "")
        branch = repository.get("default_branch", "")
        if not owner or not repo_name or not branch:
            raise GitHubApiError("Repository metadata is missing its owner, name, or default branch.")
        branch_path = urllib.parse.quote(branch, safe="")
        commit = self.client.get_json(f"/repos/{owner}/{repo_name}/commits/{branch_path}")
        commit_sha = commit.get("sha", "")
        tree_sha = commit.get("commit", {}).get("tree", {}).get("sha", "")
        if not commit_sha or not tree_sha:
            raise GitHubApiError("GitHub did not return a commit and tree SHA.")
        tree = self.client.get_json(
            f"/repos/{owner}/{repo_name}/git/trees/{tree_sha}", {"recursive": 1}
        )
        if tree.get("truncated"):
            raise GitHubApiError("Repository tree was truncated by GitHub; skipping it.")
        return commit_sha, branch, tree.get("tree", [])

    def _eligible_files(self, tree: list[dict]) -> list[dict]:
        eligible = []
        for entry in tree:
            source_path = entry.get("path", "")
            if entry.get("type") != "blob" or not source_path.endswith(".py"):
                continue
            self.stats.files_considered += 1
            if ignored_source_path(source_path):
                self.stats.files_skipped_by_ignored_path += 1
                continue
            if not file_size_is_eligible(
                entry.get("size"), self.options.min_file_bytes, self.options.max_file_bytes
            ):
                self.stats.files_skipped_by_size += 1
                continue
            eligible.append(entry)
        return eligible

    def _raw_url(self, repository: dict, commit_sha: str, source_path: str) -> str:
        owner = repository["owner"]["login"]
        repo_name = repository["name"]
        return (
            f"{RAW_ROOT}/{urllib.parse.quote(owner, safe='')}"
            f"/{urllib.parse.quote(repo_name, safe='')}"
            f"/{commit_sha}/{urllib.parse.quote(source_path, safe='/')}"
        )

    def _manifest_row(
        self,
        repository: dict,
        commit_sha: str,
        branch: str,
        source_path: str,
        size_bytes: int,
        digest: str,
        local_path: Path,
    ) -> dict[str, str]:
        owner = repository.get("owner", {}).get("login", "")
        repo_name = repository.get("name", "")
        full_name = repository.get("full_name", f"{owner}/{repo_name}")
        github_path = urllib.parse.quote(source_path, safe="/")
        return {
            "local_path": local_path.relative_to(self.output_dir.resolve()).as_posix(),
            "repository": full_name,
            "owner": owner,
            "repo_name": repo_name,
            "github_url": f"https://github.com/{full_name}/blob/{commit_sha}/{github_path}",
            "source_path": source_path,
            "default_branch": branch,
            "stars": str(repository.get("stargazers_count", "")),
            "size_bytes": str(size_bytes),
            "license": repository_license(repository) or "UNKNOWN",
            "commit_sha": commit_sha,
            "collected_at": self.now().astimezone(timezone.utc).isoformat(),
            "sha256": digest,
        }

    def _collect_repository(self, repository: dict) -> int:
        commit_sha, branch, tree = self._fetch_tree(repository)
        candidates = self._eligible_files(tree)
        candidates = sample_files(candidates, len(candidates), self.rng)
        repository_id = repository.get("full_name", "")
        selected_count = 0
        if self.options.dry_run:
            chosen = candidates[: self.options.files_per_repo]
            for entry in chosen:
                self.log(f"Would collect {repository_id}:{entry['path']} ({entry['size']} bytes)")
            return len(chosen)

        for entry in candidates:
            if selected_count >= self.options.files_per_repo:
                break
            source_path = entry["path"]
            cache_key = (repository_id, source_path, commit_sha)
            cached = self.cached_files.get(cache_key) if self.options.resume else None
            if cached:
                selected_count += 1
                self.stats.files_reused += 1
                continue

            try:
                content = self.client.get_raw(self._raw_url(repository, commit_sha, source_path))
            except urllib.error.HTTPError as error:
                self.log(f"Skipping {repository_id}:{source_path}: download HTTP {error.code}.")
                continue
            except (OSError, urllib.error.URLError) as error:
                self.log(
                    f"Skipping {repository_id}:{source_path}: download failed ({type(error).__name__})."
                )
                continue

            try:
                content.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                self.stats.files_skipped_by_encoding += 1
                self.log(f"Skipping {repository_id}:{source_path}: content is not valid UTF-8.")
                continue

            digest = content_sha256(content)
            if digest in self.known_hashes:
                self.stats.duplicates_skipped += 1
                continue

            local_path = output_path_for_source(
                self.output_dir,
                repository["owner"]["login"],
                repository["name"],
                source_path,
                digest,
            )
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)
            self.known_hashes.add(digest)
            self.manifest_rows.append(
                self._manifest_row(
                    repository,
                    commit_sha,
                    branch,
                    source_path,
                    len(content),
                    digest,
                    local_path,
                )
            )
            self.stats.files_downloaded += 1
            selected_count += 1
        return selected_count

    def _update_summary_stats(self) -> None:
        self.stats.api_requests_used = self.client.api_requests_used
        self.stats.rate_limit_remaining = self.client.rate_limit_remaining
        if self.output_dir.is_dir():
            self.stats.total_collected_bytes = sum(
                path.stat().st_size for path in _existing_python_files(self.output_dir)
            )

    def _print_summary(self) -> None:
        self.log(f"Repositories searched: {self.stats.repositories_searched}")
        self.log(f"Repositories sampled: {self.stats.repositories_sampled}")
        if self.options.dry_run:
            self.log(
                "Repositories with eligible samples (dry-run): "
                f"{self.stats.repositories_successfully_used}"
            )
        else:
            self.log(f"Repositories successfully used: {self.stats.repositories_successfully_used}")
        self.log(f"Files considered: {self.stats.files_considered}")
        self.log(f"Files downloaded: {self.stats.files_downloaded}")
        self.log(f"Files reused from manifest: {self.stats.files_reused}")
        self.log(f"Duplicates skipped: {self.stats.duplicates_skipped}")
        self.log(f"Files skipped by size: {self.stats.files_skipped_by_size}")
        self.log(f"Files skipped by encoding: {self.stats.files_skipped_by_encoding}")
        self.log(f"Files skipped by ignored path: {self.stats.files_skipped_by_ignored_path}")
        self.log(f"GitHub API requests used: {self.stats.api_requests_used}")
        remaining = (
            "unknown" if self.stats.rate_limit_remaining is None else self.stats.rate_limit_remaining
        )
        self.log(f"GitHub API rate-limit remaining: {remaining}")
        size_label = (
            "Existing output source size (dry-run)"
            if self.options.dry_run
            else "Total collected source size"
        )
        self.log(f"{size_label}: {self.stats.total_collected_bytes} bytes")

    def run(self) -> CollectionStats:
        if not self.client.token:
            self.log(
                "Warning: GITHUB_TOKEN is not set; unauthenticated GitHub API rate limits are much lower."
            )
        try:
            self._prepare_output()
            repositories = self._search_repositories()
            self.stats.repositories_sampled = min(self.options.repos, len(repositories))
            sampled = sample_repositories(
                repositories,
                self.options.repos,
                self.rng,
                diverse=self.options.diverse,
            )
            for repository in sampled:
                try:
                    used_count = self._collect_repository(repository)
                except RateLimitReached as error:
                    remaining = "unknown" if error.remaining is None else error.remaining
                    self.log(
                        f"Stopping collection at the GitHub API rate limit ({remaining} remaining); "
                        "no automatic retry will be attempted."
                    )
                    break
                except GitHubApiError as error:
                    self.log(f"Skipping repository {repository.get('full_name', '')}: {error}")
                    continue
                if used_count:
                    self.stats.repositories_successfully_used += 1
            if not self.options.dry_run:
                write_manifest(self.manifest_path, self.manifest_rows)
                self.log(f"Manifest: {self.manifest_path}")
        except RateLimitReached as error:
            remaining = "unknown" if error.remaining is None else error.remaining
            self.log(
                f"Stopping collection at the GitHub API rate limit ({remaining} remaining); "
                "no automatic retry will be attempted."
            )
        except GitHubApiError as error:
            self.log(f"Collection stopped: {error}")
        finally:
            self._update_summary_stats()
            self._print_summary()
        return self.stats


def clear_output(output_dir: Path, manifest_path: Path) -> None:
    resolved = output_dir.resolve()
    current = Path.cwd().resolve()
    if resolved == resolved.parent or resolved == current or resolved in current.parents:
        raise ValueError("refusing to clear a filesystem root or a directory containing the workspace")
    if output_dir.is_symlink():
        output_dir.unlink()
    elif output_dir.exists():
        shutil.rmtree(output_dir)
    manifest_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repos", type=int, default=30)
    parser.add_argument("--files-per-repo", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output-dir", type=Path, default=Path("corpus_python"))
    parser.add_argument("--min-stars", type=int, default=10)
    parser.add_argument("--max-stars", type=int, default=5000)
    parser.add_argument("--pushed-after", help="include repositories pushed after YYYY-MM-DD")
    parser.add_argument("--min-file-bytes", type=int, default=500)
    parser.add_argument("--max-file-bytes", type=int, default=100_000)
    parser.add_argument("--require-license", action="store_true")
    parser.add_argument("--licenses", nargs="+", default=())
    parser.add_argument("--diverse", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--clear-output", action="store_true")
    return parser


def options_from_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> CollectionOptions:
    if args.repos < 1 or args.files_per_repo < 1:
        parser.error("--repos and --files-per-repo must be at least 1")
    if args.min_stars < 0 or args.max_stars < args.min_stars:
        parser.error("star bounds are invalid")
    if args.min_file_bytes < 0 or args.max_file_bytes < args.min_file_bytes:
        parser.error("file size bounds are invalid")
    if args.pushed_after:
        try:
            date.fromisoformat(args.pushed_after)
        except ValueError:
            parser.error("--pushed-after must use YYYY-MM-DD")
    if args.dry_run and args.clear_output:
        parser.error("--clear-output cannot be combined with --dry-run")
    return CollectionOptions(
        repos=args.repos,
        files_per_repo=args.files_per_repo,
        seed=args.seed,
        output_dir=args.output_dir,
        min_stars=args.min_stars,
        max_stars=args.max_stars,
        pushed_after=args.pushed_after,
        min_file_bytes=args.min_file_bytes,
        max_file_bytes=args.max_file_bytes,
        require_license=args.require_license,
        licenses=tuple(args.licenses),
        diverse=args.diverse,
        dry_run=args.dry_run,
        resume=args.resume,
        clear_output=args.clear_output,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    options = options_from_args(parser.parse_args(argv), parser)
    token = os.environ.get("GITHUB_TOKEN")
    try:
        PythonCorpusCollector(options, token=token).run()
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())