# Context-response benchmark

Five series of context-response analogy problems, run through real Training Mode Sessions, and kept with their results as a
reference for later iterations and versions of Petacat's Training Mode. The benchmark records where v2.0 stands today; it is
not a target and nothing is tuned to it.

## Why

The user expects Petacat to "utterly fail because we don't have any kind of tokenizer right now", and wants the record of it,
and said "Don't try too many problems in this increment." A Training Mode problem is a **context-response analogy problem**:
the 1st position is the **context**, the 3rd the **input**, and the 4th, which Petacat constructs, the **response**. A
multi-turn run is a chat: the next turn's context is the previous context, second string and input joined with single spaces,
its second string is the previous response, and its input is the teacher's next input.

The second reason is the Coderack. Metacat's `max_coderack_size` is 100, and the user's view (2026-11-16) is that "the Coderack
is probably going to have to change to be more flexible in size". Every turn's `evidence.coderack` counts the pressure on it
(full posts, overflowing batches and evicted codelets), so the benchmark gathers that evidence. It changes nothing about the
Coderack's size.

## The series

`series.json` holds them (the file `scripts/session_client.py --teacher` reads). Each is one multi-turn problem, with the
inputs of turns 2 and 3 and then the teacher's end, labelled `series over`:

| Series | Turn 1 | Turn 2 input | Turn 3 input |
|---|---|---|---|
| 1 | `one:two::1:?` | `2` | `3` |
| 2 | `bad:good::less:?` | `more` | `old` |
| 3 | `1:2::3:?` | `1234` | `12345` |
| 4 | `up:down::in:?` | `on` | `yes` |
| 5 | `cat:cats::dog:?` | `pig` | `cow` |

Each series runs in its own fresh Training Mode Session: the v2.0 Base, seeds 1 to 50, the serial child, backend `off`, and the
session's default maximum number of codelets (the script does not state `max_codelets`; `SUMMARY.md` reports the value the
session took). The sessions are independent, so the script runs the five at the same time, each in its own process.

## How to run it

From the repository root, with a Postgres database that the script may create and fill (it holds one session per series):

    .venv/bin/python scripts/context_response_benchmark.py \
        --database-url postgresql+asyncpg://USER:PASS@localhost:5432/NAME \
        --out measurements/context-response-benchmark/NEW-FOLDER [--series 1,3]

The output folder must not exist: the script never overwrites. `--seeds` and `--max-codelets` exist for tests and trials; the
reference run states neither. A person can also run the series over HTTP, with `scripts/session_client.py --teacher
measurements/context-response-benchmark/series.json --out FILE`, in the order the running server gives (see the note below).

## What it measures

`SUMMARY.md`, per series and per turn: how many of the 50 runs reached the turn and how many answered; the turn's statuses
and its responses with their counts (top five, and how many distinct); codelets (median and mean); how many runs ended with
symbols still unperceived; the rules the answers used (top three); the Coderack's pressure (full posts, overflowing batches and
evicted, median per turn, and evicted per codelet); the end reasons of the series' runs; and what the session learned over the
series (nodes and links added, links by type, from the session's configuration against the v2.0 Base). Its head names the
commit, the Base, the settings and the run time. `v2.0-increment-4/series-N.json` holds every run's whole conversation (each
turn's four positions, who supplied them, status, codelets, answers, proposals and evidence).

The Coderack counters: **full posts** are codelets posted while the rack holds `max_coderack_size`; **overflowing batches** are
deferred batches that take the rack past it; **evicted** are codelets removed to make room (a batch as large as the whole rack
flushes it: one overflowing batch, and every codelet the rack held is evicted).

## Reproducibility

The teacher is `set_teacher`, in process, and the script uses the serial child, so the order of turns, and therefore every
answer, codelet count and Coderack count, is the same each time the same code runs. Only the times differ. A teacher answering
over HTTP while other runs go on finishes turns in another order (a turn's Episodic Memory is the one its run was dispatched
under), so a run over HTTP is not expected to reproduce these conversations exactly. A later iteration that changes the engine,
the v2.0 Base or the series is compared with this folder by running the script again into a new folder.
