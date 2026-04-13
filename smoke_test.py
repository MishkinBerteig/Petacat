#!/usr/bin/env python3
"""Smoke test — run the Petacat engine end-to-end on abc->abd; xyz->?

Usage:
    cd Petacat && python3 smoke_test.py

No database, no Docker, no FastAPI required.
"""

import logging
import os
import sys
import time

# ── Setup path so `from server.engine...` works ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner, STATUS_ANSWER_FOUND

SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_data")
MAX_STEPS = 3000
SEED = 42

# Configure logging — show INFO for engine events
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
# Engine logger at INFO to see codelet execution
engine_logger = logging.getLogger("petacat.engine")
engine_logger.setLevel(logging.WARNING)  # Keep quiet; we print summaries below


def main() -> None:
    print("=" * 70)
    print("Petacat Smoke Test: abc -> abd; xyz -> ?")
    print("=" * 70)

    # 1. Load metadata from seed JSON
    print("\n[1] Loading metadata from seed_data/ ...")
    meta = MetadataProvider.from_seed_data(SEED_DIR)
    print(f"    Loaded {len(meta.slipnet_node_specs)} slipnet nodes, "
          f"{len(meta.slipnet_link_specs)} links, "
          f"{len(meta.codelet_specs)} codelet types")

    # 2. Create runner and initialize
    print("\n[2] Creating EngineRunner and initializing problem ...")
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=SEED)
    ctx = runner.ctx
    assert ctx is not None, "init_mcat should set ctx"

    print(f"    Workspace strings: "
          f"{ctx.workspace.initial_string.text} -> "
          f"{ctx.workspace.modified_string.text}; "
          f"{ctx.workspace.target_string.text} -> ?")
    print(f"    Initial coderack size: {ctx.coderack.total_count}")
    print(f"    Initial temperature: {ctx.temperature.value:.0f}")

    # 3. Run step-by-step
    print(f"\n[3] Running up to {MAX_STEPS} steps ...")
    t0 = time.time()
    answer_found = False
    last_milestone = 0
    rules_found_count = 0

    for step in range(1, MAX_STEPS + 1):
        try:
            result = runner.step_mcat()
        except Exception as exc:
            print(f"\n*** CRASH at step {step}: {type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()
            break

        # Track rules
        if ctx.workspace.top_rules or ctx.workspace.bottom_rules:
            new_count = len(ctx.workspace.top_rules) + len(ctx.workspace.bottom_rules)
            if new_count > rules_found_count:
                rules_found_count = new_count
                top_texts = [str(r) for r in ctx.workspace.top_rules]
                bot_texts = [str(r) for r in ctx.workspace.bottom_rules]
                print(f"    Step {step}: Rules update — "
                      f"top={top_texts}, bottom={bot_texts}")

        # Check answer
        if result.answer_found:
            elapsed = time.time() - t0
            answer_found = True
            print(f"\n    >>> ANSWER FOUND at step {step} ({elapsed:.1f}s): "
                  f"'{result.answer}'")
            break

        # Progress milestones
        if step % 500 == 0:
            elapsed = time.time() - t0
            ws = ctx.workspace
            total_bonds = sum(len(s.bonds) for s in ws.all_strings)
            total_groups = sum(len(s.groups) for s in ws.all_strings)
            print(f"    Step {step}: T={ctx.temperature.value:.0f}, "
                  f"coderack={ctx.coderack.total_count}, "
                  f"bonds={total_bonds}, "
                  f"groups={total_groups}, "
                  f"bridges(t/b/v)={len(ws.top_bridges)}/"
                  f"{len(ws.bottom_bridges)}/"
                  f"{len(ws.vertical_bridges)}, "
                  f"rules(t/b)={len(ws.top_rules)}/"
                  f"{len(ws.bottom_rules)}, "
                  f"elapsed={elapsed:.1f}s")

    elapsed = time.time() - t0

    # 4. Summary
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"  Steps executed:  {ctx.codelet_count}")
    print(f"  Time elapsed:    {elapsed:.1f}s")
    print(f"  Final temperature: {ctx.temperature.value:.0f}")
    print(f"  Status:          {runner.status}")
    print(f"  Answer found:    {answer_found}")
    if runner._answers:
        print(f"  Answers:         {runner._answers}")

    # Workspace state
    ws = ctx.workspace
    total_bonds = sum(len(s.bonds) for s in ws.all_strings)
    total_groups = sum(len(s.groups) for s in ws.all_strings)
    print(f"\n  Workspace:")
    print(f"    Bonds:         {total_bonds}")
    print(f"    Groups:        {total_groups}")
    print(f"    Top bridges:   {len(ws.top_bridges)}")
    print(f"    Bottom bridges:{len(ws.bottom_bridges)}")
    print(f"    Vert bridges:  {len(ws.vertical_bridges)}")
    print(f"    Top rules:     {len(ws.top_rules)}")
    print(f"    Bottom rules:  {len(ws.bottom_rules)}")

    # Slipnet activation
    active_nodes = [
        (n.name, n.activation)
        for n in ctx.slipnet.nodes.values()
        if n.activation > 50
    ]
    if active_nodes:
        active_nodes.sort(key=lambda x: -x[1])
        print(f"\n  Active slipnet nodes (>50):")
        for name, act in active_nodes[:15]:
            print(f"    {name}: {act:.0f}")

    # Commentary
    commentary = ctx.commentary.render(eliza_mode=False)
    if commentary.strip():
        print(f"\n  Commentary:")
        for line in commentary.strip().split("\n")[:20]:
            print(f"    {line}")

    # Trace summary
    if ctx.trace.events:
        print(f"\n  Trace events: {len(ctx.trace.events)} total")
        type_counts: dict[str, int] = {}
        for ev in ctx.trace.events:
            t = ev.event_type
            type_counts[t] = type_counts.get(t, 0) + 1
        for et, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"    {et}: {cnt}")

    print("\n" + "=" * 70)
    if answer_found:
        print("PASS: Engine produced an answer.")
    else:
        print("NOTE: No answer found within step limit (this may be normal).")
    print("=" * 70)


