# OneHandKeyboardDemo

## Python corpus collection

`collect_python_corpus.py` samples public Python repositories through GitHub's
REST API, then samples a few eligible `.py` files per repository. Repository
sampling uses a larger pool of up to 300 recently updated search results and
the supplied seed; file order is also randomized with that seed. `--diverse`
prefers distinct topic sets, falling back to description keywords when topics
are absent. This lightweight heuristic cannot reliably classify project
niches. Python files are fetched as bytes, strictly decoded as UTF-8, and saved
as text only; downloaded code is never executed. A provenance manifest is
written to `corpus_python_manifest.csv`.

An unauthenticated small test:

```bash
python collect_python_corpus.py \
	--repos 5 \
	--files-per-repo 3 \
	--seed 7
```

Normal collection:

```bash
python collect_python_corpus.py \
	--repos 30 \
	--files-per-repo 5 \
	--seed 7
```

For higher GitHub API limits, set `GITHUB_TOKEN` in the environment. The token
is sent only in the GitHub API authorization header and is never written to
disk or printed. Without it, the collector warns that unauthenticated limits
are lower. When the API limit is nearly exhausted, collection stops without
automatic retries. Repository filters include `--min-stars`, `--max-stars`,
and `--pushed-after YYYY-MM-DD`; file sizes default to 500 bytes through 100
KB and can be changed with `--min-file-bytes` and `--max-file-bytes`.

Licensed-only corpus:

```bash
python collect_python_corpus.py \
	--repos 30 \
	--files-per-repo 5 \
	--require-license \
	--licenses mit apache-2.0 bsd-3-clause
```

Dry run, which searches and inspects repository trees without writing source
files or a manifest:

```bash
python collect_python_corpus.py \
	--repos 30 \
	--files-per-repo 5 \
	--dry-run
```

Start with a small dry run before downloading:

```bash
python collect_python_corpus.py \
	--repos 5 \
	--files-per-repo 3 \
	--seed 7 \
	--dry-run
```

Existing corpus files are retained by default. Use `--resume` to reuse files
verified against their manifest hashes and avoid fetching the same
repository/path/commit again. `--clear-output` explicitly deletes the selected
output directory and the manifest; it cannot be combined with `--resume` or
`--dry-run`.

Collection does not grant redistribution rights. Check each source
repository's license and applicable terms before sharing or redistributing the
corpus; the manifest records provenance and reported license identifiers but
is not legal advice.

Analyze the collected source corpus:

```bash
python analyze_corpus.py corpus_python/ \
	--csv python_candidates.csv \
	--selected-csv python_shortcuts.csv \
	--num-shortcuts 20
```

Use it for a weight experiment:

```bash
python experiment_weights.py corpus_python/ \
	--iterations 50000 \
	--seeds 7 11 23
```

## Windows keyboard tester

The Windows-only tester uses the normal keyboard as input and opens a small
always-on-top overlay for the active left-hand area. Start it with a profile:

```powershell
python mirror_keyboard_test.py --layout layout_C.csv
```

Only `Q W E R T`, `A S D F G`, and `Z X C V B` are intercepted; other keys
pass through to Windows. The overlay keeps the active area bright, labels each
physical key with its current output, and dims the rest of the keyboard area.
Normal mode shows the physical letters, mirror modes use the loaded layout CSV,
and the active mode/profile plus recent key output appear in the status area.

Tap Right Alt once for a one-shot mirror after the double-tap interval; tap it
twice within 300 ms to latch mirror mode, then tap once to turn the latch off.
Change the interval with `--double-tap-ms`. Shortcut mode requires a valid
CSV mapping and can be loaded with `--shortcuts`:

```csv
physical_key,shortcut
q,self.
w,"import "
e,"return "
r,name
t,data
```

```powershell
python mirror_keyboard_test.py --layout layout_C.csv --shortcuts shortcuts.csv
```

