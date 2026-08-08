# Manual smoke tests — Step 0 and the parallelism fix

Six tests. Every command below was run against the live stack before this file was
written, and the numbers quoted are what it actually produced.

```
GUI   http://localhost:59595
API   http://localhost:8100     (docs: http://localhost:8100/docs)
```

## Before you start — two things that will otherwise confuse you

**1. Episodic memory persists between runs, and it changes results.** The Training
Session is process-global and deliberately outlives a run: `answer_present` makes the
engine refuse to rediscover an answer it already holds. So the *same problem at the same
seed* gives a different answer each time until you clear it. Test 2 is about exactly
that. Every other test starts with:

```bash
curl -s -X DELETE http://localhost:8100/api/memory
```

Skip that and you will think the engine is non-deterministic. It isn't.

**2. The codelet counts below are the same on every backend.** The app runs on `mlx` /
float32 — check with `curl -s localhost:8100/api/system/numeric` — and at the shipped
59-node Slipnet `python`, `numpy`, `mlx` and `mlx-cpu` produce *byte-identical
trajectories*, verified by hashing the full activation vector after every update cycle.
The Metal kernel uses `rint` and `precise::divide` deliberately, so the decay plateaus
land where float64's do.

An earlier draft of this file blamed a 1138-vs-777 difference between the application and
the test suite on float32. That was wrong. The cause was that
`load_metadata_from_db` selected the Slipnet nodes with no `ORDER BY` and the table had
no ordinal column, so the application iterated the nodes in Postgres *heap* order — which
drifts with every re-seed — while the library iterated them in `slipnet.ss` order. Node
order sets both the float accumulation order of the activation spread and which node each
`rng.prob` draw is spent on. Fixed; the two now agree, and the figures below are that
agreed number.

Still: **judge the property, not the magic number** — that a run is repeatable, and that a
config change moves it.

---

## 1 · A single run is deterministic and repeatable

*The baseline everything else is measured against.*

```bash
API=http://localhost:8100
for i in 1 2 3; do
  curl -s -X DELETE $API/api/memory > /dev/null
  RID=$(curl -s -X POST $API/api/runs -H 'Content-Type: application/json' \
        -d '{"initial":"abc","modified":"abd","target":"mrrjjj","seed":42}' \
        | python3 -c "import json,sys;print(json.load(sys.stdin)['run_id'])")
  curl -s -X POST $API/api/runs/$RID/run -H 'Content-Type: application/json' \
       -d '{"max_steps":20000}' \
    | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['status'],d['codelet_count'])"
done
```

**Expect** the identical line three times:

```
answer_found 777
answer_found 777
answer_found 777
```

**Why it matters.** Before this work the application read *zero* posting rules from the
database, so the engine the GUI ran was not the engine the tests measured. That the run
is now stable and matches the seed-data engine is the whole point of Step 0.

**In the GUI:** New Run → `abc` / `abd` / `mrrjjj`, seed 42 → Run. Clear the Training
Session between attempts or you are running test 2.

---

## 2 · A Training Session forces novelty, then exhausts

*Episodic behaviour: memory carried forward, four runs, same problem, same seed.*

```bash
API=http://localhost:8100
curl -s -X DELETE $API/api/memory > /dev/null
for i in 1 2 3 4; do
  RID=$(curl -s -X POST $API/api/runs -H 'Content-Type: application/json' \
        -d '{"initial":"abc","modified":"abd","target":"mrrjjj","seed":42}' \
        | python3 -c "import json,sys;print(json.load(sys.stdin)['run_id'])")
  curl -s -X POST $API/api/runs/$RID/run -H 'Content-Type: application/json' \
       -d '{"max_steps":20000}' \
    | python3 -c "import json,sys;d=json.load(sys.stdin);print('run $i:',d['status'],d['codelet_count'])"
done
curl -s $API/api/memory | python3 -c "
import json,sys
for a in json.load(sys.stdin)['answers']:
    print(' ', a['problem'][-1], '| quality', a['quality'], '|', a['top_rule_description'])"
```

**Expect** each run to work harder than the last, then give up:

```
run 1: answer_found 777
run 2: answer_found 2377
run 3: answer_found 8666
run 4: halted       20000

  mrrkkk  | quality 84 | change LetterCtgy by succ
  mrrjjj  | quality 54 | Unknown transformation
  mrrjjjj | quality 86 | change LetterCtgy by succ
```

**What you are watching.** Run 1 finds the obvious answer. Run 2 may not repeat it, so it
pays 3× the codelets. Run 3 pays 11× the first run's, for a poor answer
(quality 54). Run 4 has nothing new left and halts at the cap. The exact answers may vary
with load; the *shape* — rising cost, falling quality, eventual exhaustion — is the test.

**In the GUI:** run the same problem four times without clearing the Training Session,
and watch the memory panel fill.

