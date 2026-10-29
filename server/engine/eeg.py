"""The EEG -- Workspace activity and temperature, sampled once per update cycle.

Scheme source: ``eeg-graphics.ss`` (``%EEG-table%``, ``make-EEG``, ``new-EEG-window``);
sampled by ``update-everything`` (``run.ss:320-322``).

The Scheme's EEG records three values at every update cycle: the current Workspace
activity (not plotted), the **average of the last 10 recorded activity values**
(plotted yellow), and the current temperature (plotted red).  It keeps them in a
40-slot ring buffer initialised to 100, and the window plots a line segment per cycle
from the previous point to the new one, starting from ``(0, 100)``.

Two details are reproduced exactly:

- The average is taken by the table's thunk *before* the new row is stored
  (``get-values`` runs every thunk, and only then does ``record-current-values`` write
  the row), so it covers the **previous** ten samples and never the current one.  The
  buffer starts full of the initial value 100, so early averages are pulled toward 100.
- The window plots at x = (cycle number), the first sample at cycle 0.

The full history is kept (a run is a few thousand cycles), not just the ring buffer,
because the web view shows the whole run where the Scheme scrolls a window over it.
"""

from __future__ import annotations

from dataclasses import dataclass

#: ``%EEG-buffer-size%`` -- the ring buffer's length.
BUFFER_SIZE = 40
#: The window of previous activity values the plotted average covers.
AVERAGE_WINDOW = 10
#: Every table entry's ``initial-value``.
INITIAL_VALUE = 100.0

#: The plotted series, in the order and colours of ``%EEG-table%`` (entries with
#: plot? = #t): index, label, colour name.
PLOTTED_SERIES = (
    ("average_activity", "Average Workspace Activity", "yellow"),
    ("temperature", "Temperature", "red"),
)


@dataclass
class EEGSample:
    cycle: int
    codelet_count: int
    activity: float
    average_activity: float
    temperature: float

    def as_dict(self) -> dict:
        return {
            "cycle": self.cycle,
            "codelet_count": self.codelet_count,
            "activity": self.activity,
            "average_activity": self.average_activity,
            "temperature": self.temperature,
        }


class EEG:
    """``make-EEG``: record the table's values at each update cycle."""

    def __init__(self) -> None:
        self.samples: list[EEGSample] = []
        # The ring buffer of recorded Workspace activity values, newest last.
        self._activity: list[float] = [INITIAL_VALUE] * BUFFER_SIZE

    def record(self, activity: float, temperature: float, codelet_count: int) -> EEGSample:
        previous = self._activity[-AVERAGE_WINDOW:]
        average = sum(previous) / len(previous)
        self._activity.append(activity)
        del self._activity[0]
        sample = EEGSample(
            cycle=len(self.samples),
            codelet_count=codelet_count,
            activity=activity,
            average_activity=average,
            temperature=temperature,
        )
        self.samples.append(sample)
        return sample

    def history(self) -> dict:
        """The plotted curves, in the shape the API serves."""
        return {
            "series": [
                {"key": key, "label": label, "color": color}
                for key, label, color in PLOTTED_SERIES
            ],
            "initial_value": INITIAL_VALUE,
            "samples": [s.as_dict() for s in self.samples],
        }
