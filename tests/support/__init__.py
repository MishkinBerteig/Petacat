"""Shared helpers for tests that are more than fixtures but less than tests.

Anything in here is imported by test modules rather than collected by pytest.
The leading rule is that a helper earns its place here only once a second
work package needs it; a helper used by one test file belongs in that file.
"""
