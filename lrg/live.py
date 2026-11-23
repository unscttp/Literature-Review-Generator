"""Tasks of one run that are running right now, as reported by DGS run observers.

DGS calls ``observe`` before every node execution, including the nodes of a
skill graph, which run as child tasks inside the stage's ``run_graph`` call.
The workflow viewer reads them from here while they run; afterwards the
child tasks are read from the stage's saved graph records.
"""

from __future__ import annotations

import threading

from workflow_core import Task


class LiveTasks:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._guard = threading.Lock()

    def observe(self, task: Task, execution) -> None:
        with self._guard:
            self._tasks[task.id] = task

    def get(self, task_id: str) -> Task | None:
        with self._guard:
            return self._tasks.get(task_id)

    def children(self, task_id: str, execution_id: str | None = None) -> list[Task]:
        with self._guard:
            tasks = list(self._tasks.values())
        return [
            task
            for task in tasks
            if task.metadata.get("parent_task_id") == task_id
            and (execution_id is None or task.metadata.get("parent_execution_id") == execution_id)
        ]

    def clear(self) -> None:
        with self._guard:
            self._tasks.clear()
