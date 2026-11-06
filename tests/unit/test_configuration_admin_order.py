"""Stage 4 (F-change-api): the order a reset or a restore writes its ops in.

An enum row is named by other rows through a foreign key and its ``role`` is unique, so a
renamed row cannot be put back by a plain delete-then-insert: the new row comes first (without
its role), then the rows that name it, then the delete of the old row, then the role.
"""

from __future__ import annotations

from server.services import config_document as cd
from server.services.change_resolve import resolve
from server.services.configuration_admin import _order
from tests.integration.equivalence_harness import SEED_DIR


def _renamed(table, old, new):
    base = cd.document_from_standard_files(SEED_DIR)
    ops, _ = resolve(base, {"ops": [{"op": "rename_enum_value", "table": table, "old": old, "new": new}]})
    return base, cd.apply_resolved(base, ops)


def test_putting_a_renamed_enum_row_back_inserts_first_deletes_last_and_gives_the_role_last():
    base, renamed = _renamed("posting_directions", "bottom_up", "bu")
    ops = _order(cd.diff(renamed, base))
    kinds = [(o["op"], o["table"]) for o in ops]
    first_insert = kinds.index(("insert", "posting_directions"))
    last_child = max(i for i, k in enumerate(kinds) if k == ("update", "posting_rules"))
    delete = kinds.index(("delete", "posting_directions"))
    assert first_insert < min(i for i, k in enumerate(kinds) if k == ("update", "posting_rules"))
    assert last_child < delete
    assert ops[first_insert]["row"]["role"] is None  # unique: the old row still holds it
    assert ops[-1] == {"op": "update", "table": "posting_directions", "key": {"name": "bottom_up"},
                       "set": {"role": "posting_direction.bottom_up"}}
    # applied in this order the document is the standard one again, with no op naming a row
    # that is not there (the document would raise)
    assert cd.apply_resolved(renamed, ops).content_equals(base)


def test_other_deletes_still_come_first_children_before_parents():
    base = cd.document_from_standard_files(SEED_DIR)
    ops = [{"op": "delete", "table": "slipnet_node_defs", "key": {"name": "plato-a"}},
           {"op": "delete", "table": "slipnet_link_defs", "key": {"from_node": "plato-a", "to_node": "plato-b",
                                                                 "link_type": "lateral", "label_node": "plato-successor"}}]
    assert [o["table"] for o in _order(ops)] == ["slipnet_link_defs", "slipnet_node_defs"]
    assert base
