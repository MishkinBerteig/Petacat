"""Unit (C12): the pure parts of edit-all: the preview token, the batch each target gets, and
how a refusal or a report becomes one of the six results (configuration plan 3.10.3)."""

import pytest

from server.services import configuration_edits as e
from server.services.configuration_writer import ChangeError

OPS = [{"op": "set_param", "name": "p", "to": 3, "expect": 1}]


def test_the_token_round_trips_with_revisions_and_skips():
    token = e.encode_token(OPS, "why", {1: (4, None), 7: (None, "frozen")})
    body = e.decode_token(token)
    assert body["ops"] == OPS and body["note"] == "why"
    assert body["targets"] == [(1, 4, None), (7, None, "frozen")]


@pytest.mark.parametrize("token", ["", "nonsense", "e30=", "eyJ2IjogOTl9"])
def test_a_bad_token_is_a_400(token):
    with pytest.raises(e.EditError) as caught:
        e.decode_token(token)
    assert caught.value.status == 400


def test_every_target_batch_is_an_admin_batch_with_one_configuration_id():
    target = {"configuration_id": 5}
    batch = e._batch(target, OPS, base_version=2, note="n", dry_run=False, group_id="g")
    assert (batch["source"], batch["actor"], batch["configuration_id"], batch["group_id"]) == ("admin", "admin", 5, "g")
    assert batch["base_mode"] == "strict" and batch["on_op_failure"] == "abort" and batch["ops"] == OPS
    assert "group_id" not in e._batch(target, OPS, base_version=2, note="", dry_run=True)


def test_overwrite_drops_expect_and_apply_rest_skips_failing_ops():
    target = {"configuration_id": 5}
    batch = e._batch(target, OPS, base_version=2, note="", dry_run=False, overwrite=True, apply_rest=True)
    assert batch["ops"] == [{"op": "set_param", "name": "p", "to": 3}] and batch["on_op_failure"] == "skip"
    assert OPS[0]["expect"] == 1  # the caller's ops are not changed


def test_a_report_is_apply_not_applicable_or_no_change():
    assert e._classify_report({"applied": [{}], "skipped": [{}]})[0] == e.APPLY
    result, reason = e._classify_report({"applied": [], "skipped": [{"reason": {"message": "no row"}}]})
    assert (result, reason) == (e.NOT_APPLICABLE, "no row")
    assert e._classify_report({"applied": [], "skipped": []})[0] == e.NO_CHANGE


def test_a_refusal_is_a_result_unless_the_request_itself_is_wrong():
    def refusal(code, field=None):
        return ChangeError(code, "m", [{"field": field}] if field else [])

    assert e._classify_error(refusal("stale", "base_version"))[0] == e.STALE
    assert e._classify_error(refusal("stale", "expect"))[0] == e.DIFFERS
    for code in ("unknown_reference", "key_exists", "does_not_compile"):
        assert e._classify_error(refusal(code))[0] == e.NOT_APPLICABLE
    assert e._classify_error(refusal("busy"))[0] == e.SKIPPED_BY_SELECTION
    for code in ("malformed", "source_refused", "unknown_configuration"):
        with pytest.raises(ChangeError):
            e._classify_error(refusal(code))


def test_selection_skips_frozen_only_by_default_and_a_changing_state_always():
    frozen = {"frozen": True, "session_state": "stopped"}
    assert e._selection_skip(frozen, by_default=True) == "frozen"
    assert e._selection_skip(frozen, by_default=False) is None
    for state in ("starting", "stopping"):
        assert e._selection_skip({"frozen": False, "session_state": state}, by_default=False) == "changing state"
    assert e._selection_skip({"frozen": False, "session_state": None}, by_default=True) is None


def test_choosing_targets():
    targets = {1: {}, 4: {}, 9: {}}
    assert e._choose(targets, None, True) == [1, 4, 9]
    assert e._choose(targets, [9, 1, 9], False) == [1, 9]
    for ids, all_ in ((None, False), ([1], True), ([], False)):
        with pytest.raises(e.EditError) as caught:
            e._choose(targets, ids, all_)
        assert caught.value.status == 400
    with pytest.raises(e.EditError) as caught:
        e._choose(targets, [2], False)
    assert caught.value.status == 404
