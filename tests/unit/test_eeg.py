"""The EEG's recorder: ``eeg-graphics.ss`` ``make-EEG`` and its ``%EEG-table%``.

Metacat records Workspace activity, the average of the last ten activity values, and
the temperature at each update cycle, from a 40-slot ring buffer initialised to 100.
The average is computed before the new row is stored, so it covers the previous ten
readings and never the current one -- the detail these tests pin.
"""

from server.engine.eeg import AVERAGE_WINDOW, BUFFER_SIZE, INITIAL_VALUE, EEG


def test_the_first_average_is_the_initial_value_whatever_the_first_activity():
    eeg = EEG()
    sample = eeg.record(activity=0, temperature=80, codelet_count=15)
    assert sample.average_activity == INITIAL_VALUE
    assert sample.activity == 0
    assert sample.temperature == 80
    assert sample.cycle == 0


def test_the_average_covers_the_previous_ten_readings_not_the_current():
    eeg = EEG()
    for _ in range(AVERAGE_WINDOW):
        eeg.record(activity=0, temperature=50, codelet_count=0)
    # Ten zeros are now the previous ten readings.
    sample = eeg.record(activity=100, temperature=50, codelet_count=0)
    assert sample.average_activity == 0
    # The next average sees that 100 and nine zeros.
    after = eeg.record(activity=0, temperature=50, codelet_count=0)
    assert after.average_activity == 10


def test_early_averages_are_pulled_toward_the_initial_value():
    eeg = EEG()
    eeg.record(activity=0, temperature=100, codelet_count=0)
    second = eeg.record(activity=0, temperature=100, codelet_count=0)
    # One zero and nine initial 100s.
    assert second.average_activity == 90


def test_the_history_names_the_two_plotted_curves_in_metacats_colours():
    eeg = EEG()
    eeg.record(activity=40, temperature=70, codelet_count=15)
    history = eeg.history()
    assert [(s["key"], s["color"]) for s in history["series"]] == [
        ("average_activity", "yellow"),
        ("temperature", "red"),
    ]
    assert history["initial_value"] == 100
    assert history["samples"][0]["codelet_count"] == 15


def test_the_buffer_is_forty_slots_but_the_history_keeps_every_cycle():
    eeg = EEG()
    for i in range(BUFFER_SIZE + 25):
        eeg.record(activity=i % 100, temperature=50, codelet_count=i)
    assert len(eeg.history()["samples"]) == BUFFER_SIZE + 25
    assert [s["cycle"] for s in eeg.history()["samples"]][-1] == BUFFER_SIZE + 24
