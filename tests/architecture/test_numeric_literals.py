"""The numeric literal guard: no number in the engine decides cognition from inside the code.

Round 2 of the Metacat finish, ruling 53.  The user, verbatim: "configuration MUST INCLUDE
EVERYTHING THAT DETERMINES COGNITIVE BEHAVIOUR IN Metacat Mode!"  Stage 5 moved every number it
found into ``seed_data/engine_params.json`` and ``seed_data/formula_coefficients.json``; this is the
numeric counterpart of ``test_vocabulary_literals.py``, so that the rule holds after the next edit.

Test 1 is an AST walk of every ``.py`` file under ``server/engine/`` and ``server/parallel/`` for an
``int`` or ``float`` literal (a ``True`` or ``False`` is not a number here, and a ``-1`` is the
literal ``-1``).  A hit is allowed only in one of two ways:

* **A syntactic shape that cannot be a weight** (``SHAPES``): a constant list or tuple index
  (``x[0]``, ``x[-1]``, ``row[4]``) and a constant slice bound (``x[1:]``, ``x[:-1]``).  These two
  are all there is.  A subscript position is a place in a layout, never a quantity, and nothing a
  run computes with can hide in one.  A comparison with a constant, ``x * 2``, ``+= 1`` and
  ``range(n)`` are *not* shapes, because a threshold, a factor or a count is exactly what this guard
  is for: each is listed below with its reason.
* **An entry of ``ENTRIES``**: keyed by file, enclosing function and literal, with the count of
  hits.  The list is strict in both directions: a hit not listed fails, a count that differs
  fails, and an entry that is no longer hit fails (delete it).  Every entry carries its class
  and a reason (``REASONS``):

  * ``UNIT``: an arithmetic fact.  The reason says why giving it another value is meaningless: a
    list position, an arity, an off-by-one, the origin of a scale, a conversion on the fixed 0-100
    percent scale, a probability's bounds, the shape of a curve.
  * ``NONCOG-KEEP``: it affects no cognition and has a job: display, logging, I/O, process and
    hardware limits, bookkeeping.  The reason says what the job is.

A number that could change what a run does is configuration, never an entry.  Judging an entry:
could changing it change a codelet chosen, a random draw, an activation, a strength, an urgency, a
probability, the temperature, a structure built or broken, an answer or a decision, and is it
meaningless to give it another value?  Commentary thresholds, the floor of the local-support
exponent's denominator, and the nine others stage 5 had missed were found by this walk and moved
(see ``seed_data/README.md``).

Test 2 checks the table itself: every class is ``UNIT`` or ``NONCOG-KEEP``, every reason key is
defined and used, and every reason says something.

To list the current hits that no entry covers: ``.venv/bin/python tests/architecture/test_numeric_literals.py``.
To print the counts: ``... test_numeric_literals.py --counts``.
"""

from __future__ import annotations

import ast
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TREES = (REPO_ROOT / "server" / "engine", REPO_ROOT / "server" / "parallel")

CLASSES = ("UNIT", "NONCOG-KEEP")


def _shape(node: ast.Constant, top: ast.AST, parent: ast.AST) -> str | None:
    """The closed syntactic shape this literal has, or ``None`` when it needs an entry.

    ``top`` is the literal, or the ``-literal`` that wraps it; ``parent`` is what holds ``top``.
    """
    if isinstance(parent, ast.Subscript) and parent.slice is top:
        return "index"
    if isinstance(parent, ast.Slice) and top in (parent.lower, parent.upper, parent.step):
        return "slice"
    return None


def walk_literals() -> tuple[Counter, Counter]:
    """``(hits, shapes)``: the counts by ``(file, function, literal)``, and by shape."""
    hits: Counter = Counter()
    shapes: Counter = Counter()
    for tree_root in TREES:
        for path in sorted(tree_root.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            tree = ast.parse(path.read_text())
            parents: dict[ast.AST, ast.AST] = {}
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    parents[child] = node
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and type(node.value) in (int, float)):
                    continue
                top, parent, value = node, parents[node], node.value
                if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.USub):
                    top, parent, value = parent, parents[parent], -value
                shape = _shape(node, top, parent)
                if shape:
                    shapes[shape] += 1
                    continue
                names: list[str] = []
                scope: ast.AST = node
                while scope in parents:
                    scope = parents[scope]
                    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        names.append(scope.name)
                function = ".".join(reversed(names)) or "<module>"
                hits[(rel, function, repr(value))] += 1
    return hits, shapes


def _entry_counts() -> Counter:
    counts: Counter = Counter()
    for key, rows in ENTRIES.items():
        counts[key] = sum(n for n, _, _ in rows)
    return counts


def test_every_number_in_the_engine_is_accounted_for():
    hits, _ = walk_literals()
    listed = _entry_counts()
    unlisted = sorted(k for k in hits if k not in listed)
    wrong = sorted((k, hits[k], listed[k]) for k in hits if k in listed and hits[k] != listed[k])
    gone = sorted(k for k in listed if k not in hits)
    message = []
    if unlisted:
        message.append(
            "a number literal in the engine that no entry covers (a weight belongs in "
            "seed_data/engine_params.json or formula_coefficients.json and is read from the run's "
            "constants; only an arithmetic fact or a non-cognitive job is listed):\n  "
            + "\n  ".join(f"{k} x{hits[k]}" for k in unlisted))
    if wrong:
        message.append("an entry whose count differs from the hits:\n  "
                       + "\n  ".join(f"{k}: hits {h}, listed {n}" for k, h, n in wrong))
    if gone:
        message.append("an entry that is no longer hit (delete it):\n  " + "\n  ".join(map(str, gone)))
    assert not message, "\n\n".join(message)


def test_the_table_is_well_formed():
    used = set()
    for key, rows in ENTRIES.items():
        assert rows, key
        for n, cls, reason in rows:
            assert n > 0, key
            assert cls in CLASSES, (key, cls)
            assert reason in REASONS, (key, reason)
            used.add(reason)
    assert used == set(REASONS), f"reasons never used: {sorted(set(REASONS) - used)}"
    for reason, text in REASONS.items():
        assert len(text) >= 30, reason


def test_the_shapes_are_only_positions():
    """The two exempt shapes absorb a constant index and a constant slice bound, and nothing else."""
    _, shapes = walk_literals()
    assert set(shapes) <= {"index", "slice"}


def _main() -> None:
    hits, shapes = walk_literals()
    listed = _entry_counts()
    if "--counts" in sys.argv:
        by_class: Counter = Counter()
        for key, rows in ENTRIES.items():
            for n, cls, _ in rows:
                by_class[cls] += n
        print("hits:", sum(hits.values()) + sum(shapes.values()), "| shapes:", dict(shapes),
              "| listed hits:", dict(by_class), "| entries:", len(ENTRIES))
        return
    for key in sorted(hits):
        if hits[key] != listed.get(key):
            print(key, hits[key], listed.get(key))



