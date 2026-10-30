"""Codelet DSL Interpreter — uses Python as the expression language.

Instead of inventing a custom DSL, codelet behavior is expressed as Python
source code stored in the `execute_body` column of `codelet_type_defs`.
The source is compiled once at startup with `compile()` and executed at
runtime via `exec()` in a sandboxed namespace populated with built-in
helper functions.

This means:
- Adding a new codelet type = inserting a row with Python code
- Changing codelet behavior = editing the `execute_body` column
- Zero Python code changes needed for either

The namespace provides all the primitives a codelet needs: object selection,
structure proposals, stochastic decisions, slipnet access, etc.
"""

from __future__ import annotations

import math
import types
from functools import partial
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from server.engine.runner import EngineContext


#: The builtins that exist only for Verbose mode's narration.  They are bound into a
#: codelet's namespace only when Verbose mode is on, so a run with it off pays nothing
#: for them -- not even the closure each ``_bind_ctx`` would build per codelet.  A body
#: calls them behind ``if verbose:``, which is false in exactly the runs where they
#: are absent.
VERBOSE_ONLY = frozenset({
    "say", "vprint", "ascii_name", "generic_name", "print_name", "round_to_100ths", "exact",
})


class CodeletFizzle(Exception):
    """Raised when a codelet decides not to proceed (normal flow control)."""
    pass


class CompiledCodelet:
    """A compiled codelet program (Python code object)."""

    def __init__(self, name: str, code: types.CodeType | None = None, source: str = "") -> None:
        self.name = name
        self.code = code
        self.source = source

    @property
    def is_empty(self) -> bool:
        return self.code is None

    def __repr__(self) -> str:
        status = "compiled" if self.code else "empty"
        return f"CompiledCodelet({self.name}, {status})"


class CodeletInterpreter:
    """Executes Python codelet programs against an EngineContext.

    Programs are compiled once at startup. At runtime, each execution
    gets a fresh namespace populated with built-in functions and the
    current EngineContext.
    """

    #: Class-level default, so a subclass that skips ``__init__`` still works.
    _bound_cache: tuple[Any, dict, dict, dict] | None = None

    def __init__(self, builtins: dict[str, Callable] | None = None) -> None:
        # Held by reference, not copied: a caller (the tests) may swap an entry afterwards.
        self._builtins = builtins if builtins is not None else {}
        self._bound_cache: tuple[Any, dict, dict, dict] | None = None

    def _bound_for(self, ctx: Any) -> tuple[dict[str, Callable], dict[str, Callable]]:
        """The builtins bound to *ctx*: ``(always, verbose_only)``.

        Built once per ctx and reused for every codelet that ctx runs.  The cache is a
        single immutable tuple, replaced whole, so a thread that finds it stale rebuilds
        and publishes without a lock and no thread can see half of one.  It records the
        ``_builtins`` entries it was built from and is discarded when they differ -- the
        tests swap an entry after construction -- so a changed builtin takes effect on
        the very next execution, exactly as when each execution rebound every one.  The
        dicts are only ever read (``dict.update`` copies them into the namespace).
        """
        cached = self._bound_cache
        builtins = self._builtins
        if cached is not None and cached[0] is ctx and cached[1] == builtins:
            return cached[2], cached[3]
        always = {n: _bind_ctx(fn, ctx) for n, fn in builtins.items() if n not in VERBOSE_ONLY}
        verbose_only = {}
        for name in VERBOSE_ONLY:
            fn = builtins.get(name)
            if fn is not None:
                verbose_only[name] = _bind_ctx(fn, ctx)
        self._bound_cache = (ctx, dict(builtins), always, verbose_only)
        return always, verbose_only

    def compile(self, source: str, name: str = "<codelet>") -> CompiledCodelet:
        """Compile Python source to a code object. Called once at startup."""
        if not source or not source.strip():
            return CompiledCodelet(name=name, code=None, source="")
        try:
            code = compile(source, f"<codelet:{name}>", "exec")
            return CompiledCodelet(name=name, code=code, source=source)
        except SyntaxError as e:
            raise ValueError(
                f"Syntax error in codelet '{name}': {e}"
            ) from e

    def execute(
        self,
        compiled: CompiledCodelet,
        ctx: EngineContext,
        **codelet_args: Any,
    ) -> None:
        """Run a compiled codelet program against the current engine state.

        The namespace includes:
        - All registered built-in functions (pre-bound to ctx)
        - `ctx` — the full EngineContext
        - `args` — codelet-specific arguments
        - `fizzle()` — raises CodeletFizzle to abort cleanly
        - Standard Python builtins (math, min, max, etc.)
        """
        if compiled.is_empty:
            return

        # Build the execution namespace
        namespace: dict[str, Any] = {
            "ctx": ctx,
            "args": codelet_args,
            "fizzle": _fizzle,
            "CodeletFizzle": CodeletFizzle,
            # Convenience aliases
            "workspace": ctx.workspace,
            "slipnet": ctx.slipnet,
            "coderack": ctx.coderack,
            "themespace": ctx.themespace,
            "trace": ctx.trace,
            "memory": ctx.memory,
            "temperature": ctx.temperature,
            "commentary": ctx.commentary,
            "rng": ctx.rng,
            "meta": ctx.meta,
            "codelet_count": ctx.codelet_count,
            "justify_mode": ctx.justify_mode,
            "self_watching": ctx.self_watching_enabled,
            # Verbose mode's switch: a message site reads this local and builds nothing
            # when it is false (``server/engine/verbose.py``).
            "verbose": ctx.verbose,
        }

        # Add built-in functions, each pre-bound to ctx.  The bound set is cached per ctx
        # (``_bound_for``): rebuilding ~270 callables for every codelet was allocation churn
        # that every thread then paid for in shared-refcount traffic.
        bound, bound_verbose = self._bound_for(ctx)
        namespace.update(bound)
        if ctx.verbose:
            namespace.update(bound_verbose)

        # Add safe Python builtins
        namespace["math"] = math
        namespace["min"] = min
        namespace["max"] = max
        namespace["abs"] = abs
        namespace["round"] = round
        namespace["len"] = len
        namespace["range"] = range
        namespace["sum"] = sum
        namespace["any"] = any
        namespace["all"] = all
        namespace["isinstance"] = isinstance
        namespace["getattr"] = getattr
        namespace["hasattr"] = hasattr
        namespace["print"] = print  # For debugging

        try:
            exec(compiled.code, namespace)  # noqa: S102
        except CodeletFizzle:
            pass  # Normal: codelet decided not to proceed