---

## 3 · An engine parameter edit changes the run

*The core Step 0 property: a value you change in the database is a value the engine reads.*

```bash
API=http://localhost:8100
run() { curl -s -X DELETE $API/api/memory > /dev/null
  RID=$(curl -s -X POST $API/api/runs -H 'Content-Type: application/json' \
        -d '{"initial":"abc","modified":"abd","target":"mrrjjj","seed":42}' \
        | python3 -c "import json,sys;print(json.load(sys.stdin)['run_id'])")
  curl -s -X POST $API/api/runs/$RID/run -H 'Content-Type: application/json' \
       -d '{"max_steps":20000}' \
    | python3 -c "import json,sys;d=json.load(sys.stdin);print(' ',d['status'],d['codelet_count'])"; }

echo shipped:; run
curl -s -X PUT $API/api/admin/params/expiration_period \
     -H 'Content-Type: application/json' -d '{"value":"50"}' > /dev/null
echo 'expiration_period = 50:'; run
curl -s -X PUT $API/api/admin/params/expiration_period \
     -H 'Content-Type: application/json' -d '{"value":"500"}' > /dev/null
echo restored:; run
```

**Expect** the middle run to differ and the third to return to the first:

```
shipped:               answer_found 777
expiration_period=50:  answer_found 345
restored:              answer_found 777
```

**Why this parameter.** `%expiration-period%` scales the workspace-activity measure the
progress-watcher reads. It shipped in the database, was displayed in the admin panel, was
covered by the config hash — and the engine read a Python literal instead. Editing it did
nothing. Now it does.