REASONS: dict[str, str] = {
    'ACCESS_HISTORY': (
        'how many recent accesses the speculative conflict recorder keeps for diagnosis'),
    'ARITY_PAIR': (
        'two is the arity of the structure tested (a bond joins two objects, an interior letter has two sides, a swap is a pair of opposite slippages), not a weight'),
    'BACKEND_POLICY': (
        'when the vectorised or GPU backend is worth its set-up cost, and the largest activation a float32 array holds exactly; they choose a backend and refuse an inexact one, never change a value'),
    'BATCH_OF_ONE': (
        'select_backend(1) asks for the backend for a batch of one run: the batch size, not a weight'),
    'BITMASK': (
        'one bit per component in the effects mask: a bit-set encoding'),
    'BOOL01': (
        '0 and 1 are the two values of the justify flag'),
    'CACHE_SIZE': (
        'the size of an lru_cache in the start check'),
    'CEIL_DIV': (
        "ceil(n / ceil(n / max_line)) balances a line break over the fewest lines; zero is the empty line's length"),
    'CHAOS_HASH': (
        'the multiplicative hash and 16-bit mask of the chaos hook, which aborts chosen speculations to test recovery; it is how the executor is tested and is not set by any route'),
    'CLOCK_ORIGIN': (
        'the codelet clock is thread-local; a thread that has not stamped it yet is at codelet zero, the origin of the count'),
    'COUNT_DEFAULT': (
        'dict.get(key, 0) on a counter: an unseen key has been counted zero times'),
    'COUNT_STEP': (
        'a counter counts one occurrence (+= 1, -= 1, or a one in a sum of ones); the step is one by definition of counting'),
    'DECADE_BASE': (
        "10 is the base of the decade that math.log10 counts in the same function; both name 'a power of ten'"),
    'EEG_DISPLAY': (
        "the ring buffer, averaging window and starting value of the EEG strip chart (Metacat's graphic); drawn, never read back by a run"),
    'EXACT_ARITH': (
        'whole-number arithmetic that rounds an exact ratio half to even (2 * remainder, the low bit, a ratio of 0 over 1, 100 * numerator): how rounding is defined, not a weight'),
    'EXACT_DECAY': (
        'the exact form of the decay (1 - (depth/100) ** e) of a whole exponent, written as a ratio of whole numbers over the 0-100 scale; the exponent is configured'),
    'EXECUTOR_PACING': (
        'capacity, timeouts, spin counts, windows, telemetry counters and call-site arguments of the parallel executors: how fast and how widely work runs, never which work runs; the speculative executor equals the reference for any of them'),
    'FORMAT_VERSION': (
        'the version number of a stored or served format, read by whoever loads it'),
    'FORMULA_SIZE': (
        'the largest posting formula the compiler accepts; it refuses an oversized formula and changes none'),
    'HARDWARE': (
        'the machine probe: core counts, the reserved core, timeouts of the system calls and the power-of-two ladder of worker counts; they decide how many threads run, never what a run does'),
    'HASH_FORMAT': (
        "the length of the configuration hash and the hash scheme's version; identity of a record, not behaviour"),
    'INSERT_FRONT': (
        "insert(0, x) puts x at the front of a list, which is Metacat's cons; position zero is the front, not a weight"),
    'LEN_ONE': (
        'len(x) compared with one separates one element from several (a singular from a plural, a single choice from a draw): an arity, not a threshold'),
    'LEN_PAIR': (
        "len(x) compared with two is the arity of a pair (a swap, a bond's two objects, a two-item list in prose): a structural fact of the object tested"),
    'LEN_SHAPE3': (
        "len(x) compared with three tests the shape of a (dimension, relation, descriptor) tuple, a data layout of the engine's own"),
    'LEN_ZERO': (
        'len(x) compared with zero is an emptiness test'),
    'LETTER_LENGTH': (
        "a Letter has no length attribute, so a constituent that is a letter has length one; the default is the letter's length, tested against its siblings' lengths"),
    'MEAN_OF_N': (
        'the mean of two terms divides by two'),
    'METAL_LAYOUT': (
        'SIMD width, threadgroup size and the lanes of the Metal kernel launch; the same values come out whatever they are'),
    'MLX_PROBE': (
        'a one-line array computation that tests whether the GPU or the float64 CPU stream works'),
    'NUMERIC_UNIT': (
        "the same arithmetic as the Python engine formula this backend mirrors: zero floors and zero tests of an activation, means of two or three terms, a reciprocal, a uint8 flag or an array of zeros; a configured value is read from the run's parameters, none is repeated here"),
    'ONE_OF_N': (
        '1 - 1/n is the chance that a uniformly chosen one of n clamps is not the kept one: the shape of picking one of n'),
    'ORIGIN_IDENTITY': (
        'an origin or identity: 0 as the first codelet, cycle or entry, 1 as the one-based number of the codelet being run or the multiplicative identity of an unboosted factor'),
    'OS_QOS': (
        'macOS quality-of-service class values and priorities for threads: operating-system constants'),
    'PARAM_BOUNDS': (
        'the lower and upper bound of a run parameter, which refuse input and do not shape a run (ruling 24; they leave with the L15 package)'),
    'PATCH_COUNTER': (
        "the speculative executor's count of how many engines have patched the Bridge class; the attribute is created by the first patch, so its absence is the count zero"),
    'PCT_COMPLEMENT': (
        "100 - x is the complement of a 0-100 percent value (unhappiness from strength, the temperature's inverse); the scale's top is a unit fact (ruling 1)"),
    'PCT_COMPLEMENT_FLOOR': (
        'max(0.0, 100.0 - length) is the degree of association as the complement of a link length on the 0-100 scale, floored at zero'),
    'PCT_DIV': (
        'x / 100 converts a 0-100 percent value to a fraction; a different divisor would change the unit, not the value'),
    'PCT_MUL': (
        '100 * x converts a fraction to a 0-100 percent value that is then rounded; the scale is a unit fact (ruling 1)'),
    'PCT_POW': (
        '100 ** exponent is the percent scale raised to the whole exponent so that (depth/100) ** exponent is computed exactly; it follows the scale conversion'),
    'PCT_PRODUCT': (
        "100 is the percent scale: the product of strengths / 100 ** n, kept as exact whole numbers so that it rounds as Metacat's does"),
    'PCT_RATIO': (
        '100 - round(100 * ratio) is the percent complement of a ratio clipped to 1.0, and a ratio of 1.0 is the whole of the distance threshold; the threshold is a configured parameter'),
    'PLURAL_ONE': (
        "a count of one selects the singular of a word in the commentary text, or 'first' against 'another'; English grammar, not a weight"),
    'PLUS_ONE': (
        'an off-by-one between 0-based and 1-based positions or counts (the next index, the last index, the codelet being run, a rank), fixed by the indexing convention'),
    'POSITION_PREDICATE': (
        'the position arithmetic of a named initial-description condition (single, leftmost, rightmost, middle): which letter is where in a string of length n; the program that uses it is configuration'),
    'PROB_BOUND': (
        'a probability of at least 1.0 always succeeds and at most 0.0 never does, so the draw is skipped: the bounds of a probability'),
    'PROB_CAP': (
        'a probability cannot exceed 1.0, so min(1.0, ...) caps a scaled count; the scale count is a configured parameter'),
    'PRODUCT_IDENTITY': (
        '1.0 is the starting value of a product (the multiplicative identity)'),
    'RATIONAL_DISPLAY': (
        'a denominator of one prints an integer: display of an exact number'),
    'RATIONAL_PARSE': (
        "the numerator and denominator groups of the text 'a/b', and a denominator above zero: the syntax of a ratio"),
    'RECIPROCAL': (
        '1.0 / x is a reciprocal and 1.0 ** y the multiplicative identity in the exponent form base ** (1/max(floor, n ** e)); the floor and the exponent are configured'),
    'RNG_WORD': (
        "the 64-bit word, the 53 mantissa bits and the 11 shifted-out bits of the generator's arithmetic: the width of the numbers, not a tuning"),
    'ROW_SHAPE': (
        'the fifth column of a stored row, present or not: a data layout'),
    'SEED_DEFAULT': (
        "the seed a run takes when its caller names none (tests, scripts); every served run passes its seed. A seed is the run's input, not configuration, and carries no cognitive weight"),
    'SENTINEL_INDEX': (
        "-1 or an index of 1 beside a position: the sentinel 'not found', or the positions of the data layout, tested against themselves"),
    'SIGMOID_FORM': (
        'the constants 1 and 2 of the logistic 1/(1+e^-x) and the tanh form 2/(1+e^-2x)-1: the shape of the curve, with its steepness a configured coefficient'),
    'SIGN_ARG': (
        'the sign of the depth term (+1 for a bonus, -1 for a penalty) and the zero floor of a slippability: a direction, not a weight'),
    'SNAG_PICTURE_TEMP': (
        'the thermometer reading drawn in a stored picture of a snag; the picture is display and no run reads it back'),
    'SORT_KEY': (
        "a sort key, tuple tag or sort position (0 or 1 for 'this first', -1 for 'none') that only orders items the way Metacat's sort does"),
    'SQRT_EXACT': (
        '0.5 is the exponent for which math.sqrt and pow differ in the last bit (ruling 4); it only selects the exact routine, the exponent used is the configured one'),
    'STEP_KEY': (
        "the key of a step table (1, 2, 3 and 'more') whose values are configured rows named for it (group_length_factor_1, description_local_support_2 ...); the key is part of the row's name"),
    'STREAM_TAGS': (
        'distinct tags for the independent random streams of the speculative executor (body, clock, fallback, update, loop); any distinct values derive different streams, and none has a cognitive meaning'),
    'TAG_CODES': (
        "distinct integer tags (0 to 4) that mark a string's kind in the numeric arrays; any distinct values would do, and the names are bound by role"),
    'TEMP_GRID': (
        'the temperature table has one row for each whole percent, 0 to 100 (101 rows), and an index outside is clipped to the ends; the scale is a unit fact (ruling 7)'),
    'UNIT_COMPLEMENT': (
        "1 - x is the complement of a probability or a fraction; the scale's top is 1 by definition"),
    'VERBOSE_LOG': (
        'capacity, rule width and step cap of the Verbose narration, and the sequence number of its first entry; a log, read by no codelet'),
    'ZERO_CEILING': (
        'the share of a ceiling of zero is nothing (0.0), or all of the room is unfilled (1.0): the limit values of the quotient, fixed by the arithmetic'),
    'ZERO_DEFAULT': (
        "zero as an argument default that means 'start' or 'no limit' (a codelet count, a step cap of 0 for an unlimited run, a clamp of 0 cycles): a sentinel, not a weight"),
    'ZERO_DIVISOR_GUARD': (
        'max(1, count) keeps a count that serves as a divisor non-zero'),
    'ZERO_DIVISOR_WEIGHTS': (
        'weights summing to zero have no average; the pair (1, 0) over 1 returns the first term alone, as compute_temperature does; unreachable for any weights that average, so no other value has a meaning'),
    'ZERO_FLOOR': (
        'zero as the floor of a quantity that cannot be negative, or the value of an absent node, structure or set; changing it would give nothing a magnitude'),
    'ZERO_INIT': (
        "zero is the origin of the scale: the starting value of a counter, an accumulator or a field that is assigned before it is read; nothing is weighted by it, and another start would only mislabel 'none yet'"),
    'ZERO_KW': (
        "zero as a keyword argument that means 'start' or 'none' (a clamp of 0 cycles, a codelet count of 0): a sentinel, not a weight"),
    'ZERO_RESULT': (
        'zero as the value of nothing: the sum, count, share or quality of an empty set, returned for the degenerate case; any other number would invent a quantity from nothing'),
    'ZERO_TEST': (
        "a comparison with zero asks 'none, or which side of nothing': sign, emptiness or exhaustion of a quantity, not a threshold on a scale; the question has no other value"),
}

