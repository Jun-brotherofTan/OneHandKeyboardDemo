import csv
import json
import random
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from collect_python_corpus import (
    API_ROOT,
    MANIFEST_FIELDS,
    CollectionOptions,
    GitHubClient,
    PythonCorpusCollector,
    build_search_query,
    clear_output,
    content_sha256,
    file_size_is_eligible,
    filter_repositories,
    ignored_source_path,
    is_duplicate_content,
    output_path_for_source,
    read_manifest,
    sample_files,
    sample_repositories,
    write_manifest,
)


class FakeResponse:
    def __init__(self, body, headers=None):
        self.body = body
        self.headers = headers or {"X-RateLimit-Remaining": "5000"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def repository(
    name="project",
    *,
    owner="sample-owner",
    stars=100,
    archived=False,
    fork=False,
    size=100,
    license_id="MIT",
    topics=None,
):
    return {
        "full_name": f"{owner}/{name}",
        "owner": {"login": owner},
        "name": name,
        "default_branch": "main",
        "stargazers_count": stars,
        "archived": archived,
        "fork": fork,
        "size": size,
        "license": {"spdx_id": license_id} if license_id else None,
        "topics": topics or [],
        "description": "A sample Python project",
    }


def fake_opener(files=None, *, repos=None, response_remaining="5000", request_log=None):
    files = files or {"src/module.py": b"x" * 600}
    repos = repos or [repository()]
    request_log = request_log if request_log is not None else []
    tree = [
        {"path": path, "type": "blob", "size": len(content), "sha": f"blob-{index}"}
        for index, (path, content) in enumerate(files.items())
    ]

    def opener(request, timeout=30):
        request_log.append(request)
        url = request.full_url
        if url.startswith(API_ROOT):
            if "/search/repositories?" in url:
                payload = {"items": repos}
            elif "/commits/" in url:
                payload = {
                    "sha": "commit-sha",
                    "commit": {"tree": {"sha": "tree-sha"}},
                }
            elif "/git/trees/" in url:
                payload = {"truncated": False, "tree": tree}
            else:
                raise AssertionError(f"Unexpected API request: {url}")
            return FakeResponse(
                json.dumps(payload).encode("utf-8"),
                {"X-RateLimit-Remaining": response_remaining},
            )

        path_parts = urllib.parse.urlparse(url).path.split("/")
        source_path = urllib.parse.unquote("/".join(path_parts[4:]))
        return FakeResponse(files[source_path])

    opener.requests = request_log
    return opener


def collector_for(directory, files=None, **option_changes):
    option_values = {
        "repos": 1,
        "files_per_repo": 1,
        "seed": 7,
        "output_dir": Path(directory) / "corpus_python",
        "min_file_bytes": 0,
        "max_file_bytes": 100_000,
    }
    option_values.update(option_changes)
    options = CollectionOptions(**option_values)
    messages = []
    opener = fake_opener(files)
    client = GitHubClient("test-token", opener=opener, log=messages.append)
    collector = PythonCorpusCollector(options, client=client, log=messages.append)
    collector.manifest_path = Path(directory) / "corpus_python_manifest.csv"
    return collector, messages


class PythonCorpusCollectorTests(unittest.TestCase):
    def test_repository_filters_apply_stars_and_empty_repository(self):
        repos = [
            repository("valid", stars=10),
            repository("few-stars", stars=9),
            repository("many-stars", stars=5001),
            repository("empty", size=0),
        ]
        selected = filter_repositories(repos, min_stars=10, max_stars=5000)
        self.assertEqual([item["name"] for item in selected], ["valid"])

    def test_archived_repositories_are_excluded(self):
        selected = filter_repositories(
            [repository("active"), repository("archived", archived=True)],
            min_stars=0,
            max_stars=5000,
        )
        self.assertEqual([item["name"] for item in selected], ["active"])

    def test_forks_are_excluded(self):
        selected = filter_repositories(
            [repository("original"), repository("fork", fork=True)],
            min_stars=0,
            max_stars=5000,
        )
        self.assertEqual([item["name"] for item in selected], ["original"])

    def test_search_query_contains_configured_repository_filters(self):
        options = CollectionOptions(min_stars=12, max_stars=456, pushed_after="2025-01-02")
        query = build_search_query(options)
        self.assertIn("language:Python", query)
        self.assertIn("stars:12..456", query)
        self.assertIn("fork:false", query)
        self.assertIn("archived:false", query)
        self.assertIn("pushed:>2025-01-02", query)

    def test_ignored_directory_and_generated_file_detection(self):
        for path in (
            ".github/workflows/test.py",
            "vendor/module.py",
            "deps/external/module.py",
            "dependencies/package/module.py",
            "docs/_build/rendered.py",
            "app/__pycache__/module.py",
            "api/schema_pb2.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(ignored_source_path(path))
        self.assertFalse(ignored_source_path("src/application.py"))

    def test_file_size_filter_includes_boundaries(self):
        self.assertTrue(file_size_is_eligible(500, 500, 100_000))
        self.assertTrue(file_size_is_eligible(100_000, 500, 100_000))
        self.assertFalse(file_size_is_eligible(499, 500, 100_000))
        self.assertFalse(file_size_is_eligible(100_001, 500, 100_000))
        self.assertFalse(file_size_is_eligible(None, 500, 100_000))

    def test_repository_sampling_is_reproducible(self):
        repos = [repository(f"repo-{index}") for index in range(50)]
        first = sample_repositories(repos, 8, random.Random(7))
        second = sample_repositories(repos, 8, random.Random(7))
        self.assertEqual(first, second)

    def test_repository_sampling_changes_with_seed(self):
        repos = [repository(f"repo-{index}") for index in range(50)]
        first = sample_repositories(repos, 8, random.Random(7))
        second = sample_repositories(repos, 8, random.Random(8))
        self.assertNotEqual(first, second)

    def test_seeded_sampling_is_independent_of_api_result_order(self):
        repos = [repository(f"repo-{index}") for index in range(50)]
        files = [{"path": f"src/file_{index}.py"} for index in range(40)]
        self.assertEqual(
            sample_repositories(repos, 8, random.Random(7)),
            sample_repositories(list(reversed(repos)), 8, random.Random(7)),
        )
        self.assertEqual(
            sample_files(files, 7, random.Random(7)),
            sample_files(list(reversed(files)), 7, random.Random(7)),
        )

    def test_file_sampling_is_reproducible_and_seeded(self):
        files = [{"path": f"src/file_{index}.py"} for index in range(40)]
        first = sample_files(files, 7, random.Random(7))
        second = sample_files(files, 7, random.Random(7))
        other_seed = sample_files(files, 7, random.Random(8))
        self.assertEqual(first, second)
        self.assertNotEqual(first, other_seed)

    def test_sha256_duplicate_detection(self):
        content = b"same source bytes"
        known = {content_sha256(content)}
        self.assertTrue(is_duplicate_content(content, known))
        self.assertFalse(is_duplicate_content(b"different", known))

    def test_manifest_writing_preserves_requested_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.csv"
            row = {field: f"value-{field}" for field in MANIFEST_FIELDS}
            write_manifest(path, [row])
            self.assertEqual(read_manifest(path), [row])
            with path.open(encoding="utf-8", newline="") as stream:
                self.assertEqual(next(csv.reader(stream)), list(MANIFEST_FIELDS))

    def test_output_path_sanitizes_traversal_and_prevents_collisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "corpus"
            first = output_path_for_source(root, "../owner", "repo", "../../escape.py", "a" * 64)
            second = output_path_for_source(root, "../owner", "repo", "nested/escape.py", "b" * 64)
            self.assertIn(root.resolve(), first.parents)
            self.assertNotIn("..", first.parts)
            self.assertNotEqual(first, second)

    def test_license_filters_require_recognized_matching_spdx(self):
        repos = [
            repository("mit", license_id="MIT"),
            repository("apache", license_id="Apache-2.0"),
            repository("unknown", license_id="NOASSERTION"),
        ]
        selected = filter_repositories(
            repos,
            min_stars=0,
            max_stars=5000,
            require_license=True,
            licenses=("apache-2.0",),
        )
        self.assertEqual([item["name"] for item in selected], ["apache"])

    def test_dry_run_inspects_tree_without_writing_or_downloading_files(self):
        with tempfile.TemporaryDirectory() as directory:
            collector, messages = collector_for(directory, dry_run=True)
            collector.output_dir.mkdir()
            existing_file = collector.output_dir / "existing.py"
            existing_file.write_bytes(b"keep existing corpus")
            collector.run()
            self.assertEqual(existing_file.read_bytes(), b"keep existing corpus")
            self.assertFalse(collector.manifest_path.exists())
            self.assertEqual(collector.stats.files_downloaded, 0)
            self.assertTrue(any("Would collect" in message for message in messages))
            self.assertFalse(
                any(
                    "raw.githubusercontent.com" in request.full_url
                    for request in collector.client.opener.requests
                )
            )

    def test_utf8_decode_failure_is_skipped_and_valid_text_is_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            collector, _ = collector_for(
                directory,
                {"bad.py": b"\xff\xfe", "good.py": b"print('text')"},
                files_per_repo=2,
            )
            collector.run()
            self.assertEqual(collector.stats.files_skipped_by_encoding, 1)
            self.assertEqual(collector.stats.files_downloaded, 1)
            saved = list(collector.output_dir.rglob("*.py"))
            self.assertEqual([path.read_bytes() for path in saved], [b"print('text')"])

    def test_resume_reuses_manifest_match_without_redownloading(self):
        with tempfile.TemporaryDirectory() as directory:
            collector, _ = collector_for(directory, resume=True)
            content = b"x" * 600
            digest = content_sha256(content)
            local_path = output_path_for_source(
                collector.output_dir, "sample-owner", "project", "src/module.py", digest
            )
            local_path.parent.mkdir(parents=True)
            local_path.write_bytes(content)
            collector.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            write_manifest(
                collector.manifest_path,
                [
                    {
                        "local_path": local_path.relative_to(collector.output_dir).as_posix(),
                        "repository": "sample-owner/project",
                        "source_path": "src/module.py",
                        "commit_sha": "commit-sha",
                        "sha256": digest,
                    }
                ],
            )

            collector.run()

            raw_requests = [
                request
                for request in collector.client.opener.requests
                if request.full_url.startswith("https://raw.githubusercontent.com")
            ]
            self.assertEqual(collector.stats.files_reused, 1)
            self.assertEqual(collector.stats.files_downloaded, 0)
            self.assertEqual(raw_requests, [])

    def test_github_token_is_sent_but_never_logged(self):
        secret = "do-not-print-this-token"
        requests = []
        messages = []

        def opener(request, timeout=30):
            requests.append(request)
            return FakeResponse(
                json.dumps({"items": []}).encode("utf-8"),
                {"X-RateLimit-Remaining": "5000"},
            )

        with tempfile.TemporaryDirectory() as directory:
            options = CollectionOptions(repos=1, output_dir=Path(directory) / "out", dry_run=True)
            client = GitHubClient(secret, opener=opener, log=messages.append)
            collector = PythonCorpusCollector(options, client=client, log=messages.append)
            collector.manifest_path = Path(directory) / "manifest.csv"
            collector.run()

        self.assertIn(f"Bearer {secret}", requests[0].get_header("Authorization"))
        self.assertNotIn(secret, "\n".join(messages))

    def test_rate_limit_stops_without_retrying(self):
        requests = []
        messages = []

        def opener(request, timeout=30):
            requests.append(request)
            return FakeResponse(
                json.dumps({"items": [repository()]}).encode("utf-8"),
                {"X-RateLimit-Remaining": "1"},
            )

        with tempfile.TemporaryDirectory() as directory:
            options = CollectionOptions(repos=1, output_dir=Path(directory) / "out", dry_run=True)
            client = GitHubClient("token", opener=opener, log=messages.append)
            collector = PythonCorpusCollector(options, client=client, log=messages.append)
            collector.manifest_path = Path(directory) / "manifest.csv"
            collector.run()

        self.assertEqual(len(requests), 1)
        self.assertEqual(collector.stats.rate_limit_remaining, 1)
        self.assertTrue(any("no automatic retry" in message for message in messages))

    def test_clear_output_requires_call_and_removes_only_selected_corpus(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "corpus"
            output.mkdir()
            (output / "old.py").write_text("old", encoding="utf-8")
            manifest = root / "manifest.csv"
            manifest.write_text("old manifest", encoding="utf-8")
            clear_output(output, manifest)
            self.assertFalse(output.exists())
            self.assertFalse(manifest.exists())


if __name__ == "__main__":
    unittest.main()