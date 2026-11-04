import sqlite3
import sys

from sentinai import scrub

CHAINED = """\
Traceback (most recent call last):
  File "app.py", line 3, in save
    db.commit()
sqlalchemy.exc.IntegrityError: (psycopg2.errors.UniqueViolation) duplicate key
DETAIL:  Key (phone)=(255700000000) already exists.
[SQL: INSERT INTO users (phone) VALUES (%(phone)s)]

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "app.py", line 9, in view
    save()
ValueError: could not save
"""


def test_database_message_is_withheld_and_the_rest_is_kept():
    out = scrub.withhold_db_messages(CHAINED)
    assert "sqlalchemy.exc.IntegrityError: <message withheld>" in out
    assert "255700000000" not in out
    assert "INSERT INTO" not in out
    assert 'File "app.py", line 3' in out
    assert "ValueError: could not save" in out


def test_text_without_database_errors_is_unchanged():
    text = 'Traceback (most recent call last):\n  File "a.py", line 1\nValueError: x'
    assert scrub.withhold_db_messages(text) == text


def test_safe_traceback_withholds_a_real_sqlite_error():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("SELECT * FROM nothing_here")
    except sqlite3.Error:
        out = scrub.safe_traceback(sys.exc_info())
    finally:
        conn.close()
    assert "no such table" not in out
    assert "sqlite3.OperationalError: <message withheld>" in out


def test_trim_leaves_short_text_alone():
    assert scrub.trim("short", 1000) == "short"


def test_trim_keeps_the_start_and_the_end_inside_the_limit():
    text = "S" * 5000 + "END"
    out = scrub.trim(text, 1000)
    assert len(out) <= 1000
    assert out.startswith("S" * 250)
    assert out.endswith("END")
    assert "... trimmed ..." in out
