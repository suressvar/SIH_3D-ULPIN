"""Small local read benchmark; no remote-scale claims."""

import json
from pathlib import Path
from statistics import median
from time import perf_counter

from sqlalchemy import event, select

from app.db import get_session
from app.judge_demo import uid
from app.models import AppUser
from app.routers.governance import case
from app.routers.workspace import scene


def benchmark():
    with get_session() as db:
        engine = db.get_bind()
        user = db.scalar(select(AppUser).where(AppUser.role == "officer"))
        if user is None:
            raise RuntimeError("No officer available for the read benchmark")
        counter = [0]

        def count(*args):
            counter[0] += 1

        event.listen(engine, "before_cursor_execute", count)
        results = {}
        try:
            for name, function, object_id in [
                ("property_case", case, uid("A-301")),
                ("parcel_scene", scene, uid("P001")),
            ]:
                elapsed, queries, sizes = [], [], []
                for _ in range(20):
                    counter[0] = 0
                    start = perf_counter()
                    result = function(object_id, db, user)
                    encoded = json.dumps(result, default=str).encode()
                    elapsed.append((perf_counter() - start) * 1000)
                    queries.append(counter[0])
                    sizes.append(len(encoded))
                results[name] = {
                    "samples": len(elapsed),
                    "median_ms": round(median(elapsed), 2),
                    "p95_ms": round(sorted(elapsed)[18], 2),
                    "sql_statements_max": max(queries),
                    "response_bytes_max": max(sizes),
                }
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return {
            "scope": "Local Python read services plus JSON encoding against actual PostGIS; warm pool/cache; excludes HTTP, WAN and authentication latency",
            "results": results,
        }


if __name__ == "__main__":
    result = benchmark()
    Path("output/final-read-performance.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
