import csv
import tempfile
import unittest
from pathlib import Path

from corpus_analyzer import analyze_path, analyze_text, write_csv
from shortcut_optimizer import encoded_keystrokes, optimize_shortcuts, write_selected_csv


class CorpusAnalyzerTests(unittest.TestCase):
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