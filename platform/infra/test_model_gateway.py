import asyncio
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).parent / 'model_gateway.py'

class GatewayContract(unittest.IsolatedAsyncioTestCase):
    async def test_shared_priority_queue_is_serial_and_cancellable(self):
        self.assertTrue(MODULE.exists(), 'model gateway must exist')
        spec = importlib.util.spec_from_file_location('model_gateway', MODULE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        gate = mod.PriorityGate(max_pending=3)
        order = []
        release = asyncio.Event()
        async def work(name, priority, block=False):
            async with gate.slot(priority):
                order.append(name)
                if block:
                    await release.wait()
        first = asyncio.create_task(work('chat-current', 20, True))
        await asyncio.sleep(0)
        embedding = asyncio.create_task(work('embedding', 30))
        low = asyncio.create_task(work('cancelled', 30))
        high = asyncio.create_task(work('interactive', 0))
        await asyncio.sleep(0)
        low.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await low
        release.set()
        await asyncio.gather(first, embedding, high)
        self.assertEqual(order, ['chat-current', 'interactive', 'embedding'])
        self.assertEqual(gate.pending, 0)
        self.assertFalse(gate.active)

    async def test_embeddings_wait_behind_interactive_calls_by_default(self):
        spec = importlib.util.spec_from_file_location('model_gateway', MODULE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertLess(mod.request_priority('api/chat', None), mod.request_priority('api/embed', None))
        self.assertEqual(mod.request_priority('api/embed', '0'), 0)
        with self.assertRaises(ValueError): mod.request_priority('api/chat', 'invalid')

    async def test_queue_rejects_overload_without_losing_lock(self):
        self.assertTrue(MODULE.exists(), 'model gateway must exist')
        spec = importlib.util.spec_from_file_location('model_gateway', MODULE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        gate = mod.PriorityGate(max_pending=0)
        async with gate.slot(20):
            with self.assertRaises(mod.QueueFull):
                async with gate.slot(20):
                    self.fail('overload was admitted')
        async with gate.slot(20):
            self.assertTrue(gate.active)

if __name__ == '__main__':
    unittest.main()

