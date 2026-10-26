"""Deterministic Redis queue precedence, independent of Kombu's active queue set."""
from kombu.utils.scheduling import priority_cycle


class WorkQueueCycle(priority_cycle):
    def consume(self, n):
        order = {"control": 0, "match": 1, "index": 2, "ingest": 3}
        return sorted(self.items, key=lambda queue: (order.get(queue, 4), queue))[:n]