#: ``(file, enclosing function, literal) -> [(count, class, reason key)]``.  The literal is written as Python
#: spells it (``1`` and ``1.0`` are different literals).  ``<module>`` is a module-level literal.
ENTRIES: dict[tuple[str, str, str], list[tuple[int, str, str]]] = {
    # ---- server/engine/access.py
    ('server/engine/access.py', 'AccessRecorder.__init__', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/access.py', 'AccessRecorder.__init__', '200'): [(1, 'NONCOG-KEEP', 'ACCESS_HISTORY')],
    ('server/engine/access.py', 'AccessRecorder.summary', '0.0'): [(2, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/access.py', 'AccessRecorder.validate', '0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    ('server/engine/access.py', 'AccessRecorder.validate', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/access.py', 'AccessSet.record_write', '0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    ('server/engine/access.py', 'AccessSet.record_write', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/access.py', 'VersionTable.bump', '0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    ('server/engine/access.py', 'VersionTable.bump', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/access.py', 'VersionTable.version', '0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    ('server/engine/access.py', 'VersionTable.versions', '0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    # ---- server/engine/answer_comparison.py
    ('server/engine/answer_comparison.py', 'AnswerComparison.__init__', '0'): [(4, 'UNIT', 'ZERO_TEST')],
    ('server/engine/answer_comparison.py', 'AnswerComparison._incoherence', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/answer_comparison.py', '_bound_node_name', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/answer_comparison.py', '_criterion_fewer_unjustified', '0'): [(2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/answer_comparison.py', '_criterion_more_abstract_rule', '-1'): [(1, 'UNIT', 'SENTINEL_INDEX')],
    ('server/engine/answer_comparison.py', '_is_verbatim_signature', '0'): [(1, 'UNIT', 'LEN_ZERO')],
    ('server/engine/answer_comparison.py', '_is_verbatim_signature', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/answer_comparison.py', 'count_rule_differences', '-1'): [(1, 'UNIT', 'SENTINEL_INDEX')],
    ('server/engine/answer_comparison.py', 'count_rule_differences', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/answer_comparison.py', 'count_rule_differences', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/answer_comparison.py', 'punctuate_with_commas', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/answer_comparison.py', 'punctuate_with_commas', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    # ---- server/engine/answers.py
    ('server/engine/answers.py', '_attach_length_to_appropriate_groups', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/answers.py', '_conceptual_depth', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/answers.py', '_select_transform', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/answers.py', '_theme_abstractness', '2.0'): [(1, 'UNIT', 'MEAN_OF_N')],
    ('server/engine/answers.py', 'average_theme_abstractness', '0.0'): [(2, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/answers.py', '_unjustified_themes', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/answers.py', 'compute_answer_quality', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/answers.py', 'compute_answer_quality', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/answers.py', 'make_translated_string', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/answers.py', 'make_translated_string.bind_leaf', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    # ---- server/engine/bonds.py
    ('server/engine/bonds.py', 'Bond._bond_degree_of_assoc', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/bonds.py', 'Bond._local_support', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/bonds.py', 'Bond._local_support', '1.0'): [(1, 'UNIT', 'RECIPROCAL')],
    ('server/engine/bonds.py', 'Bond._local_support', '100.0'): [(1, 'UNIT', 'PCT_DIV'), (1, 'UNIT', 'PCT_MUL')],
    ('server/engine/bonds.py', 'Bond.get_local_density', '0'): [(1, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/bonds.py', 'Bond.get_local_density', '1'): [(2, 'UNIT', 'COUNT_STEP')],
    ('server/engine/bonds.py', 'Bond.get_local_density', '100.0'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/bonds.py', 'Bond.get_num_of_local_supporting_bonds', '0'): [(1, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/bonds.py', 'Bond.get_num_of_local_supporting_bonds', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/bonds.py', 'Bond.leftmost_in_string', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/bonds.py', 'Bond.rightmost_in_string', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    # ---- server/engine/bridges.py
    ('server/engine/bridges.py', 'Bridge._get_supporting_bridge_strength', '0.0'): [(1, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/bridges.py', 'Bridge.add_bond_concept_mapping', '0'): [(2, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/bridges.py', 'Bridge.add_concept_mapping', '0'): [(2, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/bridges.py', 'Bridge.add_symmetric_slippage', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/bridges.py', 'Bridge.calculate_internal_strength', '1'): [(1, 'UNIT', 'STEP_KEY')],
    ('server/engine/bridges.py', 'Bridge.calculate_internal_strength', '2'): [(1, 'UNIT', 'STEP_KEY')],
    ('server/engine/bridges.py', 'Bridge.get_average_theme_support', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/bridges.py', '_bridge_theme_compatibility_sigmoid', '-1.0'): [(1, 'UNIT', 'SIGMOID_FORM')],
    ('server/engine/bridges.py', '_bridge_theme_compatibility_sigmoid', '-2.0'): [(1, 'UNIT', 'SIGMOID_FORM')],
    ('server/engine/bridges.py', '_bridge_theme_compatibility_sigmoid', '1.0'): [(2, 'UNIT', 'SIGMOID_FORM')],
    ('server/engine/bridges.py', '_bridge_theme_compatibility_sigmoid', '2.0'): [(1, 'UNIT', 'SIGMOID_FORM')],
    ('server/engine/bridges.py', '_get_edge_bond', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/bridges.py', '_is_singleton_group', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/bridges.py', 'direction_incompatible_bridges', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    # ---- server/engine/codelet_dsl/builtins.py
    ('server/engine/codelet_dsl/builtins.py', '_absorb_duplicate_group', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/codelet_dsl/builtins.py', '_apply_group_flips', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/codelet_dsl/builtins.py', '_boost_themespace_activations', '1'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/codelet_dsl/builtins.py', '_build_structure_locked', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/codelet_dsl/builtins.py', '_consolidate_group', '1'): [(1, 'UNIT', 'LEN_ONE'), (2, 'UNIT', 'LETTER_LENGTH')],
    ('server/engine/codelet_dsl/builtins.py', '_punctuate', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/codelet_dsl/builtins.py', '_punctuate', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/codelet_dsl/builtins.py', '_record_group_event', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/codelet_dsl/builtins.py', '_report_answer_locked', '0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/codelet_dsl/builtins.py', '_report_answer_locked', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/codelet_dsl/builtins.py', '_slippage_importance', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR'), (1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/codelet_dsl/builtins.py', '_slippage_importance', '2.0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/codelet_dsl/builtins.py', '_slippage_importance.depth', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/codelet_dsl/builtins.py', 'choose_bond_facet', '0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/codelet_dsl/builtins.py', 'choose_bond_facet', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/codelet_dsl/builtins.py', 'choose_bond_facet', '100.0'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/codelet_dsl/builtins.py', 'descriptor_support', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/codelet_dsl/builtins.py', 'descriptor_support', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/codelet_dsl/builtins.py', 'descriptor_support', '100'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/codelet_dsl/builtins.py', 'evaluate_group', '1.0'): [(1, 'UNIT', 'UNIT_COMPLEMENT')],
    ('server/engine/codelet_dsl/builtins.py', 'evaluate_group', '100'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/codelet_dsl/builtins.py', 'evaluate_structure', '1.0'): [(1, 'UNIT', 'UNIT_COMPLEMENT')],
    ('server/engine/codelet_dsl/builtins.py', 'evaluate_structure', '100.0'): [(2, 'UNIT', 'PCT_DIV')],
    ('server/engine/codelet_dsl/builtins.py', 'get_activation', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/codelet_dsl/builtins.py', 'has_supported_rule', '0'): [(1, 'UNIT', 'LEN_ZERO')],
    ('server/engine/codelet_dsl/builtins.py', 'num_bonds_to_scan', '0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/codelet_dsl/builtins.py', 'num_bonds_to_scan', '2'): [(1, 'UNIT', 'ARITY_PAIR')],
    ('server/engine/codelet_dsl/builtins.py', 'record_event', '0.0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/engine/codelet_dsl/builtins.py', 'scan_bonds', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/codelet_dsl/builtins.py', 'scan_bonds', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/codelet_dsl/builtins.py', 'single_letter_group_probability', '1'): [(1, 'UNIT', 'STEP_KEY')],
    ('server/engine/codelet_dsl/builtins.py', 'single_letter_group_probability', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/codelet_dsl/builtins.py', 'single_letter_group_probability', '2'): [(1, 'UNIT', 'STEP_KEY')],
    # ---- server/engine/codelet_dsl/interpreter.py
    ('server/engine/codelet_dsl/interpreter.py', 'CodeletRegistry.__repr__', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    # ---- server/engine/coderack.py
    ('server/engine/coderack.py', 'Codelet.__init__', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/engine/coderack.py', 'Coderack.__init__', '0'): [(2, 'UNIT', 'ZERO_INIT')],
    ('server/engine/coderack.py', 'Coderack._pick_codelet_to_remove.build', '0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/coderack.py', 'Coderack._pick_codelet_to_remove.pick', '0'): [(2, 'UNIT', 'ZERO_FLOOR'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/coderack.py', 'Coderack._pick_codelet_to_remove.pick', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/coderack.py', 'Coderack._urgency_to_bin', '0'): [(1, 'UNIT', 'ZERO_RESULT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/coderack.py', 'Coderack._urgency_to_bin', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/coderack.py', 'Coderack.choose_and_remove', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/coderack.py', 'Coderack.choose_and_remove.pick', '0'): [(4, 'UNIT', 'ZERO_TEST')],
    ('server/engine/coderack.py', 'Coderack.clamped_posting_probability', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/coderack.py', 'Coderack.clear', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/coderack.py', 'Coderack.codelets_present', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/coderack.py', 'Coderack.get_codelet_type_counts', '0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    ('server/engine/coderack.py', 'Coderack.get_codelet_type_counts', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/coderack.py', 'Coderack.is_empty', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/coderack.py', 'Coderack.post', '1'): [(1, 'UNIT', 'COUNT_STEP'), (1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/coderack.py', 'Coderack.post_deferred', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/coderack.py', 'Coderack.post_deferred', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/coderack.py', 'Coderack.remove_old_codelets', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/coderack.py', 'CoderackBin.__init__', '0'): [(2, 'UNIT', 'ZERO_INIT')],
    ('server/engine/coderack.py', 'CoderackBin.age_sum', '0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/coderack.py', 'CoderackBin.clear', '0'): [(2, 'UNIT', 'ZERO_INIT')],
    ('server/engine/coderack.py', 'UrgencyValueTable.__init__', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/coderack.py', 'UrgencyValueTable.__init__', '100'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/coderack.py', 'UrgencyValueTable.__init__', '101'): [(1, 'UNIT', 'TEMP_GRID')],
    ('server/engine/coderack.py', 'UrgencyValueTable.index', '0'): [(1, 'UNIT', 'ZERO_RESULT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/coderack.py', 'UrgencyValueTable.index', '100'): [(2, 'UNIT', 'TEMP_GRID')],
    ('server/engine/coderack.py', '_bin_type_counts', '0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    ('server/engine/coderack.py', '_bin_type_counts', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/coderack.py', 'type_selection_probabilities', '0'): [(1, 'UNIT', 'COUNT_DEFAULT'), (1, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_TEST')],
    # ---- server/engine/commentary.py
    ('server/engine/commentary.py', 'CommentaryLog.add_comment', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/engine/commentary.py', 'CommentaryParagraph', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/commentary.py', 'CommentaryWriter.add_comment', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/engine/commentary.py', '_progress_key', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/commentary.py', 'emit_answer_discovered', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/commentary.py', 'emit_answer_unjustified', '1'): [(2, 'UNIT', 'PLURAL_ONE')],
    ('server/engine/commentary.py', 'emit_clamp_activate', '1'): [(1, 'UNIT', 'PLURAL_ONE')],
    ('server/engine/commentary.py', 'emit_new_problem', '0'): [(1, 'UNIT', 'ZERO_KW')],
    ('server/engine/commentary.py', 'emit_snag', '1'): [(1, 'UNIT', 'PLURAL_ONE')],
    # ---- server/engine/concept_mappings.py
    ('server/engine/concept_mappings.py', 'ConceptMapping.activate_label', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR'), (1, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/concept_mappings.py', 'ConceptMapping.conceptual_depth', '2.0'): [(1, 'UNIT', 'MEAN_OF_N')],
    ('server/engine/concept_mappings.py', 'ConceptMapping.slippability', '-1'): [(1, 'UNIT', 'SIGN_ARG')],
    ('server/engine/concept_mappings.py', 'ConceptMapping.slippability', '0.0'): [(2, 'UNIT', 'SIGN_ARG')],
    ('server/engine/concept_mappings.py', 'ConceptMapping.slippability', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/concept_mappings.py', 'ConceptMapping.strength', '1'): [(1, 'UNIT', 'SIGN_ARG')],
    ('server/engine/concept_mappings.py', 'ConceptMapping.strength', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/concept_mappings.py', 'SlippageLog.applied', '0'): [(2, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/concept_mappings.py', 'SlippageLog.coattail', '0'): [(2, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/concept_mappings.py', 'SlippageLog.get_applied_slippages', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/concept_mappings.py', 'SlippageLog.get_slippage_bridges', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/concept_mappings.py', '_is_whole', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/concept_mappings.py', '_rounded_depth_product', '100'): [(1, 'UNIT', 'PCT_POW')],
    # ---- server/engine/descriptions.py
    ('server/engine/descriptions.py', 'Description.calculate_external_strength', '2.0'): [(1, 'UNIT', 'MEAN_OF_N')],
    ('server/engine/descriptions.py', 'Description.calculate_local_support', '0'): [(1, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/descriptions.py', 'Description.calculate_local_support', '1'): [(1, 'UNIT', 'COUNT_STEP'), (1, 'UNIT', 'STEP_KEY')],
    ('server/engine/descriptions.py', 'Description.calculate_local_support', '2'): [(1, 'UNIT', 'STEP_KEY')],
    ('server/engine/descriptions.py', 'Description.calculate_local_support', '3'): [(1, 'UNIT', 'STEP_KEY')],
    # ---- server/engine/eeg.py
    ('server/engine/eeg.py', '<module>', '10'): [(1, 'NONCOG-KEEP', 'EEG_DISPLAY')],
    ('server/engine/eeg.py', '<module>', '100.0'): [(1, 'NONCOG-KEEP', 'EEG_DISPLAY')],
    ('server/engine/eeg.py', '<module>', '40'): [(1, 'NONCOG-KEEP', 'EEG_DISPLAY')],
    # ---- server/engine/formulas.py
    ('server/engine/formulas.py', 'bond_degree_of_assoc', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR'), (1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/formulas.py', 'group_evaluation_probability', '1.0'): [(2, 'UNIT', 'SIGMOID_FORM'), (1, 'UNIT', 'UNIT_COMPLEMENT')],
    ('server/engine/formulas.py', 'group_evaluation_probability', '100.0'): [(2, 'UNIT', 'PCT_DIV')],
    ('server/engine/formulas.py', 'group_evaluation_probability', '2.0'): [(1, 'UNIT', 'SIGMOID_FORM')],
    ('server/engine/formulas.py', 'length_description_probability', '1'): [(1, 'UNIT', 'STEP_KEY')],
    ('server/engine/formulas.py', 'pow_exact', '0.5'): [(1, 'UNIT', 'SQRT_EXACT')],
    ('server/engine/formulas.py', 'ratio_div', '0'): [(2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/formulas.py', 'round_exact', '1'): [(2, 'UNIT', 'EXACT_ARITH')],
    ('server/engine/formulas.py', 'round_ratio', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/formulas.py', 'round_ratio', '1'): [(1, 'UNIT', 'COUNT_STEP'), (1, 'UNIT', 'EXACT_ARITH')],
    ('server/engine/formulas.py', 'round_ratio', '2'): [(1, 'UNIT', 'EXACT_ARITH')],
    ('server/engine/formulas.py', 'share_of_ceiling', '0.0'): [(1, 'UNIT', 'ZERO_CEILING')],
    ('server/engine/formulas.py', 'sigmoid', '1.0'): [(2, 'UNIT', 'SIGMOID_FORM')],
    ('server/engine/formulas.py', 'temp_adjusted_probability', '0.0'): [(1, 'UNIT', 'ZERO_RESULT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/formulas.py', 'temp_adjusted_probability', '1.0'): [(2, 'UNIT', 'UNIT_COMPLEMENT')],
    ('server/engine/formulas.py', 'temp_adjusted_probability', '10.0'): [(1, 'UNIT', 'DECADE_BASE')],
    ('server/engine/formulas.py', 'temp_adjusted_values', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/formulas.py', 'temp_adjusted_values', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/formulas.py', 'temp_adjusted_values', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/formulas.py', 'unfilled_share_of_ceiling', '1.0'): [(1, 'UNIT', 'ZERO_CEILING')],
    ('server/engine/formulas.py', 'update_temperature', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/formulas.py', 'weighted_average', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/formulas.py', 'weighted_average', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    # ---- server/engine/frame.py
    ('server/engine/frame.py', 'Frame.__init__', '0'): [(1, 'UNIT', 'BOOL01')],
    ('server/engine/frame.py', 'Frame.__init__', '1'): [(1, 'UNIT', 'BOOL01')],
    # ---- server/engine/groups.py
    ('server/engine/groups.py', 'Group._local_support', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/groups.py', 'Group._local_support', '1.0'): [(1, 'UNIT', 'RECIPROCAL')],
    ('server/engine/groups.py', 'Group._local_support', '100.0'): [(1, 'UNIT', 'PCT_DIV'), (1, 'UNIT', 'PCT_MUL')],
    ('server/engine/groups.py', 'Group.calculate_internal_strength', '0'): [(2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/groups.py', 'Group.calculate_internal_strength', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/groups.py', 'Group.calculate_internal_strength', '1'): [(1, 'UNIT', 'STEP_KEY')],
    ('server/engine/groups.py', 'Group.calculate_internal_strength', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/groups.py', 'Group.calculate_internal_strength', '2'): [(1, 'UNIT', 'STEP_KEY')],
    ('server/engine/groups.py', 'Group.calculate_internal_strength', '3'): [(1, 'UNIT', 'STEP_KEY')],
    ('server/engine/groups.py', 'Group.get_local_density', '0'): [(1, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/groups.py', 'Group.get_local_density', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/groups.py', 'Group.get_local_density', '100.0'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/groups.py', 'Group.get_num_of_local_supporting_groups', '0'): [(1, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/groups.py', 'Group.get_num_of_local_supporting_groups', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/groups.py', 'attach_length_description', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    # ---- server/engine/hardware.py
    ('server/engine/hardware.py', '<module>', '1'): [(1, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', '<module>', '1024'): [(1, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', '<module>', '30.0'): [(1, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', '<module>', '5.0'): [(1, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', '<module>', '64'): [(1, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', '_int_from_environment', '0'): [(1, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', '_logical_cores', '1'): [(2, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', '_next_power_of_two', '1'): [(2, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', '_perflevel_split', '0'): [(4, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', '_perflevel_split', '1'): [(2, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', '_perflevel_split', '2'): [(1, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', 'gpu_info', '0'): [(2, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', 'population_worker_count', '0'): [(2, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', 'population_worker_count', '1'): [(1, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', 'worker_count', '0'): [(2, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', 'worker_count', '1'): [(1, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', 'worker_ladder', '1'): [(2, 'NONCOG-KEEP', 'HARDWARE')],
    ('server/engine/hardware.py', 'worker_ladder', '2'): [(1, 'NONCOG-KEEP', 'HARDWARE')],
    # ---- server/engine/hashing.py
    ('server/engine/hashing.py', '<module>', '2'): [(1, 'NONCOG-KEEP', 'HASH_FORMAT')],
    ('server/engine/hashing.py', '<module>', '32'): [(1, 'NONCOG-KEEP', 'HASH_FORMAT')],
    # ---- server/engine/ids.py
    ('server/engine/ids.py', 'IdAllocator.next', '0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    ('server/engine/ids.py', 'IdAllocator.next', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/ids.py', 'IdAllocator.peek', '0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    ('server/engine/ids.py', 'IdAllocator.reserve', '0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    # ---- server/engine/images.py
    ('server/engine/images.py', 'Image.is_letter_image', '0'): [(1, 'UNIT', 'LEN_ZERO')],
    ('server/engine/images.py', 'Image.shorten', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/images.py', 'Image.shorten', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/images.py', 'StringImage._constituent_images', '-1'): [(2, 'UNIT', 'SORT_KEY')],
    ('server/engine/images.py', 'StringImage._constituent_images', '0'): [(2, 'UNIT', 'SORT_KEY'), (1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/images.py', 'StringImage._constituent_images', '1'): [(1, 'UNIT', 'COUNT_STEP'), (1, 'UNIT', 'PLUS_ONE'), (1, 'UNIT', 'SORT_KEY')],
    ('server/engine/images.py', '_bonds_between', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/images.py', '_group_image_relations', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/images.py', 'enumerate_letter', '1'): [(1, 'UNIT', 'PLUS_ONE'), (1, 'UNIT', 'SORT_KEY')],
    ('server/engine/images.py', 'get_related_node', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/images.py', 'relationship_between', '1'): [(2, 'UNIT', 'LEN_ONE')],
    # ---- server/engine/initial_program.py
    ('server/engine/initial_program.py', '<module>', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/initial_program.py', '<module>', '1'): [(1, 'UNIT', 'PLUS_ONE'), (6, 'UNIT', 'POSITION_PREDICATE')],
    ('server/engine/initial_program.py', '<module>', '2'): [(2, 'UNIT', 'POSITION_PREDICATE')],
    ('server/engine/initial_program.py', 'add_initial_descriptions', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/initial_program.py', 'describe_group', '0'): [(2, 'UNIT', 'INSERT_FRONT')],
    # ---- server/engine/jootsing.py
    ('server/engine/jootsing.py', 'JootserResult.__init__', '0.0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/engine/jootsing.py', 'ProgressWatcherResult.__init__', '0.0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/engine/jootsing.py', '_average_description_depth', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/jootsing.py', '_build_theme_overlap_table', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/jootsing.py', '_build_theme_overlap_table', '100'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/jootsing.py', '_collect_all_theme_entries', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/jootsing.py', '_lookup_overlap', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/jootsing.py', '_partition_events', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/jootsing.py', '_unique_entries', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/jootsing.py', 'attempt_jootsing', '1.0'): [(1, 'UNIT', 'PROB_CAP'), (1, 'UNIT', 'UNIT_COMPLEMENT')],
    ('server/engine/jootsing.py', 'attempt_jootsing', '100.0'): [(4, 'UNIT', 'PCT_DIV')],
    ('server/engine/jootsing.py', 'check_progress', '0'): [(2, 'UNIT', 'ZERO_RESULT'), (2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/jootsing.py', 'check_progress', '0.0'): [(2, 'UNIT', 'ZERO_KW'), (3, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/jootsing.py', 'check_progress', '1.0'): [(2, 'UNIT', 'UNIT_COMPLEMENT')],
    ('server/engine/jootsing.py', 'check_progress', '100.0'): [(3, 'UNIT', 'PCT_DIV')],
    ('server/engine/jootsing.py', 'get_clamp_jootsing_probability', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/jootsing.py', 'get_clamp_jootsing_probability', '0.0'): [(1, 'UNIT', 'ZERO_INIT'), (2, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/jootsing.py', 'get_clamp_jootsing_probability', '1.0'): [(1, 'UNIT', 'PROB_CAP'), (1, 'UNIT', 'UNIT_COMPLEMENT')],
    ('server/engine/jootsing.py', 'get_clamp_jootsing_probability', '100'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/jootsing.py', 'get_clamp_jootsing_probability', '100.0'): [(2, 'UNIT', 'PCT_DIV')],
    ('server/engine/jootsing.py', 'joots_from_justify_clamps', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/jootsing.py', 'joots_from_justify_clamps', '1.0'): [(1, 'UNIT', 'ONE_OF_N'), (1, 'UNIT', 'UNIT_COMPLEMENT')],
    # ---- server/engine/justify.py
    ('server/engine/justify.py', 'JustificationResult.__init__', '0.0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/engine/justify.py', '_retention_probability', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/justify.py', '_retention_probability', '100.0'): [(2, 'UNIT', 'PCT_DIV')],
    ('server/engine/justify.py', '_theme_pattern_list_to_dict', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/justify.py', '_theme_pattern_to_dict', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/justify.py', 'attempt_justification', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/engine/justify.py', 'attempt_justification', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/justify.py', 'get_vertical_theme_pattern_to_clamp', '2'): [(3, 'UNIT', 'LEN_PAIR')],
    # ---- server/engine/memory.py
    ('server/engine/memory.py', 'AnswerDescription', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/memory.py', 'AnswerDescription', '0.0'): [(4, 'UNIT', 'ZERO_INIT')],
    ('server/engine/memory.py', 'AnswerDescription.is_coherent', '0.0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/memory.py', 'EpisodicMemory.clear_activations', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/memory.py', 'EpisodicMemory.distance', '-1'): [(1, 'UNIT', 'SENTINEL_INDEX')],
    ('server/engine/memory.py', 'EpisodicMemory.distance', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/memory.py', 'EpisodicMemory.find_remindings', '0'): [(1, 'UNIT', 'PCT_RATIO'), (2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/memory.py', 'EpisodicMemory.find_remindings', '1.0'): [(2, 'UNIT', 'PCT_RATIO')],
    ('server/engine/memory.py', 'EpisodicMemory.find_remindings', '100'): [(1, 'UNIT', 'PCT_COMPLEMENT'), (1, 'UNIT', 'PCT_MUL')],
    ('server/engine/memory.py', 'EpisodicMemory.store_answer', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/memory.py', 'EpisodicMemory.store_snag', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/memory.py', 'SnagDescription', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    # ---- server/engine/numeric/backend.py
    ('server/engine/numeric/backend.py', '<module>', '0'): [(1, 'NONCOG-KEEP', 'BACKEND_POLICY')],
    ('server/engine/numeric/backend.py', '<module>', '2'): [(1, 'NONCOG-KEEP', 'BACKEND_POLICY')],
    ('server/engine/numeric/backend.py', '<module>', '20'): [(1, 'NONCOG-KEEP', 'BACKEND_POLICY')],
    ('server/engine/numeric/backend.py', '<module>', '512'): [(1, 'NONCOG-KEEP', 'BACKEND_POLICY')],
    ('server/engine/numeric/backend.py', '_int_from_environment', '0'): [(1, 'NONCOG-KEEP', 'BACKEND_POLICY')],
    ('server/engine/numeric/backend.py', 'best_available', '0'): [(2, 'NONCOG-KEEP', 'BACKEND_POLICY')],
    ('server/engine/numeric/backend.py', 'float32_exactness_problem', '0'): [(1, 'NONCOG-KEEP', 'BACKEND_POLICY')],
    # ---- server/engine/numeric/layout.py
    ('server/engine/numeric/layout.py', '<module>', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/numeric/layout.py', '<module>', '1'): [(1, 'UNIT', 'TAG_CODES')],
    ('server/engine/numeric/layout.py', '<module>', '2'): [(1, 'UNIT', 'TAG_CODES')],
    ('server/engine/numeric/layout.py', '<module>', '3'): [(1, 'UNIT', 'TAG_CODES')],
    ('server/engine/numeric/layout.py', '<module>', '4'): [(1, 'UNIT', 'TAG_CODES')],
    ('server/engine/numeric/layout.py', 'SalienceWeights.from_metadata', '0.0'): [(2, 'UNIT', 'ZERO_DIVISOR_WEIGHTS'), (2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/layout.py', 'SalienceWeights.from_metadata', '1.0'): [(4, 'UNIT', 'ZERO_DIVISOR_WEIGHTS')],
    ('server/engine/numeric/layout.py', 'SlipnetTopology.from_slipnet', '0'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/layout.py', 'ThemeLayout.from_themespace', '0'): [(1, 'UNIT', 'ZERO_KW')],
    ('server/engine/numeric/layout.py', 'ThemeLayout.from_themespace', '1'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/layout.py', 'ThemeState.from_themespace', '0.0'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/layout.py', 'jump_probability', '0.0'): [(1, 'UNIT', 'ZERO_RESULT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/layout.py', 'relative_importances', '0'): [(1, 'UNIT', 'EXACT_ARITH'), (5, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/layout.py', 'relative_importances', '1'): [(1, 'UNIT', 'COUNT_STEP'), (2, 'UNIT', 'EXACT_ARITH')],
    ('server/engine/numeric/layout.py', 'relative_importances', '100'): [(3, 'UNIT', 'PCT_MUL')],
    ('server/engine/numeric/layout.py', 'relative_importances', '100.0'): [(1, 'UNIT', 'EXACT_ARITH'), (1, 'UNIT', 'PCT_MUL')],
    ('server/engine/numeric/layout.py', 'relative_importances', '2'): [(2, 'UNIT', 'EXACT_ARITH')],
    # ---- server/engine/numeric/metal_kernels.py
    ('server/engine/numeric/metal_kernels.py', '<module>', '256'): [(1, 'NONCOG-KEEP', 'METAL_LAYOUT')],
    ('server/engine/numeric/metal_kernels.py', '<module>', '32'): [(2, 'NONCOG-KEEP', 'METAL_LAYOUT')],
    ('server/engine/numeric/metal_kernels.py', '_next_power_of_two', '1'): [(2, 'NONCOG-KEEP', 'METAL_LAYOUT')],
    ('server/engine/numeric/metal_kernels.py', 'grid_for', '1'): [(2, 'NONCOG-KEEP', 'METAL_LAYOUT')],
    ('server/engine/numeric/metal_kernels.py', 'lanes_per_row', '0'): [(1, 'NONCOG-KEEP', 'METAL_LAYOUT')],
    ('server/engine/numeric/metal_kernels.py', 'lanes_per_row', '1'): [(2, 'NONCOG-KEEP', 'METAL_LAYOUT')],
    ('server/engine/numeric/metal_kernels.py', 'max_in_degree', '0'): [(1, 'NONCOG-KEEP', 'METAL_LAYOUT')],
    ('server/engine/numeric/metal_kernels.py', 'max_in_degree', '1'): [(2, 'NONCOG-KEEP', 'METAL_LAYOUT')],
    ('server/engine/numeric/metal_kernels.py', 'threadgroup_for', '1'): [(2, 'NONCOG-KEEP', 'METAL_LAYOUT')],
    # ---- server/engine/numeric/mlx_backend.py
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.average_unhappiness', '0'): [(2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.average_unhappiness', '0.0'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.average_unhappiness', '1e-30'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.combine_object_values', '0'): [(2, 'UNIT', 'NUMERIC_UNIT'), (3, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.combine_object_values', '1'): [(2, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.combine_object_values', '2.0'): [(4, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.combine_object_values', '3.0'): [(4, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.spread_themes', '-1'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.spread_themes', '0'): [(3, 'UNIT', 'NUMERIC_UNIT'), (6, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.spread_themes', '0.0'): [(2, 'UNIT', 'NUMERIC_UNIT'), (5, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.spread_themes', '1'): [(3, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.spread_themes', '1.0'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.spread_themes', '100.0'): [(5, 'UNIT', 'PCT_DIV')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.structure_strengths', '0'): [(1, 'UNIT', 'LEN_ZERO')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.structure_strengths', '0.0'): [(6, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.structure_strengths', '1.0'): [(1, 'UNIT', 'UNIT_COMPLEMENT')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.structure_strengths', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/numeric/mlx_backend.py', 'MlxBackend.temperature', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/mlx_backend.py', 'MlxCpuBackend.is_available', '1.0'): [(1, 'NONCOG-KEEP', 'MLX_PROBE')],
    ('server/engine/numeric/mlx_backend.py', 'MlxCpuBackend.is_available', '2.0'): [(1, 'NONCOG-KEEP', 'MLX_PROBE')],
    ('server/engine/numeric/mlx_backend.py', 'MlxSlipnetSession._update_composed', '0'): [(2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/mlx_backend.py', 'MlxSlipnetSession._update_composed', '0.0'): [(1, 'UNIT', 'NUMERIC_UNIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/mlx_backend.py', 'MlxSlipnetSession._update_composed', '100.0'): [(2, 'UNIT', 'PCT_DIV')],
    ('server/engine/numeric/mlx_backend.py', 'MlxSlipnetSession.jump_candidates', '0.0'): [(1, 'UNIT', 'NUMERIC_UNIT'), (2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/mlx_backend.py', 'MlxSlipnetSession.jump_candidates', '1.0'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/mlx_backend.py', '_gpu_usable', '1.0'): [(1, 'NONCOG-KEEP', 'MLX_PROBE')],
    ('server/engine/numeric/mlx_backend.py', '_gpu_usable', '2.0'): [(1, 'NONCOG-KEEP', 'MLX_PROBE')],
    # ---- server/engine/numeric/numpy_backend.py
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.average_unhappiness', '0'): [(1, 'UNIT', 'ZERO_RESULT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.average_unhappiness', '0.0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.combine_object_values', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.combine_object_values', '2.0'): [(4, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.combine_object_values', '3.0'): [(4, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.spread_themes', '-1'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.spread_themes', '0'): [(2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.spread_themes', '0.0'): [(4, 'UNIT', 'NUMERIC_UNIT'), (5, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.spread_themes', '1.0'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.spread_themes', '100.0'): [(5, 'UNIT', 'PCT_DIV')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.structure_strengths', '0'): [(1, 'UNIT', 'LEN_ZERO'), (2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.structure_strengths', '0.0'): [(2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.structure_strengths', '1.0'): [(1, 'UNIT', 'UNIT_COMPLEMENT')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.structure_strengths', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/numeric/numpy_backend.py', 'NumpyBackend.temperature', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/numpy_backend.py', 'NumpySlipnetSession.__init__', '1.0'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/numpy_backend.py', 'NumpySlipnetSession.jump_candidates', '0.0'): [(1, 'UNIT', 'NUMERIC_UNIT'), (2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/numpy_backend.py', 'NumpySlipnetSession.jump_candidates', '1.0'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/numpy_backend.py', 'NumpySlipnetSession.update', '0.0'): [(4, 'UNIT', 'NUMERIC_UNIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/numpy_backend.py', 'NumpySlipnetSession.update', '100.0'): [(2, 'UNIT', 'PCT_DIV')],
    # ---- server/engine/numeric/python_backend.py
    ('server/engine/numeric/python_backend.py', 'PythonBackend.average_unhappiness', '0'): [(1, 'UNIT', 'ZERO_RESULT'), (2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/python_backend.py', 'PythonBackend.combine_object_values', '2'): [(6, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/python_backend.py', 'PythonBackend.combine_object_values', '3'): [(4, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/python_backend.py', 'PythonBackend.spread_themes', '0'): [(7, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/python_backend.py', 'PythonBackend.spread_themes', '0.0'): [(2, 'UNIT', 'NUMERIC_UNIT'), (2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/python_backend.py', 'PythonBackend.spread_themes', '1.0'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/python_backend.py', 'PythonBackend.spread_themes', '100.0'): [(2, 'UNIT', 'PCT_DIV')],
    ('server/engine/numeric/python_backend.py', 'PythonBackend.structure_strengths', '0'): [(1, 'UNIT', 'NUMERIC_UNIT'), (3, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/python_backend.py', 'PythonBackend.structure_strengths', '0.0'): [(1, 'UNIT', 'NUMERIC_UNIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/python_backend.py', 'PythonBackend.structure_strengths', '1.0'): [(1, 'UNIT', 'UNIT_COMPLEMENT')],
    ('server/engine/numeric/python_backend.py', 'PythonBackend.structure_strengths', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/numeric/python_backend.py', 'PythonBackend.temperature', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/python_backend.py', 'PythonSlipnetSession.__init__', '0.0'): [(2, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/python_backend.py', 'PythonSlipnetSession.__init__', '1.0'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/python_backend.py', 'PythonSlipnetSession._spread', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/python_backend.py', 'PythonSlipnetSession._spread', '0.0'): [(1, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/python_backend.py', 'PythonSlipnetSession._spread', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/numeric/python_backend.py', 'PythonSlipnetSession._spread', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/numeric/python_backend.py', 'PythonSlipnetSession.jump_candidates', '0.0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/python_backend.py', 'PythonSlipnetSession.jump_candidates', '1.0'): [(1, 'UNIT', 'NUMERIC_UNIT')],
    ('server/engine/numeric/python_backend.py', 'PythonSlipnetSession.update', '0.0'): [(1, 'UNIT', 'NUMERIC_UNIT'), (1, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/numeric/python_backend.py', 'PythonSlipnetSession.update', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    # ---- server/engine/parameters.py
    ('server/engine/parameters.py', '<module>', '0'): [(17, 'NONCOG-KEEP', 'PARAM_BOUNDS')],
    ('server/engine/parameters.py', '<module>', '0.0'): [(2, 'NONCOG-KEEP', 'PARAM_BOUNDS')],
    ('server/engine/parameters.py', '<module>', '1'): [(4, 'NONCOG-KEEP', 'PARAM_BOUNDS')],
    ('server/engine/parameters.py', '<module>', '1.0'): [(2, 'NONCOG-KEEP', 'PARAM_BOUNDS')],
    ('server/engine/parameters.py', '<module>', '10'): [(1, 'NONCOG-KEEP', 'PARAM_BOUNDS')],
    ('server/engine/parameters.py', '<module>', '100'): [(7, 'NONCOG-KEEP', 'PARAM_BOUNDS')],
    ('server/engine/parameters.py', '<module>', '1000'): [(5, 'NONCOG-KEEP', 'PARAM_BOUNDS')],
    ('server/engine/parameters.py', '<module>', '10000'): [(3, 'NONCOG-KEEP', 'PARAM_BOUNDS')],
    ('server/engine/parameters.py', '<module>', '100000'): [(1, 'NONCOG-KEEP', 'PARAM_BOUNDS')],
    ('server/engine/parameters.py', '<module>', '200'): [(4, 'NONCOG-KEEP', 'PARAM_BOUNDS')],
    ('server/engine/parameters.py', '<module>', '32'): [(1, 'NONCOG-KEEP', 'PARAM_BOUNDS')],
    ('server/engine/parameters.py', '<module>', '400'): [(1, 'NONCOG-KEEP', 'PARAM_BOUNDS')],
    # ---- server/engine/posting.py
    ('server/engine/posting.py', '<module>', '256'): [(1, 'NONCOG-KEEP', 'FORMULA_SIZE')],
    # ---- server/engine/rational.py
    ('server/engine/rational.py', 'parse_rational', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/rational.py', 'parse_rational', '1'): [(1, 'UNIT', 'RATIONAL_PARSE')],
    ('server/engine/rational.py', 'parse_rational', '2'): [(1, 'UNIT', 'RATIONAL_PARSE')],
    # ---- server/engine/rng.py
    ('server/engine/rng.py', 'RNG.__init__', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/rng.py', 'RNG.perturb', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/rng.py', 'RNG.perturb_bound', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/rng.py', 'RNG.prob', '0.0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/rng.py', 'RNG.prob', '1.0'): [(1, 'UNIT', 'PROB_BOUND')],
    ('server/engine/rng.py', 'RNG.randint', '0'): [(1, 'UNIT', 'ZERO_RESULT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/rng.py', 'RNG.randint', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/rng.py', 'RNG.random', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/rng.py', 'RNG.weighted_pick', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/rng.py', 'RNG.weighted_pick', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    # ---- server/engine/roles.py
    ('server/engine/roles.py', '<module>', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/roles.py', 'Absent', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/roles.py', 'Absent', '0.0'): [(3, 'UNIT', 'ZERO_INIT')],
    ('server/engine/roles.py', 'resolve_roles', '1'): [(1, 'UNIT', 'LEN_ONE')],
    # ---- server/engine/rule_english.py
    ('server/engine/rule_english.py', '_find_next_space', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/rule_english.py', '_plural_object_phrase', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rule_english.py', '_punctuate', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rule_english.py', '_punctuate', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/rule_english.py', '_ref_objects', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rule_english.py', '_swap_phrase', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rule_english.py', 'transcribe_rule_to_english_lines', '0'): [(1, 'UNIT', 'CEIL_DIV')],
    # ---- server/engine/rules.py
    ('server/engine/rules.py', 'ExtrinsicChangeDescription.__init__', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rules.py', 'Rule.__init__', '0.0'): [(4, 'UNIT', 'ZERO_INIT')],
    ('server/engine/rules.py', 'Rule._compute_abstractness', '0.0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/rules.py', 'Rule._compute_abstractness', '100.0'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/rules.py', 'Rule._compute_abstractness.depth', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/rules.py', 'Rule._compute_succinctness', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/rules.py', 'Rule._compute_succinctness', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rules.py', 'Rule._compute_succinctness', '100.0'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/rules.py', 'Rule._compute_uniformity', '1.0'): [(1, 'UNIT', 'PRODUCT_IDENTITY')],
    ('server/engine/rules.py', 'Rule._compute_uniformity', '100.0'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/rules.py', 'Rule.get_degree_of_support', '100'): [(2, 'UNIT', 'PCT_PRODUCT')],
    ('server/engine/rules.py', 'Rule.get_descriptors_to_activate', '3'): [(1, 'UNIT', 'LEN_SHAPE3')],
    ('server/engine/rules.py', 'Rule.get_relative_quality', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/rules.py', 'Rule.get_relative_quality', '100.0'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/rules.py', 'Rule.is_identity_rule', '0'): [(1, 'UNIT', 'LEN_ZERO')],
    ('server/engine/rules.py', 'Rule.is_verbatim_rule', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rules.py', '_average', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/rules.py', '_bounded_random_partition', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/rules.py', '_bounded_random_partition', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/rules.py', '_change_abstractness_uniformity', '1'): [(1, 'UNIT', 'SENTINEL_INDEX')],
    ('server/engine/rules.py', '_check_for_conflicts', '0'): [(1, 'UNIT', 'SORT_KEY')],
    ('server/engine/rules.py', '_check_for_conflicts', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/rules.py', '_check_for_conflicts.visit', '1'): [(2, 'UNIT', 'PLUS_ONE')],
    ('server/engine/rules.py', '_chez_map', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rules.py', '_choose_description_for_rule', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/rules.py', '_choose_description_for_rule', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rules.py', '_count_strposctgy_opposite_slippages', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/rules.py', '_count_strposctgy_opposite_slippages', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/rules.py', '_find_matching_objects', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rules.py', '_find_matching_objects', '3'): [(1, 'UNIT', 'LEN_SHAPE3')],
    ('server/engine/rules.py', '_get_all_swaps', '2'): [(2, 'UNIT', 'LEN_PAIR')],
    ('server/engine/rules.py', '_get_common_schemas', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/rules.py', '_get_extrinsic_transforms', '1'): [(2, 'UNIT', 'LEN_ONE')],
    ('server/engine/rules.py', '_get_extrinsic_transforms', '2'): [(3, 'UNIT', 'LEN_PAIR')],
    ('server/engine/rules.py', '_group_transforms_by_object', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/rules.py', '_homogeneity', '0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    ('server/engine/rules.py', '_homogeneity', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/rules.py', '_instantiate_change_template', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rules.py', '_instantiate_change_template', '3'): [(1, 'UNIT', 'LEN_SHAPE3')],
    ('server/engine/rules.py', '_is_whole_string_object_description', '3'): [(1, 'UNIT', 'LEN_SHAPE3')],
    ('server/engine/rules.py', '_nesting_level', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/rules.py', '_nesting_level', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/rules.py', '_object_description_node', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/rules.py', '_object_description_possible', '0'): [(1, 'UNIT', 'LEN_ZERO')],
    ('server/engine/rules.py', '_pairwise_disjoint', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/rules.py', '_partition_by', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/rules.py', '_remq_duplicates', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/rules.py', '_sort_change_templates.key', '0'): [(1, 'UNIT', 'SORT_KEY')],
    ('server/engine/rules.py', '_sort_change_templates.key', '1'): [(1, 'UNIT', 'SORT_KEY')],
    ('server/engine/rules.py', '_translate_rule_clause', '1'): [(2, 'UNIT', 'LEN_ONE')],
    ('server/engine/rules.py', '_valid_object_description', '3'): [(1, 'UNIT', 'LEN_SHAPE3')],
    ('server/engine/rules.py', '_valid_rule_clause', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rules.py', 'abstract_change_descriptions', '2'): [(1, 'UNIT', 'ARITY_PAIR'), (1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/rules.py', 'apply_rule', '3'): [(1, 'UNIT', 'LEN_SHAPE3')],
    ('server/engine/rules.py', 'chez_sort', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/rules.py', 'chez_sort', '1'): [(2, 'UNIT', 'COUNT_STEP'), (2, 'UNIT', 'SORT_KEY')],
    ('server/engine/rules.py', 'get_tagged_supporting_horizontal_bridges', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/rules.py', 'instantiate_rule_clause_template', '1'): [(2, 'UNIT', 'LEN_ONE')],
    ('server/engine/rules.py', 'remove_redundant_change_descriptions', '-1'): [(3, 'UNIT', 'SENTINEL_INDEX')],
    ('server/engine/rules.py', 'remove_redundant_change_descriptions', '0'): [(3, 'UNIT', 'ZERO_TEST')],
    ('server/engine/rules.py', 'remove_redundant_change_descriptions', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/rules.py', 'rule_quality', '0'): [(1, 'UNIT', 'ZERO_RESULT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/rules.py', 'rule_quality', '100'): [(1, 'UNIT', 'PCT_MUL')],
    # ---- server/engine/runner.py
    ('server/engine/runner.py', 'EngineContext.__init__', '0'): [(2, 'UNIT', 'ZERO_INIT')],
    ('server/engine/runner.py', 'EngineRunner.__init__', '0'): [(2, 'UNIT', 'ZERO_INIT')],
    ('server/engine/runner.py', 'EngineRunner._execute_codelet', '1'): [(2, 'UNIT', 'PLUS_ONE')],
    ('server/engine/runner.py', 'EngineRunner._init_mcat', '0'): [(2, 'UNIT', 'ZERO_INIT')],
    ('server/engine/runner.py', 'EngineRunner._init_mcat', '1'): [(1, 'UNIT', 'ORIGIN_IDENTITY')],
    ('server/engine/runner.py', 'EngineRunner._record_stage', '0.0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    ('server/engine/runner.py', 'EngineRunner._spread_activation_to_themespace', '1'): [(1, 'UNIT', 'ORIGIN_IDENTITY')],
    ('server/engine/runner.py', 'EngineRunner._step_mcat', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/runner.py', 'EngineRunner._step_mcat', '1'): [(1, 'UNIT', 'COUNT_STEP'), (3, 'UNIT', 'PLUS_ONE')],
    ('server/engine/runner.py', 'EngineRunner._update_everything', '0'): [(1, 'UNIT', 'ORIGIN_IDENTITY')],
    ('server/engine/runner.py', 'EngineRunner._update_everything', '1'): [(1, 'UNIT', 'COUNT_STEP'), (1, 'UNIT', 'ORIGIN_IDENTITY')],
    ('server/engine/runner.py', 'EngineRunner._update_everything', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/runner.py', 'EngineRunner.init_mcat', '0'): [(1, 'UNIT', 'SEED_DEFAULT'), (1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/runner.py', 'EngineRunner.run_mcat', '0'): [(1, 'UNIT', 'ORIGIN_IDENTITY'), (1, 'UNIT', 'ZERO_DEFAULT'), (1, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/runner.py', 'EngineRunner.run_mcat', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/runner.py', 'RunResult', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/runner.py', 'StepResult', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    # ---- server/engine/serialization.py
    ('server/engine/serialization.py', '_serialize_rule', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/serialization.py', 'serialize_themespace_state', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/serialization.py', 'theme_display_labels', '1'): [(1, 'UNIT', 'LEN_ONE')],
    # ---- server/engine/slipnet.py
    ('server/engine/slipnet.py', 'Alphabet.unit_length_node', '1'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/slipnet.py', 'Slipnet.__repr__', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/slipnet.py', 'Slipnet.spread_activation', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR'), (1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/slipnet.py', 'SlipnetLink.degree_of_association', '0.0'): [(1, 'UNIT', 'PCT_COMPLEMENT_FLOOR')],
    ('server/engine/slipnet.py', 'SlipnetLink.degree_of_association', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/slipnet.py', 'SlipnetLink.intrinsic_degree_of_association', '0.0'): [(3, 'UNIT', 'PCT_COMPLEMENT_FLOOR')],
    ('server/engine/slipnet.py', 'SlipnetLink.intrinsic_degree_of_association', '100.0'): [(3, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/slipnet.py', 'SlipnetNode.__init__', '0.0'): [(3, 'UNIT', 'ZERO_INIT')],
    ('server/engine/slipnet.py', 'SlipnetNode._related_through', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/slipnet.py', 'SlipnetNode.apply_slippages', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/slipnet.py', 'SlipnetNode.clamp', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/slipnet.py', 'SlipnetNode.compute_rate_of_decay', '1.0'): [(2, 'UNIT', 'EXACT_DECAY'), (2, 'UNIT', 'UNIT_COMPLEMENT')],
    ('server/engine/slipnet.py', 'SlipnetNode.compute_rate_of_decay', '100'): [(2, 'UNIT', 'EXACT_DECAY'), (1, 'UNIT', 'PCT_COMPLEMENT'), (1, 'UNIT', 'PCT_MUL')],
    ('server/engine/slipnet.py', 'SlipnetNode.compute_rate_of_decay', '100.0'): [(2, 'UNIT', 'PCT_DIV'), (2, 'UNIT', 'PCT_MUL')],
    ('server/engine/slipnet.py', 'SlipnetNode.decay', '100'): [(1, 'UNIT', 'EXACT_DECAY')],
    ('server/engine/slipnet.py', 'SlipnetNode.decay', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/slipnet.py', 'SlipnetNode.degree_of_assoc', '0.0'): [(3, 'UNIT', 'PCT_COMPLEMENT_FLOOR')],
    ('server/engine/slipnet.py', 'SlipnetNode.degree_of_assoc', '100.0'): [(3, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/slipnet.py', 'SlipnetNode.get_similar_property_links', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/slipnet.py', 'SlipnetNode.spread_activation_to_neighbors', '0'): [(2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/slipnet.py', 'SlipnetNode.spread_activation_to_neighbors', '100'): [(1, 'UNIT', 'EXACT_DECAY')],
    ('server/engine/slipnet.py', 'SlipnetNode.spread_activation_to_neighbors', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    # ---- server/engine/snag_explanation.py
    ('server/engine/snag_explanation.py', '_punctuate', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/snag_explanation.py', '_punctuate', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/snag_explanation.py', 'explain_failure', '3'): [(1, 'UNIT', 'LEN_SHAPE3')],
    ('server/engine/snag_explanation.py', 'failure_result_of', '1'): [(1, 'UNIT', 'LEN_ONE')],
    # ---- server/engine/splittable_rng.py
    ('server/engine/splittable_rng.py', '<module>', '1'): [(1, 'UNIT', 'PLUS_ONE'), (2, 'UNIT', 'RNG_WORD')],
    ('server/engine/splittable_rng.py', '<module>', '53'): [(1, 'UNIT', 'RNG_WORD')],
    ('server/engine/splittable_rng.py', '<module>', '64'): [(1, 'UNIT', 'RNG_WORD')],
    ('server/engine/splittable_rng.py', 'SplittableRNG.__init__', '0'): [(2, 'UNIT', 'ZERO_DEFAULT'), (1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/splittable_rng.py', 'SplittableRNG._next_words', '1'): [(2, 'UNIT', 'COUNT_STEP')],
    ('server/engine/splittable_rng.py', 'SplittableRNG.perturb', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/splittable_rng.py', 'SplittableRNG.prob', '0.0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/splittable_rng.py', 'SplittableRNG.prob', '1.0'): [(1, 'UNIT', 'PROB_BOUND')],
    ('server/engine/splittable_rng.py', 'SplittableRNG.randint', '0'): [(1, 'UNIT', 'ZERO_RESULT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/splittable_rng.py', 'SplittableRNG.random', '11'): [(1, 'UNIT', 'RNG_WORD')],
    ('server/engine/splittable_rng.py', 'SplittableRNG.weighted_pick', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/splittable_rng.py', 'SplittableRNG.weighted_pick', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    # ---- server/engine/start_check.py
    ('server/engine/start_check.py', '_tiers_read_by', '512'): [(1, 'NONCOG-KEEP', 'CACHE_SIZE')],
    ('server/engine/start_check.py', 'check_run_start', '1'): [(1, 'NONCOG-KEEP', 'CACHE_SIZE')],
    # ---- server/engine/state_graph.py
    ('server/engine/state_graph.py', '<module>', '1'): [(1, 'NONCOG-KEEP', 'FORMAT_VERSION')],
    ('server/engine/state_graph.py', '_restore_run_state', '0.0'): [(6, 'UNIT', 'COUNT_DEFAULT')],
    ('server/engine/state_graph.py', '_restore_run_state', '4'): [(1, 'UNIT', 'ROW_SHAPE')],
    # ---- server/engine/temperature.py
    ('server/engine/temperature.py', 'Temperature.__init__', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/temperature.py', 'Temperature.__init__', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/temperature.py', 'Temperature.clamp', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/engine/temperature.py', 'Temperature.tick_clamp', '0'): [(2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/temperature.py', 'Temperature.tick_clamp', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/temperature.py', 'Temperature.unclamp', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/temperature.py', 'Temperature.update', '1'): [(1, 'UNIT', 'BATCH_OF_ONE')],
    # ---- server/engine/themes.py
    ('server/engine/themes.py', 'Theme.__init__', '0.0'): [(2, 'UNIT', 'ZERO_INIT')],
    ('server/engine/themes.py', 'Theme.boost', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/themes.py', 'Theme.clear_net_input_buffer', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/themes.py', 'ThemeCluster.add_theme', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/themes.py', 'ThemeCluster.get_max_positive_theme_activation', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/themes.py', 'ThemeCluster.pick_positive_theme', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/themes.py', 'ThemeCluster.spread_activation', '0'): [(9, 'UNIT', 'ZERO_TEST')],
    ('server/engine/themes.py', 'ThemeCluster.spread_activation', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/themes.py', 'ThemeCluster.spread_activation', '1'): [(1, 'UNIT', 'ZERO_DIVISOR_GUARD')],
    ('server/engine/themes.py', 'ThemeCluster.spread_activation', '1.0'): [(1, 'UNIT', 'ZERO_DIVISOR_GUARD')],
    ('server/engine/themes.py', 'ThemeCluster.spread_activation', '100.0'): [(2, 'UNIT', 'PCT_DIV')],
    ('server/engine/themes.py', 'Themespace.__repr__', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/themes.py', 'Themespace.__repr__', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/themes.py', 'Themespace.add_theme', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/themes.py', 'Themespace.get_max_positive_theme_activation', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/themes.py', 'Themespace.spread_activation_to_slipnet', '0'): [(2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/themes.py', '_clip_negative', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/themes.py', '_clip_positive', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/themes.py', 'dominant_index', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/themes.py', 'dominant_index', '0.0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/themes.py', 'dominant_index', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/themes.py', 'look_for_auxiliary_slippages', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/themes.py', 'theme_type_weights', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    # ---- server/engine/trace.py
    ('server/engine/trace.py', 'AnswerEvent.get_absolute_quality', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/trace.py', 'AnswerEvent.get_relative_quality', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/trace.py', 'AnswerEvent.is_unjustified', '0'): [(1, 'UNIT', 'LEN_ZERO')],
    ('server/engine/trace.py', 'ClampEvent.__init__', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/trace.py', 'ClampEvent.evaluate_progress', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/trace.py', 'SnagEvent.__init__', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/trace.py', 'SnagEvent.evaluate_progress', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/trace.py', 'TemporalTrace.__init__', '0'): [(5, 'UNIT', 'ZERO_INIT')],
    ('server/engine/trace.py', 'TemporalTrace.add_clamp_event', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/trace.py', 'TemporalTrace.add_snag_event', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/trace.py', 'TemporalTrace.announce_clamp', '1'): [(1, 'UNIT', 'ORIGIN_IDENTITY')],
    ('server/engine/trace.py', 'TemporalTrace.clear', '0'): [(5, 'UNIT', 'ZERO_INIT')],
    ('server/engine/trace.py', 'TemporalTrace.get_new_events_since_last', '-1'): [(1, 'UNIT', 'ORIGIN_IDENTITY')],
    ('server/engine/trace.py', 'TemporalTrace.get_new_events_since_last', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/trace.py', 'TemporalTrace.get_new_events_since_last', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/trace.py', 'TemporalTrace.progress_since_last_clamp', '0.0'): [(2, 'UNIT', 'ZERO_KW'), (3, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/trace.py', 'TemporalTrace.progress_since_last_snag', '0.0'): [(2, 'UNIT', 'ZERO_KW'), (2, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/trace.py', 'TemporalTrace.record_snag', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/trace.py', 'TemporalTrace.undo_last_clamp', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/trace.py', 'TemporalTrace.within_grace_period', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/trace.py', 'TraceEvent.__init__', '0.0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/engine/trace.py', '_associated_concept_pattern', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/trace.py', '_rule_quality', '0.0'): [(2, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/trace.py', '_rule_relative_quality', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/trace.py', 'clamp_theme_pattern', '0'): [(2, 'UNIT', 'ZERO_TEST')],
    ('server/engine/trace.py', 'concept_activation_importance', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/trace.py', 'get_snag_theme_pattern', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/trace.py', 'theme_pattern_entries', '2'): [(4, 'UNIT', 'LEN_PAIR')],
    # ---- server/engine/trace_display.py
    ('server/engine/trace_display.py', '<module>', '1'): [(1, 'NONCOG-KEEP', 'FORMAT_VERSION')],
    ('server/engine/trace_display.py', 'build_event_picture', '100.0'): [(1, 'NONCOG-KEEP', 'SNAG_PICTURE_TEMP')],
    ('server/engine/trace_display.py', 'build_snag_description_picture', '100.0'): [(1, 'NONCOG-KEEP', 'SNAG_PICTURE_TEMP')],
    ('server/engine/trace_display.py', 'build_snag_description_picture', '2'): [(1, 'UNIT', 'LEN_PAIR')],
    ('server/engine/trace_display.py', 'group_concept_pattern', '0.0'): [(1, 'UNIT', 'ORIGIN_IDENTITY')],
    ('server/engine/trace_display.py', 'object_ref', '-1'): [(2, 'UNIT', 'ORIGIN_IDENTITY')],
    ('server/engine/trace_display.py', 'workspace_picture', '1'): [(2, 'UNIT', 'ORIGIN_IDENTITY')],
    # ---- server/engine/verbose.py
    ('server/engine/verbose.py', '<module>', '10'): [(1, 'NONCOG-KEEP', 'VERBOSE_LOG')],
    ('server/engine/verbose.py', '<module>', '46'): [(1, 'NONCOG-KEEP', 'VERBOSE_LOG')],
    ('server/engine/verbose.py', '<module>', '5000'): [(1, 'NONCOG-KEEP', 'VERBOSE_LOG')],
    ('server/engine/verbose.py', '<module>', '58'): [(1, 'NONCOG-KEEP', 'VERBOSE_LOG')],
    ('server/engine/verbose.py', 'VerboseLog.__init__', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/verbose.py', 'VerboseLog.emit', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/verbose.py', 'VerboseLog.since', '0'): [(3, 'NONCOG-KEEP', 'VERBOSE_LOG')],
    ('server/engine/verbose.py', '_float', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/verbose.py', 'ascii_name', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/verbose.py', 'display', '1'): [(1, 'UNIT', 'RATIONAL_DISPLAY')],
    ('server/engine/verbose.py', 'round_to_100ths', '100'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/verbose.py', 'round_to_100ths', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/engine/verbose.py', 'rule_clause_text', '1'): [(1, 'UNIT', 'LEN_ONE')],
    # ---- server/engine/workspace.py
    ('server/engine/workspace.py', 'Workspace.__init__', '0.0'): [(6, 'UNIT', 'ZERO_INIT')],
    ('server/engine/workspace.py', 'Workspace._average_inter_string_unhappiness', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/workspace.py', 'Workspace._average_inter_string_unhappiness', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/workspace.py', 'Workspace._get_youngest_structures_average_age', '0'): [(1, 'UNIT', 'ZERO_FLOOR')],
    ('server/engine/workspace.py', 'Workspace._get_youngest_structures_average_age', '0.0'): [(2, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/workspace.py', 'Workspace._mapping_strength_from_raw', '100.0'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/workspace.py', 'Workspace._object_spans_string', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/workspace.py', 'Workspace._spanning_group_possible', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/workspace.py', 'Workspace.add_bridge', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/workspace.py', 'Workspace.add_rule', '0'): [(2, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/workspace.py', 'Workspace.get_activity', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/engine/workspace.py', 'Workspace.get_activity', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT'), (1, 'UNIT', 'PCT_MUL')],
    ('server/engine/workspace.py', 'Workspace.get_rough_num_of_ungrouped_objects', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/workspace.py', 'Workspace.get_rough_num_of_unmapped_objects', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/workspace.py', 'Workspace.get_rough_num_of_unrelated_objects', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/workspace.py', 'Workspace.has_supported_rule', '0'): [(1, 'UNIT', 'LEN_ZERO')],
    ('server/engine/workspace.py', 'Workspace.update_average_unhappiness_values', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/workspace.py', 'WorkspaceString._get_relevance', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/workspace.py', 'WorkspaceString._get_relevance', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/workspace.py', 'WorkspaceString._get_relevance', '1'): [(1, 'UNIT', 'COUNT_STEP'), (1, 'UNIT', 'LEN_ONE'), (1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/workspace.py', 'WorkspaceString._get_relevance', '100.0'): [(1, 'UNIT', 'PCT_MUL')],
    ('server/engine/workspace.py', 'WorkspaceString.add_bond', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/workspace.py', 'WorkspaceString.add_group', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/workspace.py', 'WorkspaceString.add_group', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/workspace.py', 'WorkspaceString.compute_average_intra_string_unhappiness', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/workspace.py', 'WorkspaceString.left_string_pos', '0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/workspace.py', 'WorkspaceString.right_string_pos', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/workspace.py', 'unrelated', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/workspace.py', 'unrelated', '2'): [(1, 'UNIT', 'ARITY_PAIR')],
    # ---- server/engine/workspace_objects.py
    ('server/engine/workspace_objects.py', 'WorkspaceObject.__init__', '0.0'): [(10, 'UNIT', 'ZERO_INIT')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject._bridge_weakness', '100.0'): [(2, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject._pick_neighbor', '1'): [(1, 'UNIT', 'LEN_ONE')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.add_description', '0'): [(1, 'UNIT', 'INSERT_FRONT')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.exact_raw_importance', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.exact_raw_ratio', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.exact_raw_ratio', '1'): [(2, 'UNIT', 'ZERO_INIT')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.get_all_left_neighbors', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.get_all_left_neighbors', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.get_all_right_neighbors', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.get_all_right_neighbors', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.get_nesting_level', '0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.get_nesting_level', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.get_num_of_spanning_bridges', '0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.get_num_of_spanning_bridges', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.leftmost_in_string', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.rightmost_in_string', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.span', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.spans_whole_string', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/engine/workspace_objects.py', 'WorkspaceObject.update_intra_string_unhappiness', '100.0'): [(3, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/workspace_objects.py', '_average', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    # ---- server/engine/workspace_structures.py
    ('server/engine/workspace_structures.py', 'WorkspaceStructure.__init__', '0'): [(1, 'UNIT', 'CLOCK_ORIGIN')],
    ('server/engine/workspace_structures.py', 'WorkspaceStructure.__init__', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/engine/workspace_structures.py', 'WorkspaceStructure.get_thematic_compatibility', '0.0'): [(1, 'UNIT', 'ZERO_RESULT')],
    ('server/engine/workspace_structures.py', 'WorkspaceStructure.update_strength', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/workspace_structures.py', 'WorkspaceStructure.update_strength', '0.0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/engine/workspace_structures.py', 'WorkspaceStructure.update_strength', '1.0'): [(1, 'UNIT', 'UNIT_COMPLEMENT')],
    ('server/engine/workspace_structures.py', 'WorkspaceStructure.update_strength', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    ('server/engine/workspace_structures.py', 'WorkspaceStructure.weakness', '100.0'): [(1, 'UNIT', 'PCT_COMPLEMENT')],
    # ---- server/parallel/coderack_shards.py
    ('server/parallel/coderack_shards.py', 'LockedCoderack.__init__', '0'): [(2, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/coderack_shards.py', 'LockedCoderack._acquire', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/coderack_shards.py', 'LockedCoderack.clear', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/coderack_shards.py', 'LockedCoderack.is_empty', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    # ---- server/parallel/free_running.py
    ('server/parallel/free_running.py', 'FreeRunResult', '0'): [(5, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/free_running.py', 'FreeRunResult', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/free_running.py', 'FreeRunResult', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/free_running.py', 'FreeRunResult.codelets_per_second', '0.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/free_running.py', 'FreeRunResult.conflict_rate', '0.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/free_running.py', 'FreeRunResult.summary', '4'): [(2, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/free_running.py', 'FreeRunningEngine.__init__', '0'): [(4, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/free_running.py', 'FreeRunningEngine.__init__', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/free_running.py', 'FreeRunningEngine._finish_codelet', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/free_running.py', 'FreeRunningEngine._worker', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (2, 'UNIT', 'ZERO_TEST')],
    ('server/parallel/free_running.py', 'FreeRunningEngine._worker', '1'): [(5, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/free_running.py', 'FreeRunningEngine.run', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (1, 'UNIT', 'ZERO_DEFAULT'), (3, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/free_running.py', 'run_free', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    # ---- server/parallel/placement.py
    ('server/parallel/placement.py', '<module>', '0.14'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/placement.py', '<module>', '2.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/placement.py', '<module>', '200'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/placement.py', '<module>', '32768'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/placement.py', '<module>', '512'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/placement.py', '_env_int', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/placement.py', 'describe', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/placement.py', 'gpu_worthwhile', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/placement.py', 'gpu_worthwhile', '1'): [(7, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/placement.py', 'speculative_backend', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    # ---- server/parallel/qos.py
    ('server/parallel/qos.py', '<module>', '17'): [(1, 'NONCOG-KEEP', 'OS_QOS')],
    ('server/parallel/qos.py', '<module>', '25'): [(1, 'NONCOG-KEEP', 'OS_QOS')],
    ('server/parallel/qos.py', '<module>', '33'): [(1, 'NONCOG-KEEP', 'OS_QOS')],
    ('server/parallel/qos.py', '<module>', '9'): [(1, 'NONCOG-KEEP', 'OS_QOS')],
    ('server/parallel/qos.py', 'CoreTiers', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/qos.py', 'current_thread_qos', '0'): [(3, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/qos.py', 'describe_core_tiers', '0'): [(3, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/qos.py', 'describe_core_tiers', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/qos.py', 'set_thread_qos', '0'): [(2, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    # ---- server/parallel/speculative/clock_rack.py
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack.__init__', '0'): [(4, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack.__init__', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack._compact', '4'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack._compact', '64'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack._enroll', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack._fallback_choice', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack._fallback_choice', '1'): [(3, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack._move_urgencies', '0'): [(2, 'UNIT', 'ZERO_TEST')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack._move_urgencies', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack._rescaled', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (2, 'UNIT', 'ZERO_TEST')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack._reweight', '1'): [(2, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack._smallest_valid', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack._smallest_valid', '1'): [(4, 'UNIT', 'PLUS_ONE')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack._smallest_valid', '2'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack.choose_and_remove', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack.choose_and_remove', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/clock_rack.py', 'ClockCoderack.clear', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    # ---- server/parallel/speculative/compare.py
    ('server/parallel/speculative/compare.py', 'RecordingSink.on_trace_event', '9'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/compare.py', 'RunRecord', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/compare.py', 'RunRecord', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/compare.py', 'run_record', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/parallel/speculative/compare.py', 'run_record', '1'): [(2, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    # ---- server/parallel/speculative/effects.py
    ('server/parallel/speculative/effects.py', '<module>', '1'): [(2, 'UNIT', 'BITMASK'), (1, 'UNIT', 'PLUS_ONE')],
    ('server/parallel/speculative/effects.py', 'mask', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    # ---- server/parallel/speculative/engine.py
    ('server/parallel/speculative/engine.py', '<module>', '7'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'Spec.__init__', '-1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine.__init__', '-1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine.__init__', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (4, 'UNIT', 'ZERO_INIT'), (2, 'UNIT', 'ZERO_TEST')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine.__init__', '0.0'): [(2, 'UNIT', 'ZERO_DEFAULT'), (2, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine.__init__', '1'): [(3, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine.__init__', '1.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine.__init__', '100'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine.__init__', '2'): [(2, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine.__init__', '3000'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine.__init__', '6'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._abandon', '0'): [(2, 'UNIT', 'COUNT_DEFAULT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._abandon', '1'): [(2, 'UNIT', 'PLUS_ONE')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._abandon', '1.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._await_token', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (1, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._await_token', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._await_token', '100'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._bump', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._bump_tele', '0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._bump_tele', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._commit_read_only', '0'): [(3, 'UNIT', 'COUNT_DEFAULT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._commit_read_only', '1'): [(7, 'UNIT', 'PLUS_ONE')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._commit_speculated', '0'): [(2, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (2, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._commit_speculated', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._commit_speculated', '1'): [(6, 'UNIT', 'COUNT_STEP'), (2, 'UNIT', 'PLUS_ONE')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._commit_speculated', '100'): [(2, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._execute_hook', '1'): [(2, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._indices', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._merge_telemetry', '0'): [(5, 'UNIT', 'COUNT_DEFAULT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._probe_compare', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._probe_trap', '2'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._probe_trap', '6'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._quiesce', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._quiesce', '0.05'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._quiesce', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._quiesce', '100'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._refill', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (3, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._refill', '1'): [(2, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (8, 'UNIT', 'COUNT_STEP'), (1, 'UNIT', 'PLUS_ONE')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._refill', '16'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._refill', '2'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._refill', '8'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._run_detect', '-1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._run_detect', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._run_detect', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._run_inline', '1'): [(2, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._run_spec', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._shutdown_workers', '1.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._update_hook', '-1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._update_hook', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._wait_stale', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._wait_stale', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._wait_stale', '100'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._wait_stale', '2.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._worker_main', '0'): [(3, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._worker_main', '0.001'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine._worker_main', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine.run', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/parallel/speculative/engine.py', 'SpeculativeEngine.run', '0.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeExecutor.__init__', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', 'SpeculativeExecutor.run', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/parallel/speculative/engine.py', '_Local', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/speculative/engine.py', '_chaos_hit', '2654435761'): [(1, 'NONCOG-KEEP', 'CHAOS_HASH')],
    ('server/parallel/speculative/engine.py', '_chaos_hit', '65535'): [(1, 'NONCOG-KEEP', 'CHAOS_HASH')],
    ('server/parallel/speculative/engine.py', '_chaos_hit', '65536.0'): [(1, 'NONCOG-KEEP', 'CHAOS_HASH')],
    ('server/parallel/speculative/engine.py', '_install_class_patches', '0'): [(1, 'NONCOG-KEEP', 'PATCH_COUNTER')],
    ('server/parallel/speculative/engine.py', '_install_class_patches', '1'): [(2, 'NONCOG-KEEP', 'PATCH_COUNTER')],
    ('server/parallel/speculative/engine.py', '_new_telemetry', '0'): [(19, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', '_new_telemetry', '0.0'): [(6, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/engine.py', '_remove_class_patches', '0'): [(1, 'NONCOG-KEEP', 'PATCH_COUNTER')],
    ('server/parallel/speculative/engine.py', '_remove_class_patches', '1'): [(3, 'NONCOG-KEEP', 'PATCH_COUNTER')],
    # ---- server/parallel/speculative/fingerprint.py
    ('server/parallel/speculative/fingerprint.py', 'first_differences', '4'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/fingerprint.py', 'first_differences.walk', '2'): [(2, 'UNIT', 'LEN_PAIR')],
    # ---- server/parallel/speculative/reference.py
    ('server/parallel/speculative/reference.py', 'StreamSerial.__init__', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/reference.py', 'StreamSerial.install', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/parallel/speculative/reference.py', 'StreamSerial.install.step_mcat', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/parallel/speculative/reference.py', 'StreamSerial.install.update_everything', '1'): [(1, 'UNIT', 'PLUS_ONE')],
    ('server/parallel/speculative/reference.py', 'StreamSerial.run', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/parallel/speculative/reference.py', 'StreamSerialExecutor.__init__', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/reference.py', 'StreamSerialExecutor.run', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/parallel/speculative/reference.py', 'run_stream_serial', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/parallel/speculative/reference.py', 'run_stream_serial', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    # ---- server/parallel/speculative/streams.py
    ('server/parallel/speculative/streams.py', '<module>', '1'): [(1, 'UNIT', 'PLUS_ONE'), (3, 'UNIT', 'STREAM_TAGS')],
    ('server/parallel/speculative/streams.py', '<module>', '2'): [(1, 'UNIT', 'STREAM_TAGS')],
    ('server/parallel/speculative/streams.py', '<module>', '3'): [(1, 'UNIT', 'STREAM_TAGS')],
    ('server/parallel/speculative/streams.py', '<module>', '4'): [(1, 'UNIT', 'STREAM_TAGS')],
    ('server/parallel/speculative/streams.py', '<module>', '5'): [(1, 'UNIT', 'STREAM_TAGS')],
    ('server/parallel/speculative/streams.py', '<module>', '53'): [(1, 'UNIT', 'STREAM_TAGS')],
    ('server/parallel/speculative/streams.py', '<module>', '64'): [(1, 'UNIT', 'STREAM_TAGS')],
    ('server/parallel/speculative/streams.py', 'Streams.__init__', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/speculative/streams.py', 'Streams.clock_exponential', '11'): [(1, 'UNIT', 'RNG_WORD')],
    # ---- server/parallel/swarm.py
    ('server/parallel/swarm.py', '<module>', '1024'): [(2, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '<module>', '4'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '<module>', '64'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'EpisodeOutcome', '-1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'EpisodeOutcome', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/swarm.py', 'RunOutcome', '-1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'RunOutcome', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/swarm.py', 'RunOutcome', '0.0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/swarm.py', 'Swarm.__init__', '0'): [(3, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/swarm.py', 'Swarm.__init__', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'Swarm._acquire', '0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/parallel/swarm.py', 'Swarm._acquire', '1'): [(2, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/swarm.py', 'Swarm._release', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/swarm.py', 'Swarm._settle', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/swarm.py', 'Swarm._start', '0.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'Swarm._start', '0.05'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'Swarm._start', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'Swarm.configure', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/swarm.py', 'Swarm.imap_unordered', '1'): [(3, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'Swarm.imap_unordered', '4'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'Swarm.map', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'Swarm.submit._done', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '_failure', '0'): [(1, 'UNIT', 'ZERO_KW')],
    ('server/parallel/swarm.py', '_failure', '6'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '_outcome', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '_outcome', '0.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '_warm_batch', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '_warm_batch', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '_warm_batch', '60'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '_watch_owner._loop', '0'): [(2, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '_watch_owner._loop', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '_watch_owner._loop', '1.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '_worker_init', '0'): [(1, 'UNIT', 'ZERO_DEFAULT')],
    ('server/parallel/swarm.py', '_worker_probe', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', '_worker_run', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'default_backend', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'default_swarm_status', '0'): [(3, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'run_episode', '6'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/swarm.py', 'run_one', '0'): [(1, 'UNIT', 'ZERO_KW')],
    ('server/parallel/swarm.py', 'run_one', '0.0'): [(1, 'UNIT', 'ZERO_KW')],
    ('server/parallel/swarm.py', 'run_one', '137'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    # ---- server/parallel/update_cycle.py
    ('server/parallel/update_cycle.py', '<module>', '8'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/update_cycle.py', 'UpdateCycle.__init__', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/update_cycle.py', 'UpdateCycle.__init__', '1'): [(5, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/update_cycle.py', 'UpdateCycle.__init__', '1000'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/update_cycle.py', 'UpdateCycle.__init__', '3000.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/update_cycle.py', 'UpdateCycle._cycle', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/update_cycle.py', 'UpdateCycle._cycle', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/update_cycle.py', 'UpdateCycle._cycle', '100.0'): [(1, 'UNIT', 'PCT_DIV')],
    ('server/parallel/update_cycle.py', 'UpdateCycle._strengths_stream', '0'): [(1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/update_cycle.py', 'UpdateCycle._timed', '0.0'): [(1, 'UNIT', 'COUNT_DEFAULT')],
    ('server/parallel/update_cycle.py', 'UpdateCycle.run', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/update_cycle.py', '_LazyStream.prob', '0.0'): [(1, 'UNIT', 'ZERO_TEST')],
    ('server/parallel/update_cycle.py', '_LazyStream.prob', '1.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/update_cycle.py', '_Team.__init__', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/update_cycle.py', '_Team.__init__', '1'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/update_cycle.py', '_Team.__init__', '400000'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/update_cycle.py', '_Team.__init__', '5e-05'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/update_cycle.py', '_Team._worker', '0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (3, 'UNIT', 'ZERO_INIT'), (1, 'UNIT', 'ZERO_TEST')],
    ('server/parallel/update_cycle.py', '_Team._worker', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/update_cycle.py', '_Team._worker', '63'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/update_cycle.py', '_Team.close', '1'): [(1, 'UNIT', 'COUNT_STEP')],
    ('server/parallel/update_cycle.py', '_Team.close', '2.0'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/update_cycle.py', '_Team.run', '0'): [(2, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (1, 'UNIT', 'ZERO_INIT')],
    ('server/parallel/update_cycle.py', '_Team.run', '1'): [(2, 'NONCOG-KEEP', 'EXECUTOR_PACING'), (1, 'UNIT', 'COUNT_STEP'), (1, 'UNIT', 'PLUS_ONE')],
    ('server/parallel/update_cycle.py', '_Team.run', '200000'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
    ('server/parallel/update_cycle.py', '_label', '8'): [(1, 'NONCOG-KEEP', 'EXECUTOR_PACING')],
}


if __name__ == "__main__":
    _main()
