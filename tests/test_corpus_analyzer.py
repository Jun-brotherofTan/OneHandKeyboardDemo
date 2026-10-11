import csv
import tempfile
import unittest
from pathlib import Path

from analyze_corpus import build_parser
from corpus_analyzer import (
    Candidate,
    analyze_path,
    analyze_text,
    clean_python_license_header,
    read_corpus,
    write_csv,
)
from shortcut_optimizer import (
    encoded_keystrokes,
    limit_optimizer_candidates,
    optimize_shortcuts,
    write_selected_csv,
)


class CorpusAnalyzerTests(unittest.TestCase):
    def test_spdx_and_copyright_header_is_removed(self):
        source = (
            "# Copyright 2024 Example Authors\n"
            "# SPDX-License-Identifier: Apache-2.0\n"
            "\n"
            "VALUE = 'kept'\n"
        )
        cleaned = clean_python_license_header(source)
        self.assertNotIn("Copyright", cleaned)
        self.assertNotIn("SPDX-License-Identifier", cleaned)
        self.assertIn("VALUE = 'kept'\n", cleaned)

    def test_apache_and_gpl_comment_blocks_are_removed(self):
        headers = (
            "# Licensed under the Apache License, Version 2.0\n"
            "\n"
            "# See the License for the specific language governing permissions.\n"
            "# Apache boilerplate continuation.\n",
            "# GNU GENERAL PUBLIC LICENSE\n"
            "# Version 3, 29 June 2007\n",
            "# GNU Affero General Public License\n"
            "# Version 3\n",
            "# MIT License\n"
            "# Permission is hereby granted, free of charge.\n",
        )
        for header in headers:
            with self.subTest(header=header.splitlines()[0]):
                cleaned = clean_python_license_header(header + "VALUE = 1\n")
                self.assertNotIn("License", cleaned)
                self.assertNotIn("boilerplate continuation", cleaned)
                self.assertIn("VALUE = 1\n", cleaned)

    def test_shebang_and_encoding_lines_survive_license_cleanup(self):
        source = (
            "#!/usr/bin/env python3\n"
            "# -*- coding: utf-8 -*-\n"
            "# Copyright 2025 Example\n"
            "# Licensed under the MIT License\n"
            "VALUE = 'unchanged'\n"
        )
        cleaned = clean_python_license_header(source)
        self.assertTrue(cleaned.startswith("#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n"))
        self.assertNotIn("Copyright", cleaned)
        self.assertNotIn("Licensed under", cleaned)
        self.assertTrue(cleaned.endswith("VALUE = 'unchanged'\n"))

    def test_normal_comments_after_code_are_not_removed(self):
        source = "VALUE = 1\n# Copyright is useful vocabulary here.\n"
        self.assertEqual(clean_python_license_header(source), source)

    def test_string_variables_containing_license_are_preserved(self):
        source = "LICENSE_TEXT = 'MIT License applies to this sample'\n"
        self.assertEqual(clean_python_license_header(source), source)

    def test_code_and_docstring_are_preserved(self):
        source = (
            "# Copyright 2024 Example\n"
            "# SPDX-License-Identifier: MIT\n"
            "\"\"\"Module documentation mentions license terms.\"\"\"\n"
            "def run():\n"
            "    # Keep this normal code comment.\n"
            "    return 'license'  # keep inline comment\n"
        )
        cleaned = clean_python_license_header(source)
        self.assertEqual(
            cleaned,
            "\"\"\"Module documentation mentions license terms.\"\"\"\n"
            "def run():\n"
            "    # Keep this normal code comment.\n"
            "    return 'license'  # keep inline comment\n",
        )

    def test_directory_cleans_python_headers_but_preserves_txt_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text(
                "# Copyright 2024 Example\n# MIT License\nVALUE = 1\n", encoding="utf-8"
            )
            txt = "# Copyright 2024 Example\nMIT License\nplain text\n"
            (root / "notes.txt").write_text(txt, encoding="utf-8")

            cleaned = read_corpus(root)
            self.assertNotIn("Copyright", cleaned.replace(txt, ""))
            self.assertIn(txt, cleaned)
            self.assertIn("VALUE = 1", cleaned)
            self.assertIn("# Copyright 2024 Example", read_corpus(root, keep_license_headers=True))

    def test_overlapping_substrings_are_counted(self):
        substrings, _ = analyze_text(
            "aaaa", minimum_frequency=1, minimum_length=2, maximum_length=2, shortcut_cost=0
        )
        self.assertEqual(substrings[0].text, "aa")
        self.assertEqual(substrings[0].frequency, 3)

    def test_words_are_separate_and_case_insensitive(self):
        _, words = analyze_text("One one other", minimum_frequency=2, shortcut_cost=0)
        self.assertEqual([(item.text, item.frequency) for item in words], [("one", 2)])

    def test_non_positive_scores_are_excluded(self):
        substrings, words = analyze_text(
            "ab ab", minimum_frequency=1, minimum_length=2, maximum_length=2, shortcut_cost=2
        )
        self.assertEqual(substrings, [])
        self.assertEqual(words, [])

    def test_substring_candidates_exclude_whitespace_and_punctuation_only(self):
        text = "        \n    ######## ........ --------"
        substrings, _ = analyze_text(
            text,
            minimum_frequency=1,
            minimum_length=2,
            maximum_length=8,
            shortcut_cost=1,
        )
        self.assertEqual(substrings, [])

    def test_substring_candidates_never_contain_newline_carriage_return_or_tab(self):
        text = "alpha\nbeta\ralpha\tbeta"
        substrings, _ = analyze_text(
            text,
            minimum_frequency=1,
            minimum_length=2,
            maximum_length=8,
            shortcut_cost=1,
        )
        self.assertTrue(substrings)
        self.assertTrue(all(not any(char in item.text for char in "\n\r\t") for item in substrings))
        self.assertIn("alpha", {item.text for item in substrings})

    def test_substring_candidates_exclude_leading_whitespace_but_keep_trailing_space(self):
        text = "return " * 3
        substrings, _ = analyze_text(
            text,
            minimum_frequency=2,
            minimum_length=2,
            maximum_length=8,
            shortcut_cost=1,
            top_n=1000,
        )
        candidate_texts = {item.text for item in substrings}
        self.assertFalse(any(item.text[0].isspace() for item in substrings))
        self.assertIn("return ", candidate_texts)

    def test_useful_programming_subwords_and_punctuation_suffix_remain(self):
        text = "self. return import tion ing\n" * 2
        substrings, _ = analyze_text(
            text,
            minimum_frequency=2,
            minimum_length=2,
            maximum_length=10,
            shortcut_cost=1,
            top_n=1000,
        )
        candidate_texts = {item.text for item in substrings}
        self.assertTrue({"self", "self.", "return", "import", "tion", "ing"}.issubset(candidate_texts))

    def test_optimizer_candidate_pool_keeps_highest_raw_savings_and_deduplicates(self):
        candidates = [
            Candidate("small", 2, 5, 3, 6, 6),
            Candidate("large", 10, 8, 6, 60, 60),
            Candidate("large", 5, 8, 6, 30, 30),
        ]
        limited = limit_optimizer_candidates(candidates, 1)
        self.assertEqual([item.text for item in limited], ["large"])
        self.assertEqual(limited[0].score, 60)

    def test_max_optimizer_candidates_defaults_to_1000(self):
        args = build_parser().parse_args(["corpus", "--csv", "results.csv"])
        self.assertEqual(args.max_optimizer_candidates, 1000)

    def test_keep_license_headers_flag_is_available(self):
        args = build_parser().parse_args(
            ["corpus", "--csv", "results.csv", "--keep-license-headers"]
        )
        self.assertTrue(args.keep_license_headers)

    def test_duplicate_text_candidates_are_evaluated_once(self):
        duplicate = Candidate("ab", 2, 2, 1, 2, 2)
        progress = []
        result = optimize_shortcuts(
            "abab",
            [duplicate, duplicate],
            num_shortcuts=1,
            shortcut_cost=1,
            progress_callback=progress.append,
        )
        self.assertEqual([item.text for item in result.selected_shortcuts], ["ab"])
        self.assertTrue(any(message.startswith("  candidates evaluated: 1/1") for message in progress))

    def test_greedy_selection_matches_existing_overlap_aware_dp(self):
        text = "ababaababab"
        substrings, words = analyze_text(
            text,
            minimum_frequency=1,
            minimum_length=2,
            maximum_length=5,
            shortcut_cost=1,
        )
        result = optimize_shortcuts(
            text,
            [*substrings, *words],
            num_shortcuts=3,
            shortcut_cost=1,
        )
        candidate_texts = sorted({item.text for item in [*substrings, *words]})
        expected_selected = []
        expected_cost = len(text)
        for _ in range(3):
            best_text = None
            best_cost = expected_cost
            for candidate_text in candidate_texts:
                if candidate_text in expected_selected:
                    continue
                candidate_cost = encoded_keystrokes(
                    text, [*expected_selected, candidate_text], 1
                )
                if candidate_cost < best_cost or (
                    candidate_cost == best_cost
                    and best_text is not None
                    and candidate_text < best_text
                ):
                    best_text = candidate_text
                    best_cost = candidate_cost
            if best_text is None or best_cost >= expected_cost:
                break
            expected_selected.append(best_text)
            expected_cost = best_cost

        selected = []
        for shortcut in result.selected_shortcuts:
            selected.append(shortcut.text)
            self.assertEqual(
                encoded_keystrokes(text, selected, 1),
                len(text) - shortcut.cumulative_keystrokes_saved,
            )
        self.assertEqual(
            result.optimized_keystroke_count,
            encoded_keystrokes(text, selected, 1),
        )
        self.assertEqual(selected, expected_selected)
        self.assertEqual(result.optimized_keystroke_count, expected_cost)
        self.assertGreaterEqual(result.elapsed_seconds, 0)
        self.assertGreaterEqual(len(result.selection_round_seconds), len(result.selected_shortcuts))
        self.assertLessEqual(len(result.selection_round_seconds), len(result.selected_shortcuts) + 1)

    def test_directory_input_and_csv_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "first.txt").write_text("alpha alpha", encoding="utf-8")
            (root / "second.txt").write_text("beta beta", encoding="utf-8")
            substrings, words = analyze_path(root, minimum_frequency=2, shortcut_cost=0)
            output = root / "results.csv"
            write_csv(output, substrings, words)
            with output.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertTrue(any(row["candidate_type"] == "word" for row in rows))
            self.assertIn("alpha", {row["substring"] for row in rows})

    def test_directory_reads_txt_and_nested_python_as_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            (root / "first.txt").write_text("from text", encoding="utf-8")
            (nested / "source.py").write_text('print("from python")', encoding="utf-8")
            (nested / "nested.txt").write_text("not included", encoding="utf-8")

            self.assertEqual(
                read_corpus(root), 'from text\nprint("from python")'
            )

    def test_directory_ignores_hidden_and_generated_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "visible.py").write_text("visible", encoding="utf-8")
            ignored_names = (
                ".hidden", ".git", ".venv", "venv", "__pycache__", "site-packages",
                "node_modules", "build", "dist",
            )
            for name in ignored_names:
                folder = root / name
                folder.mkdir()
                (folder / "ignored.py").write_text(name, encoding="utf-8")

            self.assertEqual(read_corpus(root), "visible")

    def test_optimizer_does_not_double_count_overlapping_shortcuts(self):
        substrings, words = analyze_text(
            "information",
            minimum_frequency=1,
            minimum_length=2,
            maximum_length=11,
            shortcut_cost=2,
        )
        candidate_texts = {candidate.text for candidate in substrings}
        self.assertTrue({"tion", "ation", "information"}.issubset(candidate_texts))

        result = optimize_shortcuts(
            "information",
            [*substrings, *words],
            num_shortcuts=3,
            shortcut_cost=2,
        )

        self.assertEqual([item.text for item in result.selected_shortcuts], ["information"])
        self.assertEqual(result.original_character_count, 11)
        self.assertEqual(result.optimized_keystroke_count, 2)
        self.assertEqual(result.total_keystrokes_saved, 9)
        self.assertEqual(encoded_keystrokes("information", ["tion", "ation"], 2), 8)

    def test_selected_shortcuts_have_csv_output(self):
        _, words = analyze_text("hello hello", minimum_frequency=1)
        result = optimize_shortcuts("hello hello", words, num_shortcuts=1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "selected.csv"
            write_selected_csv(output, result)
            self.assertIn("shortcut", output.read_text(encoding="utf-8").splitlines()[0])


if __name__ == "__main__":
    unittest.main()