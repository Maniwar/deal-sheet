"""Long work on its own thread.

A build or a search takes a minute or more. Streamlit runs the page's script again whenever the person taps
something or the page reconnects (a phone waking up does that), and a script that is in the middle of a search
is stopped where it stands. Work done inside the script is thrown away and started over each time that
happens, which costs the whole search again. A `Job` does the work on a thread of its own instead: the script
only starts it, shows its progress and collects what it made, so nothing the person does while it runs starts
it again.

The work must not touch Streamlit (a thread has no page to draw on): it gets what it needs when it starts and
hands back a plain dictionary.
"""

from __future__ import annotations

import threading
import time

import llm


# Jobs under way, by the browser that asked for them. They live outside any one visit to the page, so a page
# that comes back as a new visit (reloaded, or reconnected after the phone slept) finds its work still running,
# or finished and waiting, instead of asking for it again.
_JOBS: dict[str, "Job"] = {}
_LOCK = threading.Lock()
_KEEP = 20 * 60           # seconds a finished job waits to be collected before it is let go


def current(key: str) -> "Job | None":
    """The job this browser has under way or waiting to be collected, if any."""
    with _LOCK:
        job = _JOBS.get(key)
        if job is not None and job.done and time.time() - job.ended > _KEEP:
            _JOBS.pop(key, None)
            return None
        return job


def start(key: str, job: "Job") -> None:
    with _LOCK:
        _JOBS[key] = job


def take(key: str) -> "Job | None":
    """Hand over a finished job, once."""
    with _LOCK:
        job = _JOBS.get(key)
        if job is None or not job.done:
            return None
        return _JOBS.pop(key)


class Job:
    """One piece of long work. `run(job)` returns the outcome, a dictionary; an error becomes {'error': text}."""

    def __init__(self, kind: str, run, car_id: str = "", name: str = "", flag: str = "", asked: str = ""):
        self.kind = kind                    # 'build', 'more' or 'verify'
        self.car_id = car_id                # the car the work is for; a build makes a new car, so it has none
        self.name = name                    # that car's short name, for a notice when another car is on screen
        self.flag = flag                    # which button started it, so the screen can show it as working
        self.asked = asked                  # what a build was asked for, for the screen
        self.progress = llm.Progress()      # lines about what is happening; any thread may add one
        self.step = 0                       # the step a build is on
        self.started = time.time()
        self.ended = 0.0
        self.outcome: dict | None = None    # set once, when the work has finished
        self._thread = threading.Thread(target=self._work, args=(run,), daemon=True)
        self._thread.start()

    def _work(self, run) -> None:
        try:
            outcome = run(self) or {}
        except llm.LLMError as exc:
            outcome = {"error": str(exc)}
        except Exception as exc:            # whatever went wrong, the screen must hear that the work has ended
            outcome = {"error": f"That stopped on an unexpected problem ({type(exc).__name__}). Try it again."}
        self.ended = time.time()
        self.outcome = outcome

    def say(self, step: int) -> None:
        self.step = int(step)

    @property
    def done(self) -> bool:
        return self.outcome is not None

    @property
    def seconds(self) -> int:
        return int(time.time() - self.started)
