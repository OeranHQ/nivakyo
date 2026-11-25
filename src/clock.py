"""Integer virtual time with stable, inclusive event boundaries; no wall-clock sleeps."""
import heapq


def milliseconds(value):
    if type(value) is not int or value < 0:
        raise ValueError('Time must be a nonnegative integer number of milliseconds')
    return value


class VirtualClock:
    def __init__(self):
        self._now = 0
        self._sequence = 0
        self._events = []

    @property
    def now_ms(self):
        return self._now

    def schedule_at(self, at_ms, callback):
        milliseconds(at_ms)
        if at_ms < self._now or not callable(callback):
            raise ValueError('Events require a callable and cannot be scheduled in the past')
        self._sequence += 1
        heapq.heappush(self._events, (at_ms, self._sequence, callback))

    def advance(self, duration_ms):
        target = self._now + milliseconds(duration_ms)
        while self._events and self._events[0][0] <= target:
            at_ms, _, callback = heapq.heappop(self._events)
            self._now = at_ms
            callback()
        self._now = target

    def settle(self):
        """Evaluator-only draining; callers must not turn this into agent evidence."""
        while self._events:
            self.advance(self._events[0][0] - self._now)
