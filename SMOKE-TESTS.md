# Petacat manual smoke test

A 16-step happy-path check of Metacat Mode, Training Mode and the stage-1 configuration work (C0 to EN3). Every step and every result below was run for real on 2026-10-31 at commit `a7a025b` (macOS, Apple M5 Max, `mlx` backend).

Run the commands from the repo root. Step 2 keeps its terminal busy, so use a second terminal for the other commands. Stop any running `scripts/dev.sh` (ctrl-c) before step 1, because that step deletes the development database.

1. **Delete the development database:** `dropdb --if-exists --force petacat`. Expect no output (or a "does not exist, skipping" notice if it was already gone).

2. **Start the stack:** `scripts/dev.sh`. Expect `postgres ready on localhost:5432 (petacat, petacat_test)`, then `GUI http://localhost:59595`, then, in the server's output, `INFO:     Configuration: empty database, loaded the Metacat Standard Configuration`, and uvicorn's `Application startup complete.` The terminal stays busy, which is right.

3. **Check the Metacat Standard Configuration was loaded into the empty database:** `psql postgresql://petacat:dev@localhost:5432/petacat -c "select origin, load_state from configuration_state"`. Expect one row, `metacat_standard | ready`.

4. **Edit a setting in the Admin view:** open http://localhost:59595, menu, **Configuration (Metacat Mode)**, tab **Engine Params**, double-click the value of `expiration_period` (shipped value 500), type `80`, press Enter. Expect the row to show `80`. The tab bar's right-hand end offers only **Export** and **Import**; there is no "Export to Seed Data".

5. **Restart the server:** `touch server/main.py`. The dev server notices and reloads. Expect `WatchFiles detected changes in 'server/main.py'. Reloading...` and then `Application startup complete.` in the step 2 terminal.

6. **Pick the problem:** menu, **Run Dashboard (Metacat Mode)**, **Demo Problem** drop-down, choose `fig5.11: abc -> abd; xyz -> ?`. Expect Initial `abc`, Modified `abd`, Target `xyz`, Seed `2006188493`.

7. **Run it:** click **Run to Answer**. Expect the top **Run History** row to read `#1 abc->abd; xyz -> xyd`, `answer found`, `1475` under Cdlts. With the shipped 500 it would be 923, so 1475 shows your step 4 edit survived the step 5 restart and changed the run.

8. **Run the same problem again:** click **Run to Answer**. Expect a new row `#2 abc->abd; xyz -> abd`, `answer found`, `2749`. A different answer and more work, because run #2 inherits the Episodic Memory that run #1 left (it already holds `xyd`).

9. **Clear Episodic Memory:** click **Clear Episodic Memory** (the Episodic Memory group of the run controls). Expect the green message `Episodic Memory cleared — the next run starts with none.`

10. **Run it a third time:** click **Run to Answer**. Expect `#3 abc->abd; xyz -> xyd`, `1475`: exactly run #1 again, because the memory was empty.

11. **Review a run:** click `review` on the `#3` row of Run History. Expect the Review (Metacat Mode) view with run #3 selected. Its **Start → end** summary shows `codelets 1475` and `memory answers 0 → 1`, and the episodic-run timeline beside it shows a marker for the clear between #3 and #2.

12. **Run the one-problem Swarm:** back on the Run Dashboard, in the **Swarm** group (Seeds 200, First seed 1) click **Run 200 seeds**. Expect `200 runs in about 3 s on <your cores> cores`, no `with errors`, and a top row of `xyd`, Count `81`, `40.5` %. The seeds are fixed, so the 81 is exact.

13. **Run a Training (Training Mode):** `.venv/bin/python scripts/training_client.py --url http://localhost:8100 --name smoke --initial 3 --add 1 --total 3 --seeds 2 --max-codelets 3000`. Expect three `finished` lines, each with `errors 0`, then `done: 3 problems, 6 runs in ~1s ... errors 0`.

14. **Create a posting rule on the fresh database:** `curl -s -X POST localhost:8100/api/admin/posting-rules -H 'Content-Type: application/json' -d '{"codelet_type":"smoke-test-scout","direction":"bottom_up","urgency_when_posted":7,"posting_formula":"temperature / 100","count_formula":"fixed","count_values":{"fixed":1},"condition":"always"}'`. Expect JSON starting `{"id":18,"rule_key":"smoke-test-scout","codelet_type":"smoke-test-scout"` (not `Internal Server Error`).

15. **Check the Admin export carries the new data:** `curl -s localhost:8100/api/admin/export | python3 -c "import json,sys;d=json.load(sys.stdin);print({k:len(d[k]) for k in ('slipnet_node_roles','codelet_type_roles','theme_relations')})"`. Expect `{'slipnet_node_roles': 37, 'codelet_type_roles': 5, 'theme_relations': 5}`.

16. **Run the golden baseline gate and the role checks:** `.venv/bin/pytest tests/lockstep/test_golden_baseline.py tests/seed_unit/test_role_identity.py tests/seed_unit/test_roles.py -q -m "not slow"`. Expect `119 passed, 1 deselected` in about 4 seconds. This recomputes four golden runs and checks the committed baseline files and all role checks. Drop `-m "not slow"` for the full byte-for-byte recompute of every baseline run: `120 passed` in about 3 minutes.

If a step differs, stop there: each depends on the ones before it. Start again from step 1 (ctrl-c the step 2 terminal first).
