"""One garage for every device.

Each browser keeps its own copy of the cars, which is fast and works with no setup, but it means a phone and a
laptop each have a garage of their own. When a garage store is set up, the cars are also kept there, one row a
car, and every device that uses the same API key reads and writes the same rows.

How it stays simple and safe:

- The store is two SQL functions on a Postgres table (see tools/garage_store.sql), reached over HTTPS with a
  key that is safe to publish. The table itself cannot be read or written with that key, only the functions,
  and both need the garage's id.
- A garage's id is a hash of the API key the buyer uses, so it is never typed, never stored beside the cars,
  and cannot be turned back into the key. Whoever has the key has the garage; nobody else can name it.
- Every car carries the time it last changed. The newer copy of a car wins, in the app and again in the
  store, so two devices can each change different cars and neither loses anything. A removed car leaves a
  marker behind, so an older copy on another device does not bring it back.
- Nothing here touches Streamlit, and saving happens on a background thread: a slow or missing store never
  holds the page up, and the browser's copy is always there.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TIMEOUT = 6.0
MAX_CAR_BYTES = 1_500_000                 # one car's facts, comps, offer and message: far below this in practice
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="garage-store")
_LOCK = threading.Lock()
_STATE: dict[str, dict] = {}              # garage id -> {"saved": when, "error": what, "waiting": how many}


class SyncError(Exception):
    """The garage store could not be reached, or turned the request down."""


def settings(url: str = "", key: str = "") -> tuple[str, str]:
    """(address, key) of the garage store, from what the app passes in or from the environment. ('', '') when
    none is set up, which turns all of this off."""
    url = (url or os.environ.get("DEALSHEET_DB_URL") or "").strip().rstrip("/")
    key = (key or os.environ.get("DEALSHEET_DB_KEY") or "").strip()
    return (url, key) if url and key else ("", "")


def garage_id(api_key: str) -> str:
    """The name of the garage that belongs to an API key: 64 hex characters that cannot be turned back into it."""
    api_key = str(api_key or "").strip()
    return hashlib.sha256(("dealsheet garage:" + api_key).encode("utf-8")).hexdigest() if api_key else ""


def digest(deal: dict) -> str:
    """A short fingerprint of a car's facts, to tell whether anything about it has changed."""
    return hashlib.sha256(json.dumps(deal, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20]


def _call(conf: tuple[str, str], name: str, body: dict):
    url, key = conf
    request = urllib.request.Request(
        f"{url}/rest/v1/rpc/{name}", data=json.dumps(body, default=str).encode("utf-8"), method="POST",
        headers={"apikey": key, "authorization": f"Bearer {key}", "content-type": "application/json", "accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
            text = reply.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise SyncError(f"the garage store turned the request down ({exc.code}: {detail})") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SyncError(f"the garage store could not be reached ({getattr(exc, 'reason', exc)})") from exc
    try:
        return json.loads(text) if text.strip() else None
    except ValueError as exc:
        raise SyncError("the garage store sent back something that could not be read") from exc


def load(conf: tuple[str, str], garage: str) -> list[dict]:
    """Every car kept for a garage: [{"car_id", "data", "deleted", "at"}]. Raises SyncError."""
    rows = _call(conf, "dealsheet_load", {"p_garage": garage})
    out = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("car_id"):
            out.append({"car_id": str(row["car_id"]), "data": row.get("data") if isinstance(row.get("data"), dict) else None,
                        "deleted": bool(row.get("deleted")), "at": float(row.get("at") or 0)})
    return out


def save(conf: tuple[str, str], garage: str, car_id: str, data: dict | None, deleted: bool, at: float) -> None:
    """Write one car, or the marker that it was removed. The store keeps whichever copy is newer. Raises SyncError."""
    if data is not None and len(json.dumps(data, default=str)) > MAX_CAR_BYTES:
        raise SyncError("that car is too large to keep in the garage store")
    _call(conf, "dealsheet_save", {"p_garage": garage, "p_car": car_id, "p_data": data, "p_deleted": bool(deleted), "p_at": float(at)})


def save_later(conf: tuple[str, str], garage: str, car_id: str, data: dict | None, deleted: bool, at: float) -> None:
    """Write one car on a background thread. What happened is kept for status()."""
    if data is not None:
        data = json.loads(json.dumps(data, default=str))      # a copy of its own: the page may go on changing the car
    with _LOCK:
        state = _STATE.setdefault(garage, {"saved": 0.0, "error": "", "waiting": 0})
        state["waiting"] += 1

    def work():
        try:
            save(conf, garage, car_id, data, deleted, at)
            problem = ""
        except SyncError as exc:
            problem = str(exc)
        except Exception as exc:                       # never let a background save take anything down
            problem = f"saving stopped on an unexpected problem ({type(exc).__name__})"
        with _LOCK:
            state["waiting"] = max(0, state["waiting"] - 1)
            if problem:
                state["error"] = problem
            else:
                state["saved"], state["error"] = time.time(), ""

    _POOL.submit(work)


def status(garage: str) -> dict:
    """{"saved": when the last save landed (0 for never), "error": the last problem or '', "waiting": saves under way}."""
    with _LOCK:
        return dict(_STATE.get(garage) or {"saved": 0.0, "error": "", "waiting": 0})


def note_problem(garage: str, problem: str) -> None:
    with _LOCK:
        _STATE.setdefault(garage, {"saved": 0.0, "error": "", "waiting": 0})["error"] = problem


def merge(local: dict[str, dict], rows: list[dict]) -> dict:
    """What to do with the cars a device holds once the store's rows are in hand.

    `local` maps a car's id to its deal (with "at", the time it last changed, 0 when unknown). Returns
    {"add": [(id, deal)], "put": [(id, deal)], "drop": [id], "gone": {id: at}}: cars the device does not have,
    cars the store holds a newer copy of, cars removed elsewhere after this device's copy was last changed, and
    every removal marker (so an older copy that turns up later is not brought back). Anything the device holds
    that is newer than the store, or that the store has never seen, is left alone: the app saves it up.
    """
    out = {"add": [], "put": [], "drop": [], "gone": {}}
    for row in rows:
        car_id, at = row["car_id"], float(row.get("at") or 0)
        mine = local.get(car_id)
        mine_at = float((mine or {}).get("at") or 0)
        if row["deleted"]:
            out["gone"][car_id] = at
            if mine is not None and at >= mine_at:
                out["drop"].append(car_id)
        elif row["data"] is not None:
            deal = {**row["data"], "at": at}
            if mine is None:
                out["add"].append((car_id, deal))
            elif at > mine_at:
                out["put"].append((car_id, deal))
    return out
