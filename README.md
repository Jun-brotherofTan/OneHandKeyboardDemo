# OneHandKeyboardDemo

## Corpus shortcut analyzer

The analyzer ranks complete words and arbitrary overlapping substrings separately.
For each candidate it reports frequency, length, keystrokes saved per use, total
potential savings, and `score = frequency * (length - shortcut_cost)`.

```bash
python analyze_corpus.py tests/data --csv results.csv --min-frequency 2
```

The input can also be one `.txt` file. Results are printed to the terminal and
written to the requested CSV. Substring occurrences overlap by design; for
example, `aa` occurs three times in `aaaa`.

The analyzer also includes a greedy overlap-aware optimizer. It repeatedly
tests every remaining candidate, simulates the whole corpus with dynamic
programming, and selects the candidate with the largest additional reduction.
The simulation allows either one literal character or one selected shortcut at
each position, so overlapping matches cannot save the same characters twice.

```bash
python analyze_corpus.py tests/data \
	--csv candidates.csv \
	--selected-csv selected_shortcuts.csv \
	--num-shortcuts 20
```

The optimizer reports original and optimized keystrokes, total and percentage
savings, and the selected shortcuts. Its greedy choices are not guaranteed to
be globally optimal, and it can only select candidates present in the analyzed
candidate lists. The selected-shortcut CSV includes selection order and
marginal savings.

Run tests with:

```bash
python -m unittest discover -s tests -v
```

## Mirrored alphabet optimizer

The one-handed keyboard optimizer keeps the normal QWERTY layer fixed and
assigns the 11 unused alphabet letters (`hijklmnopuy`) to the 11 alphabet
slots on the same 15 physical keys. The four conventional punctuation slots
remain fixed. Physical positions are represented by `(row, column)` and each
position has a fixed left-hand finger owner. The corpus is lowercased, filtered
to ASCII letters, and reduced to precomputed unigram and adjacent-letter
bigram frequencies. Each candidate layout is then scored from those tables
instead of rescanning the corpus.

Simulated annealing starts at the conventional mirror, swaps two alphabet
slots for each neighbor, accepts improvements and occasional worse layouts,
and uses `--seed` for reproducible results:

```bash
python optimize_mirror_layout.py corpus/ --iterations 10000 --seed 7 \
	--weight-repetition 10 --weight-row-jump 3 --weight-pinky 2 --weight-index 1 \
	--output-csv mirror_layout.csv
```

The command writes the physical-key mapping CSV and a companion
`mirror_layout.summary.csv` containing conventional and optimized values for
all four metrics, weighted cost, and compatibility columns named
`same_finger_count` and `same_finger_rate`. The objective is the weighted sum
of same-finger OR same-column repetition, row distance, left pinky usage, and
left index usage. The legacy `--weight-same-finger` option is accepted as an
alias for `--weight-repetition`.

The optimizer intentionally does not model finger travel, diagonal movement,
modifier frequency, subword shortcuts, punctuation, typing speed, key
pressure, hand size, or learning difficulty. These can be added later as
separate objective terms.

## Weight sensitivity experiments

`experiment_weights.py` reuses the existing corpus statistics and simulated
annealing optimizer to compare weight configurations. The default run uses
five configurations (A-E) and one seed, so it performs five optimization runs:

```bash
python experiment_weights.py corpus/ --iterations 50000 --seed 7
```

Run several seeds for mean, population standard deviation, best seed, and
layout-frequency stability:

```bash
python experiment_weights.py corpus/ --iterations 50000 --seeds 7 11 23
```

Custom CSV weights replace the defaults unless `--use-default-weights` is also
provided:

```bash
python experiment_weights.py corpus/ \
	--weights-csv weights.csv --use-default-weights --seeds 7 11 23
```

The CSV must contain `name,repetition,row_jump,pinky,index`. Optional grid
search generates every combination and warns when the run count exceeds 100:

```bash
python experiment_weights.py corpus/ --grid \
	--repetition-values 5 10 15 \
	--row-values 1 3 5 \
	--pinky-values 1 2 4 \
	--index-values 0.5 1
```

The runner prints all four ergonomic metrics, conventional-layout improvements,
Pareto-optimal configurations, layout similarity to the baseline weights
`10 / 3 / 2 / 1`, and three recommendations: lowest weighted cost, lowest
repetition, and a heuristic balanced Pareto result. It writes
`weight_experiment_results.csv`, `weight_experiment_summary.csv`, and one
`layout_<config>.csv` mapping per configuration. Pareto dominance uses only
the four raw ergonomic metrics, never weighted total cost.