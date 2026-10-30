"""The stream-serial reference (SSR): the faithful loop with keyed streams and a clock rack.

``EngineRunner.run_mcat`` / ``_step_mcat`` are the semantics.  The SSR is those very
methods, unchanged, with two things swapped underneath them:

* the choice -- ``ctx.coderack`` becomes a :class:`ClockCoderack` that adopts the rack
  ``init_mcat`` built (``choose_and_remove`` is the only method that differs, and the
  engine's step calls it through ``ctx.coderack``);
* the randomness -- every unit of work runs with a stream bound through
  ``ctx.use_codelet_rng`` (the seam the engine already offers), keyed as documented in
  :mod:`server.parallel.speculative.streams`:

  ===================  ====================================================
  unit                 bound by
  ===================  ====================================================
  one whole step       ``runner.step_mcat``  -> LOOP stream of step ``n``
  a codelet body       ``runner._execute_codelet`` -> BODY stream of its id
  an update cycle      ``runner._update_everything`` -> UPDATE stream of ``u``
  ===================  ====================================================

  The three bindings nest (an update cycle that runs inside a codelet, from an answer
  report or a snag, binds its own stream and then hands the codelet's back), which is
  why the hooks are installed on the *innermost* engine methods and not on the loop.

Nothing in the loop is re-implemented: the initial unclamp time, the rack-empty repost
and re-clamp, collecting an answer or a give-up, the cycle every ``update_cycle_length``
codelets, ``finish()``, the sink calls and the trace emission are all the engine's own
statements, run by the engine.  That is the guarantee that the SSR and the faithful loop
differ only in the choice and the generator -- the two things the design accepts as
"equal in law".

The hooks are *instance* attributes, so removing them (:meth:`StreamSerial.uninstall`)
leaves the class, and every other runner, exactly as it was.
"""

from __future__ import annotations

from typing import Any, Callable

from server.parallel.speculative.clock_rack import ClockCoderack
from server.parallel.speculative.streams import Streams

#: The names of the instance attributes the SSR shadows on the runner.
_HOOKED = ("step_mcat", "_execute_codelet", "_update_everything")


def run_seed(runner: Any) -> int:
    """The seed the run was created with (the Mersenne Twister's)."""
    rng = runner.ctx._rng
    seed = getattr(rng, "seed", None)
    if seed is None:
        raise ValueError("the run's generator has no seed; pass seed= explicitly")
    return int(seed)


class StreamSerial:
    """Installs the SSR's rack and stream bindings on one prepared runner.

    ``update`` chooses the update cycle: ``"engine"`` runs ``runner._update_everything``
    itself with the update stream bound; ``"stream"`` runs WP5's
    :class:`~server.parallel.update_cycle.UpdateCycle` under its bit-identical-across-
    thread-counts ``stream`` policy with ``update_threads`` threads.  The SSR and the
    speculative engine must be given the same ``update`` policy to be comparable.
    """

    def __init__(
        self,
        runner: Any,
        seed: int | None = None,
        *,
        update: str = "engine",
        update_threads: int = 1,
    ) -> None:
        if runner.ctx is None:
            raise ValueError("the runner has not been initialised (call init_mcat first)")
        if update not in ("engine", "stream"):
            raise ValueError(f"update must be 'engine' or 'stream', got {update!r}")
        self.runner = runner
        self.seed = run_seed(runner) if seed is None else int(seed)
        self.streams = Streams(self.seed)
        self.update = update
        self.update_threads = update_threads
        self._cycle: Any = None
        self._installed = False
        self._originals: dict[str, Callable[..., Any]] = {}

    # -- installation ------------------------------------------------------

    def install(self) -> "StreamSerial":
        if self._installed:
            return self
        runner = self.runner
        ctx = runner.ctx
        streams = self.streams

        if not isinstance(ctx.coderack, ClockCoderack):
            ctx.coderack = ClockCoderack.adopt(
                ctx.coderack,
                streams,
                rng_source=lambda: ctx.rng,
                step_source=lambda: ctx.codelet_count + 1,
            )

        if self.update == "stream":
            from server.parallel.update_cycle import UpdateCycle

            self._cycle = UpdateCycle(
                runner, policy="stream", threads=self.update_threads
            )

        orig_step = runner.step_mcat
        orig_execute = runner._execute_codelet
        orig_update = runner._update_everything
        self._originals = {
            "step_mcat": orig_step,
            "_execute_codelet": orig_execute,
            "_update_everything": orig_update,
        }
        cycle = self._cycle

        def step_mcat() -> Any:
            with ctx.use_codelet_rng(streams.loop(ctx.codelet_count + 1)):
                return orig_step()

        def execute_codelet(codelet: Any) -> None:
            with ctx.use_codelet_rng(streams.body(codelet.id)):
                orig_execute(codelet)

        def update_everything(c: Any) -> None:
            with ctx.use_codelet_rng(streams.update(runner._update_cycle + 1)):
                if cycle is None:
                    orig_update(c)
                else:
                    cycle.run()

        runner.step_mcat = step_mcat
        runner._execute_codelet = execute_codelet
        runner._update_everything = update_everything
        self._installed = True
        return self

    def uninstall(self) -> None:
        """Remove the hooks (the clock rack stays: it is a valid rack)."""
        if not self._installed:
            return
        for name in _HOOKED:
            runner_dict = self.runner.__dict__
            runner_dict.pop(name, None)
        if self._cycle is not None:
            self._cycle.close()
            self._cycle = None
        self._installed = False

    def close(self) -> None:
        self.uninstall()

    # -- running -----------------------------------------------------------

    def run(self, max_steps: int = 0) -> Any:
        """``run_mcat`` with the SSR installed.  Returns the engine's ``RunResult``."""
        self.install()
        return self.runner.run_mcat(max_steps)


def run_stream_serial(
    runner: Any,
    max_steps: int = 0,
    *,
    seed: int | None = None,
    update: str = "engine",
    update_threads: int = 1,
) -> Any:
    """Run a prepared runner to completion under the stream-serial reference."""
    ssr = StreamSerial(runner, seed, update=update, update_threads=update_threads)
    try:
        return ssr.run(max_steps)
    finally:
        ssr.close()


class StreamSerialExecutor:
    """The registry's ``"stream"`` executor: ``run(max_steps)`` over the SSR."""

    def __init__(self, runner: Any, *, update: str = "engine", update_threads: int = 1,
                 **_ignored: Any) -> None:
        self.runner = runner
        self._ssr = StreamSerial(runner, update=update, update_threads=update_threads)

    def run(self, max_steps: int = 0) -> Any:
        try:
            return self._ssr.run(max_steps)
        finally:
            self._ssr.close()
