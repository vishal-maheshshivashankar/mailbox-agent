"""Single shared checkpointer + compiled graphs for the whole process.

One SqliteSaver connection is reused everywhere so scheduled sort/sweep runs
and the Telegram-triggered resume all see the same checkpoint state -
required for interrupt()/Command(resume=...) to find the paused thread.
"""

import sqlite3
import threading
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from mailbox_agent import config
from mailbox_agent.graphs.retention_sweep import build_sweep_graph
from mailbox_agent.graphs.sort_loop import build_sort_graph

INVOKE_LOCK = threading.Lock()

_checkpointer = None
_sort_graph = None
_sweep_graph = None


def _get_checkpointer() -> SqliteSaver:
    global _checkpointer
    if _checkpointer is None:
        Path(config.CHECKPOINT_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH, check_same_thread=False)
        _checkpointer = SqliteSaver(conn)
    return _checkpointer


def get_sort_graph():
    global _sort_graph
    if _sort_graph is None:
        _sort_graph = build_sort_graph().compile(checkpointer=_get_checkpointer())
    return _sort_graph


def get_sweep_graph():
    global _sweep_graph
    if _sweep_graph is None:
        _sweep_graph = build_sweep_graph().compile(checkpointer=_get_checkpointer())
    return _sweep_graph


def reset_graphs() -> None:
    """Test-only: drop cached graphs/checkpointer so the next get_*_graph()
    call re-reads config.CHECKPOINT_DB_PATH (e.g. after pointing it at a
    temp file)."""
    global _checkpointer, _sort_graph, _sweep_graph
    if _checkpointer is not None:
        _checkpointer.conn.close()
    _checkpointer = None
    _sort_graph = None
    _sweep_graph = None