`Ctrl+Alt+S` toggles between NORMAL and SHORTCUT. Without a loaded shortcut
profile, the mode does not change and the status reports `Shortcut profile not
loaded`. Mapped key presses suppress the original character and emit the CSV
string once; keys without a mapping pass through normally. Shortcut and mirror
layers are mutually exclusive. The older `--shortcut-profile` option is an
alias for `--shortcuts`.
Switch profiles with `Ctrl+Alt+1` through `Ctrl+Alt+5`, which load
`layout_A.csv` through `layout_E.csv` beside the selected layout file. The
overlay highlights the physical source key and reports the emitted character
or shortcut. Usage events are logged to the console only.

Emergency exit is `Ctrl+Alt+Esc`. It stops the keyboard hook, closes the
overlay, flushes the console log, and exits without installing drivers,
changing registry mappings, or persisting settings.

On Korean Windows, Right Alt may be reported as `VK_HANGUL` or as an extended
`scan 0x38` event instead of `VK_RMENU`. The hook recognizes these physical
Right Alt forms and passes the default Right Alt event through to Windows so
the IME can continue handling Hangul/English switching. Left Alt remains an
ordinary Alt key. Use `--verbose` to print VK, scan code, extended, direction,
and injected details for Alt/Hangul-related events; the overlay also shows the
last detected physical modifier. If the IME still consumes the event before
the hook sees it, choose another mirror key:

```powershell
python mirror_keyboard_test.py --layout layout_C.csv --mirror-key caps-lock --verbose
python mirror_keyboard_test.py --layout layout_C.csv --mirror-key f12 --verbose
```

## Corpus shortcut analyzer

The analyzer ranks complete words and arbitrary overlapping substrings separately.
For each candidate it reports frequency, length, keystrokes saved per use, total
potential savings, and `score = frequency * (length - shortcut_cost)`.

```bash
python analyze_corpus.py python_source/ --csv results.csv --min-frequency 2
```

The input can also be one `.txt` or `.py` file. Directory input reads `.txt`
files in the selected directory and `.py` files recursively. Python files are
treated as ordinary UTF-8 text and are never executed. Likely license and
copyright blocks in initial `.py` comment headers are removed by default;
`--keep-license-headers` disables this cleanup. `.txt` content is unchanged.
Hidden, generated, and dependency directories such as `.git`, `.venv`,
`__pycache__`, and `node_modules` are skipped. Results are printed to the
terminal and written to the requested CSV.
Substring occurrences overlap by design; for example, `aa` occurs three times
in `aaaa`.

Substring shortcuts must contain an ASCII letter, cannot contain a newline,
carriage return, or tab, and cannot begin with whitespace. This keeps the
default list focused on typeable code fragments such as `self.` and `return `.

The analyzer also includes a greedy overlap-aware optimizer. It repeatedly
tests every remaining candidate, simulates the whole corpus with dynamic
programming, and selects the candidate with the largest additional reduction.
The simulation allows either one literal character or one selected shortcut at
each position, so overlapping matches cannot save the same characters twice.

```bash
python analyze_corpus.py python_source/ \
	--csv candidates.csv \
	--selected-csv selected_shortcuts.csv \
	--num-shortcuts 20 \
	--max-optimizer-candidates 1000
```

The optimizer reports original and optimized keystrokes, total and percentage
savings, and the selected shortcuts. Its greedy choices are not guaranteed to
be globally optimal, and it can only select candidates present in the analyzed
candidate lists. Exact duplicate text candidates are collapsed, then candidates
are ranked by raw potential savings and limited to 1,000 by default. Progress
shows candidate evaluations and pruned candidates for each round, along with
round and total optimizer time. The selected-shortcut CSV includes selection
order and marginal savings.

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
python optimize_mirror_layout.py python_source/ --iterations 10000 --seed 7 \
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
python experiment_weights.py python_source/ --iterations 50000 --seed 7
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