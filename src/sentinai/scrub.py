"""Keep personal data out of what the SDK sends."""

import re
import traceback
from types import TracebackType

ExcInfo = tuple[type[BaseException], BaseException, TracebackType | None]

WITHHELD = "<message withheld>"
_DB_EXCEPTION = re.compile(
    r"^(?:sqlalchemy|psycopg2|psycopg|sqlite3|pymysql|asyncpg|aiosqlite|MySQLdb|mysql"
    r"|pyodbc|oracledb|cx_Oracle|django\.db)[\w.]*:"
)
_TRACE_BOUNDARY = re.compile(r'^(?:Traceback \(|The above exception|During handling|\s+File ")')


def withhold_db_messages(text: str) -> str:
    """Cut the message of database exceptions: it can carry names, phones, emails."""
    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        if _TRACE_BOUNDARY.match(line):
            skipping = False
        if skipping:
            continue
        if _DB_EXCEPTION.match(line):
            kept.append(line.split(":", 1)[0] + ": " + WITHHELD)
            skipping = True
            continue
        kept.append(line)
    return "\n".join(kept)


def safe_traceback(exc_info: ExcInfo) -> str:
    """Format a traceback with database exception messages withheld."""
    return withhold_db_messages("".join(traceback.format_exception(*exc_info)))


def trim(text: str, limit: int) -> str:
    """Keep the start and the end (the exception line) inside the limit."""
    if len(text) <= limit:
        return text
    head = limit // 4
    return text[:head] + "\n  ... trimmed ...\n" + text[-(limit - head - 20) :]