def run_problem(initial: str, modified: str, target: str, seed: int, max_steps: int = 3000) -> bool:
    """Run a single problem and return True if an answer was found."""
    print(f"\n--- Problem: {initial} -> {modified}; {target} -> ? (seed={seed}) ---")

    meta = MetadataProvider.from_seed_data(SEED_DIR)
    runner = EngineRunner(meta)
    runner.init_mcat(initial, modified, target, seed=seed)
    ctx = runner.ctx

    t0 = time.time()
    for step in range(1, max_steps + 1):
        try:
            result = runner.step_mcat()
        except Exception as exc:
            print(f"  CRASH at step {step}: {type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()
            return False

        if result.answer_found:
            elapsed = time.time() - t0
            print(f"  ANSWER '{result.answer}' at step {step} ({elapsed:.1f}s), "
                  f"T={ctx.temperature.value:.0f}")
            return True

    elapsed = time.time() - t0
    ws = ctx.workspace
    total_bonds = sum(len(s.bonds) for s in ws.all_strings)
    print(f"  No answer in {max_steps} steps ({elapsed:.1f}s), "
          f"T={ctx.temperature.value:.0f}, bonds={total_bonds}, "
          f"rules(t/b)={len(ws.top_rules)}/{len(ws.bottom_rules)}")
    return False


if __name__ == "__main__":
    main()

    # Additional quick tests with different seeds/problems
    print("\n\n" + "=" * 70)
    print("ADDITIONAL PROBLEM TESTS")
    print("=" * 70)
    results = []
    tests = [
        ("abc", "abd", "xyz", 100),
        ("abc", "abd", "xyz", 999),
        ("abc", "abd", "ijk", 42),
        ("abc", "abd", "pqr", 77),
    ]
    for initial, modified, target, seed in tests:
        found = run_problem(initial, modified, target, seed, max_steps=2000)
        results.append((f"{initial}->{modified}; {target}->? s={seed}", found))

    print("\n\nSummary of additional tests:")
    for desc, found in results:
        status = "ANSWER" if found else "no answer"
        print(f"  {desc}: {status}")
