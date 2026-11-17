# Context-response benchmark: summary

- Commit: 1e45d78c7a6a726e85f9257912d1ff52e42a6156
- Base: the v2.0 Base (`configuration_base` `training-v2`), one fresh Training Mode Session per series
- Settings: {"backend": "off", "configuration_base": "training-v2", "max_codelets": 20000, "parameters": null, "seed_start": 1, "seeds_per_problem": 50}; the serial child; teacher `set_teacher` in process
- Run time: 73.6 s (the series ran at the same time, each in its own process)

## Series 1: `one:two::1:?`, inputs ['2', '3']

Session settings taken: `{"backend": "off", "configuration_base": "training-v2", "max_codelets": 20000, "parameters": null, "seed_start": 1, "seeds_per_problem": 50}`; 50 runs in 10.9 s.

Run end reasons: `no-answer` x50

| Turn | Reached | Answered | Statuses | Top responses (distinct) | Codelets median / mean | Unperceived at end | Top rules (top rule // bottom rule) | Full posts (median) | Overflowing batches (median) | Evicted (median) | Evicted per codelet |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 50 | 0 | `gave_up` x50 | none (0 distinct) | 4445.5 / 4580.7 | 0 of 50 | none | 16 | 231.5 | 4059 | 0.908 |
| 2 | 0 | 0 | | | | | | | | | |
| 3 | 0 | 0 | | | | | | | | | |

Learned over the series (the session's configuration against the v2.0 Base): 1 nodes added, 3 links added, links by type {"adjacent": 3}, 0 existing links changed.

## Series 2: `bad:good::less:?`, inputs ['more', 'old']

Session settings taken: `{"backend": "off", "configuration_base": "training-v2", "max_codelets": 20000, "parameters": null, "seed_start": 1, "seeds_per_problem": 50}`; 50 runs in 72.4 s.

Run end reasons: `no-answer` x50

| Turn | Reached | Answered | Statuses | Top responses (distinct) | Codelets median / mean | Unperceived at end | Top rules (top rule // bottom rule) | Full posts (median) | Overflowing batches (median) | Evicted (median) | Evicted per codelet |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 50 | 49 | `answer_found` x49; `halted` x1 | `gooss` x43; `gess` x4; `good` x2 (3 distinct) | 3016.5 / 3618.1 | 0 of 50 | `Change letter-category of leftmost letter to `g'; Change letter-category of middle letter to `o'; Increase length of middle letter by one // Change letter-category of leftmost letter to `g'; Change letter-category of middle letter to `o'; Increase length of middle letter by one` x8; `Change leftmost letter to a `g' group; Change letter-category of middle letter to `o'; Increase length of middle letter by one // Change leftmost group to a `g' group; Change letter-category of middle group to `o'; Increase length of middle group by one` x4; `Change letter-category of leftmost letter to `g'; Change letter-category of middle letter to `o'; Increase length of middle letter by one // Change letter-category of leftmost letter to `g'; Change letter-category of middle group to `o'; Increase length of middle group by one` x4 | 17.5 | 193.5 | 3998 | 1.320 |
| 2 | 49 | 1 | `gave_up` x48; `answer_found` x1 | `gooss` x1 (1 distinct) | 10386 / 10632.3 | 0 of 49 | `Change string to "gooss" // Change string to "gooss"` x1 | 13 | 628 | 12419 | 1.198 |
| 3 | 1 | 0 | `gave_up` x1 | none (0 distinct) | 16745 / 16745.0 | 0 of 1 | none | 14 | 1037 | 21055 | 1.257 |

Learned over the series (the session's configuration against the v2.0 Base): 1 nodes added, 15 links added, links by type {"adjacent": 13, "category": 1, "instance": 1}, 0 existing links changed.

## Series 3: `1:2::3:?`, inputs ['1234', '12345']

Session settings taken: `{"backend": "off", "configuration_base": "training-v2", "max_codelets": 20000, "parameters": null, "seed_start": 1, "seeds_per_problem": 50}`; 50 runs in 9.9 s.

Run end reasons: `no-answer` x50

| Turn | Reached | Answered | Statuses | Top responses (distinct) | Codelets median / mean | Unperceived at end | Top rules (top rule // bottom rule) | Full posts (median) | Overflowing batches (median) | Evicted (median) | Evicted per codelet |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 50 | 50 | `answer_found` x50 | `4` x48; `2` x1; `3` x1 (3 distinct) | 46.5 / 110.2 | 0 of 50 | `Change letter-category of single letter to adjacent // Change letter-category of single letter to adjacent` x48; `Change string to "2" // Change string to "2"` x1; `Change letter-category of letter `1' to `2' // Change letter-category of letter `1' to `2'` x1 | 0 | 0 | 0 | 0.000 |
| 2 | 50 | 0 | `gave_up` x50 | none (0 distinct) | 4237.5 / 4390.0 | 0 of 50 | none | 3.5 | 207 | 2592.5 | 0.616 |
| 3 | 0 | 0 | | | | | | | | | |

Learned over the series (the session's configuration against the v2.0 Base): 5 nodes added, 17 links added, links by type {"adjacent": 7, "category": 5, "instance": 5}, 0 existing links changed.

## Series 4: `up:down::in:?`, inputs ['on', 'yes']

Session settings taken: `{"backend": "off", "configuration_base": "training-v2", "max_codelets": 20000, "parameters": null, "seed_start": 1, "seeds_per_problem": 50}`; 50 runs in 7.4 s.

Run end reasons: `no-answer` x50

| Turn | Reached | Answered | Statuses | Top responses (distinct) | Codelets median / mean | Unperceived at end | Top rules (top rule // bottom rule) | Full posts (median) | Overflowing batches (median) | Evicted (median) | Evicted per codelet |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 50 | 0 | `gave_up` x50 | none (0 distinct) | 3247 / 3417.8 | 0 of 50 | none | 0 | 143.5 | 2295 | 0.668 |
| 2 | 0 | 0 | | | | | | | | | |
| 3 | 0 | 0 | | | | | | | | | |

Learned over the series (the session's configuration against the v2.0 Base): 0 nodes added, 5 links added, links by type {"adjacent": 5}, 0 existing links changed.

## Series 5: `cat:cats::dog:?`, inputs ['pig', 'cow']

Session settings taken: `{"backend": "off", "configuration_base": "training-v2", "max_codelets": 20000, "parameters": null, "seed_start": 1, "seeds_per_problem": 50}`; 50 runs in 12.4 s.

Run end reasons: `no-answer` x50

| Turn | Reached | Answered | Statuses | Top responses (distinct) | Codelets median / mean | Unperceived at end | Top rules (top rule // bottom rule) | Full posts (median) | Overflowing batches (median) | Evicted (median) | Evicted per codelet |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 50 | 6 | `gave_up` x44; `answer_found` x6 | `cats` x6 (1 distinct) | 4148 / 4182.3 | 0 of 50 | `Change string to "cats" // Change string to "cats"` x6 | 6 | 203 | 3137.5 | 0.822 |
| 2 | 6 | 0 | `gave_up` x6 | none (0 distinct) | 7300.5 / 6984.7 | 0 of 6 | none | 19 | 396 | 9186.5 | 1.276 |
| 3 | 0 | 0 | | | | | | | | | |

Learned over the series (the session's configuration against the v2.0 Base): 1 nodes added, 12 links added, links by type {"adjacent": 10, "category": 1, "instance": 1}, 0 existing links changed.

