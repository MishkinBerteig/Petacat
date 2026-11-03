"""The funnel's pure parts: the envelope check, the error type and its HTTP mapping."""

from __future__ import annotations

import pytest

from server.services import journal
from server.services.configuration_writer import (
    ChangeError,
    _translate,
    check_envelope,
    error_body,
)


def batch(**extra):
    return {"source": "admin", "base_version": 1, "ops": [], **extra}


def test_a_minimal_envelope_is_accepted():
    check_envelope(batch())
    check_envelope(batch(base_version="head", base_mode="rebase", on_op_failure="skip",
                         dry_run=True, actor="admin", note="n", channel="admin_editor",
                         group_id="g", configuration_id=1))


@pytest.mark.parametrize(
    "bad,field",
    [
        ("not an object", None),
        ({"source": "admin", "ops": "x"}, "ops"),
        ({"source": "admin"}, "ops"),
        ({"ops": []}, "source"),
        ({"source": "wizard", "ops": []}, "source"),
        (batch(extra=1), "extra"),
        (batch(base_mode="fast"), "base_mode"),
        (batch(on_op_failure="ignore"), "on_op_failure"),
        (batch(dry_run="yes"), "dry_run"),
        (batch(base_version="1"), "base_version"),
        (batch(base_version=True), "base_version"),
        (batch(configuration_id="1"), "configuration_id"),
        (batch(note=5), "note"),
    ],
)
def test_a_bad_envelope_is_400_malformed_and_names_the_field(bad, field):
    with pytest.raises(ChangeError) as caught:
        check_envelope(bad)
    assert caught.value.code == "malformed" and caught.value.status == 400
    if field:
        assert caught.value.problems[0]["field"] == field


def test_an_op_that_is_not_an_object_names_its_index():
    with pytest.raises(ChangeError) as caught:
        check_envelope(batch(ops=[{"op": "delete"}, 5]))
    assert caught.value.problems[0]["op_index"] == 1


def test_the_codes_map_to_the_plans_statuses():
    statuses = {
        code: ChangeError(code, "m").status
        for code in ("malformed", "unknown_reference", "does_not_compile", "stale",
                     "key_exists", "source_refused", "unknown_configuration")
    }
    assert statuses == {
        "malformed": 400, "unknown_reference": 422, "does_not_compile": 422, "stale": 409,
        "key_exists": 409, "source_refused": 403, "unknown_configuration": 404,
    }


def test_error_body_carries_code_status_message_and_problems():
    body = error_body(ChangeError("stale", "old", [{"op_index": 2}]))
    assert body == {"ok": False, "error": "stale", "status": 409, "message": "old",
                    "problems": [{"op_index": 2}]}


def test_error_response_is_a_json_response_with_the_status():
    from server.services.configuration_writer import error_response

    response = error_response(ChangeError("does_not_compile", "bad"))
    assert response.status_code == 422


def test_journal_errors_translate_to_the_codes():
    assert _translate(journal.SourceRefused("m")).code == "source_refused"
    assert _translate(journal.StaleRevision("m")).code == "stale"
    assert _translate(journal.KeyExists("m")).code == "key_exists"
    assert _translate(journal.MissingKey("m")).code == "unknown_reference"
    assert _translate(ValueError("x")) is None
