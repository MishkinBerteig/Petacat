"""C7: the read-only SQL box's statement check (``server/api/database.check_read_only_sql``)."""

import pytest
from fastapi import HTTPException

from server.api.database import check_read_only_sql


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "  select * from runs ;  ",
    "WITH a AS (SELECT 1) SELECT * FROM a",
    "-- note\nSELECT 1",
    "/* c /* nested */ */ SELECT 1",
    "SELECT 'a;b', \"x;y\" FROM t",
    "SELECT $$a;b$$",
    "SELECT $q$ a;b $q$ -- ; here",
])
def test_one_select_or_with_is_accepted(sql):
    assert check_read_only_sql(sql)


@pytest.mark.parametrize("sql", [
    "", ";", "-- only a comment", "INSERT INTO t VALUES (1)", "update t set a = 1",
    "DELETE FROM t", "DROP TABLE t", "VACUUM", "SELECT 1; SELECT 2", "SELECT 1; DROP TABLE t;",
    "/* SELECT */ DELETE FROM t", "EXPLAIN SELECT 1",
])
def test_anything_else_is_refused(sql):
    with pytest.raises(HTTPException) as info:
        check_read_only_sql(sql)
    assert info.value.status_code == 400


def test_the_trailing_semicolon_and_comment_are_trimmed_to_one_statement():
    assert check_read_only_sql("SELECT 1;  ") == "SELECT 1"