class CodeletRegistry:
    """Maps codelet type names to compiled programs. Built from DB at startup."""

    def __init__(self) -> None:
        self._compiled: dict[str, CompiledCodelet] = {}

    @classmethod
    def from_metadata(
        cls,
        meta: Any,
        interpreter: CodeletInterpreter,
    ) -> CodeletRegistry:
        """Compile each codelet_spec.execute_body via the interpreter."""
        registry = cls()
        for name, spec in meta.codelet_specs.items():
            compiled = interpreter.compile(spec.execute_body, name=name)
            registry._compiled[name] = compiled
        return registry

    def get_compiled(self, name: str) -> CompiledCodelet:
        compiled = self._compiled.get(name)
        if compiled is None:
            return CompiledCodelet(name=name)  # Empty fallback
        return compiled

    def has(self, name: str) -> bool:
        return name in self._compiled

    @property
    def names(self) -> list[str]:
        return list(self._compiled.keys())

    def __repr__(self) -> str:
        n_compiled = sum(1 for c in self._compiled.values() if not c.is_empty)
        return f"CodeletRegistry({n_compiled}/{len(self._compiled)} compiled)"


def _fizzle() -> None:
    """Abort the current codelet execution cleanly."""
    raise CodeletFizzle()


def _bind_ctx(fn: Callable, ctx: Any) -> Callable:
    """Return a callable that passes ctx as the first argument.

    A ``functools.partial`` rather than a closure with ``__name__`` and ``__doc__``
    copied onto it.  Calling it is identical -- ``fn(ctx, *args, **kwargs)`` -- but
    building it writes no attribute of a function object.  Under free-threaded CPython
    ``func_set_name`` and ``func_set_doc`` stop the world, and this ran about 270 times
    two setattrs per codelet, which capped thread scaling near 1.8x at 16 threads.  No
    codelet body reads a builtin's ``__name__`` or ``__doc__``.
    """
    return partial(fn, ctx)