**Worth trying too:** `max_activation` (80 makes every node's ceiling 80),
`workspace_activation`, `max_clamp_period`, `min_shard_capacity`. All were unread or
half-read before this work.

**In the GUI:** Configuration → Engine Parameters → double-click the value.

---

## 4 · A posting-rule edit changes the run

*The table that was empty in production until this work.*

```bash
API=http://localhost:8100
# Point the top-down category bond scout at a node that never activates.
ID=$(curl -s $API/api/admin/posting-rules | python3 -c "
import json,sys;print([r['id'] for r in json.load(sys.stdin)
                       if r['codelet_type']=='top-down-bond-scout:category'][0])")
BODY=$(curl -s $API/api/admin/posting-rules | python3 -c "
import json,sys
r=[r for r in json.load(sys.stdin) if r['id']==$ID][0]; r.pop('id')
r['triggering_slipnodes']=['plato-nonexistent']; print(json.dumps(r))")
curl -s -X PUT $API/api/admin/posting-rules/$ID -H 'Content-Type: application/json' -d "$BODY" > /dev/null
```

Run the problem (the `run()` helper from test 3), then restore:

```bash
RESTORE=$(echo "$BODY" | python3 -c "
import json,sys; r=json.load(sys.stdin)
r['triggering_slipnodes']=['plato-predecessor','plato-successor','plato-sameness']
print(json.dumps(r))")
curl -s -X PUT $API/api/admin/posting-rules/$ID -H 'Content-Type: application/json' -d "$RESTORE" > /dev/null
```

**Expect:**

```
rule silenced: answer_found 700
restored:      answer_found 777
```

**Why it matters.** `server/main.py` seeded twelve JSON files and never inserted a single
`PostingRule` row, so the application held **zero** posting rules and posted no top-down
codelets at all — while the admin API happily listed, exported and imported the empty
table. This test would previously have produced no change whatsoever.

---

## 5 · Codelet patterns come from the database, and a bad name is refused

*Happy path and error path in one. Covers the table that did not exist, and the duplicate
that was removed.*

```bash
API=http://localhost:8100
RID=$(curl -s -X POST $API/api/runs -H 'Content-Type: application/json' \
      -d '{"initial":"abc","modified":"abd","target":"mrrjjj","seed":42}' \
      | python3 -c "import json,sys;print(json.load(sys.stdin)['run_id'])")

curl -s $API/api/runs/$RID/codelet-patterns | python3 -c "
import json,sys
for p in json.load(sys.stdin)['patterns']:
    print(f\"  {p['name']:<10} {len(p['entries'])} entries  {p['entries'][0]}\")"

curl -s -o /dev/null -w '  valid   HTTP %{http_code}\n' -X POST \
  $API/api/runs/$RID/clamp-codelet-pattern -H 'Content-Type: application/json' -d '{"pattern":"rule"}'
curl -s -w '\n' -X POST \
  $API/api/runs/$RID/clamp-codelet-pattern -H 'Content-Type: application/json' -d '{"pattern":"nonsense"}'
```

**Expect** five patterns, urgencies as **named tiers** rather than numbers, and a 400 that
names the alternatives:

```
  top_down   11 entries  {'codelet_type': 'top-down-bond-scout:direction', 'urgency_level': 'very_high'}
  bottom_up  16 entries  {'codelet_type': 'bottom-up-bond-scout',          'urgency_level': 'very_high'}
  rule        3 entries  {'codelet_type': 'rule-scout',                    'urgency_level': 'very_high'}
  bridge      4 entries  {'codelet_type': 'bottom-up-bridge-scout',        'urgency_level': 'very_high'}
  group       3 entries  {'codelet_type': 'group-scout:whole-string',      'urgency_level': 'very_high'}

  valid   HTTP 200
  {"detail":"Unknown codelet pattern 'nonsense'. Available: top_down, bottom_up, rule, bridge, group"}
```

**Why it matters.** These had no table at all — the engine loaded an empty dict from the
database, so a clamp fired and pinned nothing. They also existed twice: five hardcoded in
Python for the control API and nine in the seed data for the engine. There is now one
definition, and `very_high` is a *named* tier resolved through `urgency_levels`, not the
number 77 written down in a second place.

---

## 6 · Free-running spreads work across all four workers

*The parallelism fix.*

```bash
API=http://localhost:8100
curl -s -X DELETE $API/api/memory > /dev/null
RID=$(curl -s -X POST $API/api/runs -H 'Content-Type: application/json' \
      -d '{"initial":"eeqee","modified":"qeeq","target":"xxixx","seed":42,"mode":"fast","workers":4}' \
      | python3 -c "import json,sys;print(json.load(sys.stdin)['run_id'])")
curl -s -X POST $API/api/runs/$RID/run -H 'Content-Type: application/json' -d '{"max_steps":4000}' > /dev/null
curl -s $API/api/runs/$RID/telemetry | python3 -c "
import json,sys;d=json.load(sys.stdin)
print(' workers  ', d['workers'])
print(' per_worker', d['per_worker'])
print(' codelets  ', d['codelets'], 'in', d['seconds'], 's')
print(' max share  %.0f%%' % (100*max(d['per_worker'])/d['codelets']))"
```

**Expect** roughly even quarters:

```
 workers   4
 per_worker [982, 1011, 1057, 951]
 codelets   4001 in 2.49 s
 max share  26%
```

**The failure it guards.** Before the fix this printed `[4001, 0, 0, 0]` about 40% of the
time. The pool was built *while the first worker was already running*, and a worker
executing interpreted codelet bodies never releases the GIL — so the main thread could
lose that handoff and threads 2-4 were never constructed at all. `per_worker` is
preallocated, so the telemetry reported three idle workers that had never existed.

**Run it several times.** Anything above ~40% max share, and certainly any zero, is a
regression. Ideal is 25%.

---

# One known defect you will hit if you poke at the admin API

**`PUT /api/admin/params/{name}` does not validate the value against its declared type,
and a bad value takes the whole configuration down.** I did this by accident while
writing these tests:

```bash
curl -s -X PUT http://localhost:8100/api/admin/params/max_coderack_size \
     -H 'Content-Type: application/json' -d '{"value":"not-a-number"}'
# → HTTP 200 {"name":"max_coderack_size","value":"not-a-number","value_type":"int"}
```

It is accepted. From then on **every** metadata load throws
`invalid literal for int() with base 10: 'not-a-number'`, so creating any run returns
HTTP 400 and the application is unusable until the row is repaired:

```bash
curl -s -X PUT http://localhost:8100/api/admin/params/max_coderack_size \
     -H 'Content-Type: application/json' -d '{"value":"100"}'
```

This is the same shape as the defects Step 0 removed — a value accepted, stored and
displayed without being checked against what reads it — one level up, in the endpoint
rather than the engine. `_parse_param` (`server/services/metadata_service.py`) is where
the type is known; the write path never consults it. Not fixed, and not in the six tests
above because it is a defect rather than behaviour to confirm.

---

# Reset to a clean slate

```bash
curl -s -X DELETE http://localhost:8100/api/memory        # clear the Training Session
```

If you have edited configuration and want the shipped values back, the surest way is to
let startup re-seed: the derived metadata tables are rebuilt whenever the seed-data
fingerprint changes, and the fingerprint now covers the seeder's own source. Failing
that, `POST /api/admin/import` with a previously exported payload, or edit the row back.

To check nothing is left over:

```bash
psql "postgresql://petacat:dev@localhost:5432/petacat" -tAc "
select name||' = '||value from engine_params
 where name in ('max_coderack_size','expiration_period','min_shard_capacity',
                'max_activation','workspace_activation') order by name;"
```

Shipped values: `expiration_period = 500`, `max_activation = 100`,
`max_coderack_size = 100`, `min_shard_capacity = 25`, `workspace_activation = 100`.

# Stopping

```bash
scripts/dev.sh stop      # API and client; Postgres is left running
```
