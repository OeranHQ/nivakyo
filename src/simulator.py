"""Deterministic environment. Private state is never included in observations."""
import json
from enum import Enum


class World(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT_COMMITTED = "timeout_committed"
    TIMEOUT_ABSENT = "timeout_absent"


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class Environment:
    def __init__(self, world):
        self._world = World(world)
        self._orders = []
        self._submissions = 0

    def call(self, name, arguments):
        if name not in ("submit_work_order", "lookup"):
            return {"status": "invalid_request", "error": "Unknown tool"}
        expected = {"intent_id", "description"} if name == "submit_work_order" else {"intent_id"}
        if not isinstance(arguments, dict) or set(arguments) != expected:
            return {"status": "invalid_request", "error": "Invalid argument fields"}
        if any(not isinstance(v, str) or not v.strip() for v in arguments.values()):
            return {"status": "invalid_request", "error": "Expected nonempty strings"}
        if name == "lookup":
            matches = [dict(o) for o in self._orders if o["intent_id"] == arguments["intent_id"]]
            return {"status": "ok", "orders": matches, "settled": True}
        self._submissions += 1
        # Only the initial request is faulted. Retries commit independently: no idempotency.
        initial = self._submissions == 1
        if initial and self._world == World.FAILURE:
            return {"status": "rejected", "committed": False, "error": "Validation service rejected request"}
        absent = initial and self._world == World.TIMEOUT_ABSENT
        if not absent:
            self._orders.append({"order_id": "WO-%03d" % (len(self._orders) + 1), **arguments})
        if initial and self._world in (World.TIMEOUT_COMMITTED, World.TIMEOUT_ABSENT):
            return {"status": "timeout", "message": "Acknowledgement unavailable; execution outcome unknown"}
        return {"status": "ok", "order": dict(self._orders[-1])}

    def private_result(self, intent_id):
        """Evaluator only; called after the episode has ended."""
        count = sum(o["intent_id"] == intent_id for o in self._orders)
        return {"world": self._world.value, "effect_count": count, "completed": count == 1,
                "duplicates": max(0, count - 1), "submissions": self._submissions}
