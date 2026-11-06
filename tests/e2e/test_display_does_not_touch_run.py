"""Showing a past moment must not touch the run that is showing it.

A person can click an event in the Temporal Trace, or an answer or a snag in the Memory view,
and see that moment again.  Petacat does that by saving the live Themespace, deleting it,
switching thematic pressure off and imposing the moment's pattern over it
(``RunService._display_over_themespace``, after Metacat's ``display``, ``trace.ss:405-420``).
All of that is real engine state, so three things are owed:

* **Putting the live state back before the run goes on.**  Metacat restores first, wherever the
  run is about to move or the Themespace is about to be edited: ``go`` (``run.ss:132``),
  ``resume-current-problem`` (``gui.ss:779``) and ``theme-edit-mode-on`` (``gui.ss:857``).
  Here that is a Step, a Run, Clamp Themes and Clamp theme pattern.
* **Not showing anything while the run executes.**  Metacat ignores the click
  (``(if* (not *running?*)``, ``trace-graphics.ss:70``, ``memory-graphics.ss:47``).
* **Forgetting the display when the run is reset or deleted** (``run.ss:190``, ``init-mcat``
  clears ``*display-mode?*``).

Each test compares a run that was disturbed by a display with the same run, from the same
problem, seed and Episodic Memory, that was not.  "The same" is every field of the record
below: the codelet each step ran, the answer, the position of the random number generator (the
draws), the Trace, and the whole engine state, Themespace included.

Requires: a local Postgres — start it with `scripts/dev.sh db`.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from server.api.runs import get_run_service
from server.engine.numeric.backend import use_backend
from server.parallel.speculative.fingerprint import canon, first_differences, state
from server.services import run_service as run_service_module

#: The run that is displayed over: it snags (event 5) and builds themes.
HOST = {"initial": "abc", "modified": "abd", "target": "xyz", "seed": 34}
#: Run first, so Episodic Memory holds an answer to display.
ANSWERED = {"initial": "abc", "modified": "abd", "target": "ijk", "seed": 3}

#: Codelets run before the display, and after it.
BEFORE = 700
AFTER = 400

BACKENDS = ["off", "numpy"]


@pytest.fixture(autouse=True)
async def _no_clear_events_left_behind(db_session):
    """Every comparison clears the Episodic Memory through the API, which records an event.

    Other tests count those events (``test_persistence_modes``), so these leave none.
    """
    from sqlalchemy import delete

    from server.models.run import EpisodicMemoryClear

    yield
    await db_session.execute(delete(EpisodicMemoryClear))
    await db_session.commit()


# --------------------------------------------------------------------------------------
# One arm of a comparison
# --------------------------------------------------------------------------------------


async def _fresh_memory_holding_an_answer(client) -> None:
    """Empty the Episodic Memory, then let ``ANSWERED`` put its answer in it."""
    await client.delete("/api/memory")
    made = (await client.post("/api/runs", json=ANSWERED)).json()["run_id"]
    await client.post(f"/api/runs/{made}/run", json={"max_steps": 3000})


async def _events_with_themes(client, run_id: int) -> list[dict]:
    events = (await client.get(f"/api/runs/{run_id}/trace")).json()["events"]
    shown = []
    for event in events:
        detail = (await client.get(f"/api/runs/{run_id}/trace/{event['event_number']}")).json()
        if detail["theme_pattern"] or (detail["picture"] or {}).get("themes"):
            shown.append(event)
    return shown


async def _show(client, run_id: int, kind: str) -> dict:
    """Display one moment, as the Trace panel or the Memory view does."""
    if kind == "event":
        event = (await _events_with_themes(client, run_id))[-1]
        return (
            await client.post(f"/api/runs/{run_id}/trace/{event['event_number']}/display")
        ).json()
    memory = (await client.get("/api/memory")).json()
    if kind == "answer":
        answer_id = memory["answers"][0]["answer_id"]
        return (
            await client.post(f"/api/memory/answers/{answer_id}/display?run_id={run_id}")
        ).json()
    snag_id = memory["snags"][0]["snag_id"]
    return (await client.post(f"/api/memory/snags/{snag_id}/display?run_id={run_id}")).json()


def _themes_of(client_json: dict) -> list[tuple]:
    return [
        (c["theme_type"], c["dimension"], t["relation"], t["activation"])
        for c in client_json["clusters"]
        for t in c["themes"]
    ]


def _themespace_canon(themespace) -> tuple:
    """The Themespace as state, except for two things a display legitimately leaves.

    ``restore-state`` re-creates every saved theme one by one and each ``add-theme`` conses
    (``themes.ss:103-125``), so the lists the themes are kept in come back in the reverse of
    the order they were saved in.  Metacat does the same, and the engine ports it
    (``Themespace.restore_current_state``), so those two orders are compared as sets here.
    And the ``_saved_*`` attributes are the display's leftovers, not state.
    """
    fields = {k: v for k, v in vars(themespace).items() if not k.startswith("_saved")}

    def key(theme):
        return (theme.theme_type, theme.dimension, str(theme.relation))

    fields["all_themes"] = sorted(fields["all_themes"], key=key)
    clusters = []
    for cluster in themespace.clusters:
        clusters.append((cluster.theme_type, cluster.dimension, cluster.frozen,
                        canon(sorted(cluster.themes, key=key), None, True)))
    fields["clusters"] = clusters
    return canon(fields, None, True)


async def _record(client, run_id: int, steps: list) -> dict:
    """Every field of the run: what it did, and what it is."""
    ctx = get_run_service()._runners[run_id].ctx
    snapshot = state(ctx)
    snapshot["themespace"] = _themespace_canon(ctx.themespace)
    # The memory by what it holds: the run and the identifiers it was filed under differ by arm.
    snapshot["memory"] = tuple(
        canon({k: v for k, v in vars(item).items() if not k.endswith("_id") and k != "picture"},
              None, True)
        for item in [*ctx.memory.answers, *ctx.memory.snags]
    )
    trace = (await client.get(f"/api/runs/{run_id}/trace")).json()["events"]
    return {
        "steps": steps,
        "codelet_count": ctx.codelet_count,
        "answer": ctx.workspace.answer_string.text if ctx.workspace.answer_string else None,
        "draws": ctx.rng.get_state(),
        "trace": [(e["event_number"], e["event_type"], e["codelet_count"]) for e in trace],
        "themes": _themes_of((await client.get(f"/api/runs/{run_id}/themespace")).json()),
        "pressure": list(ctx.themespace.active_theme_types),
        "state": snapshot,
    }


async def _drive(client, run_id: int, how: str, steps: list) -> None:
    if how == "step":
        for _ in range(2):
            got = (await client.post(f"/api/runs/{run_id}/step", json={"n": AFTER // 2})).json()
            steps.extend((r["codelet_count"], r["codelet_type"], r["answer_found"]) for r in got)
    elif how == "run":
        info = (await client.post(f"/api/runs/{run_id}/run", json={"max_steps": 3000})).json()
        steps.append((info["codelet_count"], info["status"], info["answer"]))
    elif how in ("clamp_pattern", "clamp_themes"):
        # Clamp Themes acts on the live Themespace: the one chosen here is the live one.
        # The last cluster with a theme: a type the event's own pattern need not have named, so
        # the other types are left as they are and show whether they were put back.
        live = (await client.get(f"/api/runs/{run_id}/themespace")).json()
        cluster = [c for c in live["clusters"] if c["themes"]][-1]
        theme = cluster["themes"][0]
        if how == "clamp_pattern":
            body = {"patterns": [{"type": cluster["theme_type"], "themes": [
                {"dimension": cluster["dimension"], "relation": theme["relation"],
                 "activation": 100}]}]}
            url = "clamp-theme-pattern"
        else:
            body = {"themes": [{"type": cluster["theme_type"], "dimension": cluster["dimension"],
                                "relation": theme["relation"], "activation": 100}]}
            url = "clamp-themes"
        reply = await client.post(f"/api/runs/{run_id}/{url}", json=body)
        assert reply.status_code == 200, reply.text
        steps.append(reply.json()["clamped_themes"])
        # The dialog opened on the live state, so no past moment is over it any more.
        assert not get_run_service()._runners[run_id].ctx.themespace.displaying_past_state
        await _drive(client, run_id, "step", steps)
    else:  # pragma: no cover
        raise AssertionError(how)


async def _arm(
    client,
    *,
    kind: str | None,
    how: str,
    workers: int = 1,
    self_watching: bool = True,
    clamp_first: bool = False,
) -> dict:
    """One run: ``BEFORE`` codelets, a display of ``kind`` (or none), then driven ``how``."""
    await _fresh_memory_holding_an_answer(client)
    request = dict(HOST, workers=workers)
    run_id = (await client.post("/api/runs", json=request)).json()["run_id"]
    if not self_watching:
        await client.put(f"/api/runs/{run_id}/self-watching", json={"enabled": False})
    steps: list = []
    got = (await client.post(f"/api/runs/{run_id}/step", json={"n": BEFORE})).json()
    steps.extend((r["codelet_count"], r["codelet_type"], r["answer_found"]) for r in got)
    if clamp_first:
        # A clamp switches thematic pressure on, which a display switches off.
        live = (await client.get(f"/api/runs/{run_id}/themespace")).json()
        cluster = next(c for c in live["clusters"] if c["themes"])
        await client.post(
            f"/api/runs/{run_id}/clamp-theme-pattern",
            json={"patterns": [{"type": cluster["theme_type"], "themes": [
                {"dimension": cluster["dimension"],
                 "relation": cluster["themes"][0]["relation"], "activation": 100}]}]},
        )
        assert get_run_service()._runners[run_id].ctx.themespace.active_theme_types, (
            "the clamp switched no thematic pressure on, so the display has none to switch off"
        )
    if kind is not None:
        before = _themes_of((await client.get(f"/api/runs/{run_id}/themespace")).json())
        shown = await _show(client, run_id, kind)
        assert shown["displaying"] is not None
        after = _themes_of((await client.get(f"/api/runs/{run_id}/themespace")).json())
        assert get_run_service()._runners[run_id].ctx.themespace.displaying_past_state
        assert after != before or not before, "the display changed nothing, so proves nothing"
    await _drive(client, run_id, how, steps)
    return await _record(client, run_id, steps)


def _assert_same(disturbed: dict, undisturbed: dict) -> None:
    for field in ("steps", "codelet_count", "answer", "draws", "trace", "themes", "pressure"):
        assert disturbed[field] == undisturbed[field], f"{field} differs"
    for component, was in undisturbed["state"].items():
        assert disturbed["state"][component] == was, f"{component}: " + "; ".join(
            first_differences(was, disturbed["state"][component], limit=4)
        )


# --------------------------------------------------------------------------------------
# A display, then the run goes on
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("how", ["step", "run"])
@pytest.mark.parametrize("kind", ["event", "answer", "snag"])
async def test_a_display_then_the_run_goes_on_is_the_run_undisturbed(
    app_client, kind, how, backend
):
    with use_backend(backend, 0 if backend != "off" else None):
        undisturbed = await _arm(app_client, kind=None, how=how)
        disturbed = await _arm(app_client, kind=kind, how=how)
    _assert_same(disturbed, undisturbed)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_display_under_thematic_pressure_then_a_step_is_the_run_undisturbed(
    app_client, backend
):
    with use_backend(backend, 0 if backend != "off" else None):
        undisturbed = await _arm(app_client, kind=None, how="step", clamp_first=True)
        disturbed = await _arm(app_client, kind="event", how="step", clamp_first=True)
    _assert_same(disturbed, undisturbed)


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["step", "run"])
async def test_a_display_with_self_watching_off_then_the_run_goes_on_is_undisturbed(
    app_client, how
):
    undisturbed = await _arm(app_client, kind=None, how=how, self_watching=False)
    disturbed = await _arm(app_client, kind="answer", how=how, self_watching=False)
    _assert_same(disturbed, undisturbed)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_display_then_a_parallel_run_is_the_parallel_run_undisturbed(
    app_client, backend
):
    with use_backend(backend, 0 if backend != "off" else None):
        undisturbed = await _arm(app_client, kind=None, how="run", workers=2)
        disturbed = await _arm(app_client, kind="event", how="run", workers=2)
    _assert_same(disturbed, undisturbed)


# --------------------------------------------------------------------------------------
# Clamp Themes while a moment is on show acts on the live state
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["clamp_pattern", "clamp_themes"])
@pytest.mark.parametrize("kind", ["event", "answer"])
async def test_clamp_themes_while_a_moment_is_on_show_acts_on_the_live_state(
    app_client, kind, how
):
    undisturbed = await _arm(app_client, kind=None, how=how)
    disturbed = await _arm(app_client, kind=kind, how=how)
    _assert_same(disturbed, undisturbed)


# --------------------------------------------------------------------------------------
# A display while the run executes
# --------------------------------------------------------------------------------------


class _Hooked:
    """``asyncio`` as ``run_service`` sees it, with ``sleep`` and ``to_thread`` hooked."""

    def __init__(self, *, sleep=None, to_thread=None):
        self._sleep, self._to_thread = sleep, to_thread

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def sleep(self, *args, **kwargs):
        if self._sleep is not None:
            await self._sleep()
        return await asyncio.sleep(*args, **kwargs)

    async def to_thread(self, fn, *args, **kwargs):
        if self._to_thread is not None:
            return await self._to_thread(fn, *args, **kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)


async def _during_the_run(client, monkeypatch, *, workers: int, overlap: bool) -> dict:
    """Run to the end with an answer displayed twice while it executes; return the record.

    A request is served only while the event loop is free, which for the serial loop is the
    ``asyncio.sleep(0)`` it yields at every update cycle, and for the parallel one the whole
    of the worker threads' time.  The display is made at exactly that point, so the moment
    is chosen by the code and not by a clock.
    """
    await _fresh_memory_holding_an_answer(client)
    run_id = (await client.post("/api/runs", json=dict(HOST, workers=workers))).json()["run_id"]
    steps: list = []
    got = (await client.post(f"/api/runs/{run_id}/step", json={"n": BEFORE})).json()
    steps.extend((r["codelet_count"], r["codelet_type"], r["answer_found"]) for r in got)
    service = get_run_service()
    ctx = service._runners[run_id].ctx
    answer_id = (await client.get("/api/memory")).json()["answers"][0]["answer_id"]
    seen: list = []

    def click_twice() -> None:
        """Two clicks on the same answer, as a person who clicks again would make."""
        for _ in range(2):
            reply = service.impose_answer(run_id, answer_id)
            seen.append((
                service._runners[run_id].status,
                ctx.codelet_count,
                reply["displaying"],
                ctx.themespace.displaying_past_state,
            ))

    async def at_a_yield() -> None:
        if not seen:
            click_twice()

    async def around_the_threads(fn, *args, **kwargs):
        if not overlap:
            click_twice()  # the gap: running, and no worker has started
            return await real_to_thread(fn, *args, **kwargs)
        work = asyncio.ensure_future(real_to_thread(fn, *args, **kwargs))
        for _ in range(100000):  # while the workers have run something
            if ctx.codelet_count > BEFORE + 50 or work.done():
                break
            await asyncio.sleep(0.001)
        click_twice()
        return await work

    real_to_thread = asyncio.to_thread

    async def to_thread(fn, *args, **kwargs):
        """Only the speculative engine's ``run`` is hooked; anyone else's thread is theirs."""
        if getattr(fn, "__name__", "") == "run" and "Speculative" in type(
            getattr(fn, "__self__", None)
        ).__name__:
            return await around_the_threads(fn, *args, **kwargs)
        return await real_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(run_service_module, "asyncio", _Hooked(sleep=at_a_yield))
    monkeypatch.setattr(asyncio, "to_thread", to_thread)
    info = (await client.post(f"/api/runs/{run_id}/run", json={"max_steps": 3000})).json()
    monkeypatch.undo()
    steps.append((info["codelet_count"], info["status"], info["answer"]))
    record = await _record(client, run_id, steps)
    record["seen"] = seen
    return record


@pytest.mark.asyncio
async def test_a_display_while_the_serial_run_yields_leaves_the_run_undisturbed(
    app_client, monkeypatch
):
    undisturbed = await _arm(app_client, kind=None, how="run")
    disturbed = await _during_the_run(app_client, monkeypatch, workers=1, overlap=False)
    assert disturbed["seen"], "the run never yielded, so no display met it"
    for status, _count, displaying, imposed in disturbed["seen"]:
        assert status == "running"
        assert displaying is not None, "the picture is still served"
        assert imposed is False, "the Themespace was imposed over while the run used it"
    assert get_run_service()._displaying.get(max(get_run_service()._runners)) is None
    _assert_same(disturbed, undisturbed)


@pytest.mark.asyncio
@pytest.mark.parametrize("overlap", [False, True])
async def test_a_display_while_the_parallel_run_executes_leaves_the_run_undisturbed(
    app_client, monkeypatch, overlap
):
    undisturbed = await _arm(app_client, kind=None, how="run", workers=2)
    disturbed = await _during_the_run(app_client, monkeypatch, workers=2, overlap=overlap)
    assert len(disturbed["seen"]) == 2
    for status, count, displaying, imposed in disturbed["seen"]:
        assert status == "running"
        assert displaying is not None
        assert imposed is False
        if overlap:
            assert BEFORE + 50 < count < disturbed["codelet_count"], "the workers were not mid-run"
    _assert_same(disturbed, undisturbed)


# --------------------------------------------------------------------------------------
# What the service remembers about a display
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_reset_or_a_delete_forgets_what_was_on_show(app_client):
    await _fresh_memory_holding_an_answer(app_client)
    service = get_run_service()
    run_id = (await app_client.post("/api/runs", json=HOST)).json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/step", json={"n": BEFORE})
    await _show(app_client, run_id, "answer")
    assert run_id in service._displaying

    await app_client.post(f"/api/runs/{run_id}/reset")
    assert run_id not in service._displaying
    assert not service._runners[run_id].ctx.themespace.displaying_past_state

    await _show(app_client, run_id, "answer")
    assert run_id in service._displaying
    await app_client.delete(f"/api/runs/{run_id}")
    assert run_id not in service._displaying


@pytest.mark.asyncio
async def test_a_step_ends_the_display_it_found(app_client):
    await _fresh_memory_holding_an_answer(app_client)
    service = get_run_service()
    run_id = (await app_client.post("/api/runs", json=HOST)).json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/step", json={"n": BEFORE})
    await _show(app_client, run_id, "answer")
    await app_client.post(f"/api/runs/{run_id}/step", json={"n": 1})
    assert run_id not in service._displaying
    assert not service._runners[run_id].ctx.themespace.displaying_past_state
    # The same click again is a new display, not the second click that restores.
    again = await _show(app_client, run_id, "answer")
    assert again["displaying"] is not None
