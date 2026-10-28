"""Background jobs: reference-data sync (step 4) and write-behind flush (step 7).

They run on a thread inside the web app to keep the sample to one deployable
app. A short Redis lock makes sure only one replica runs each job per interval;
without it, two replicas could flush the same batch of views twice. In
production, run these from a single scheduled job, such as a timer-triggered
function.
"""
import threading
import traceback

from .cache import cache
from .config import settings
from .patterns import prefetch, write_behind


def _run_once(name: str, interval: int, job) -> None:
    # The lock expires just before the next run, so if a replica stops, another takes over.
    if cache.set(f"lock:job:{name}", "1", nx=True, ex=max(interval - 1, 1)):
        job()


def _loop(stop: threading.Event, name: str, interval: int, job) -> None:
    while not stop.wait(interval):
        try:
            _run_once(name, interval, job)
        except Exception:
            print(f"[{name}] failed; retrying next interval:", flush=True)
            traceback.print_exc()


def start() -> threading.Event:
    stop = threading.Event()
    jobs = [
        ("sync-categories", settings.sync_interval_seconds, prefetch.sync_categories),
        ("flush-views", settings.flush_interval_seconds, write_behind.flush_views),
    ]
    for name, interval, job in jobs:
        threading.Thread(target=_loop, args=(stop, name, interval, job), name=name, daemon=True).start()
        print(f"[{name}] every {interval}s", flush=True)
    return stop
