from pathlib import Path
p=Path(__file__).parent/'test_model_gateway.py'
s=p.read_text('utf-8-sig')
s=s.replace("    async def test_queue_rejects_overload_without_losing_lock(self):", """    async def test_embeddings_wait_behind_interactive_calls_by_default(self):
        spec = importlib.util.spec_from_file_location('model_gateway', MODULE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertLess(mod.request_priority('api/chat', None), mod.request_priority('api/embed', None))
        self.assertEqual(mod.request_priority('api/embed', '0'), 0)
        with self.assertRaises(ValueError): mod.request_priority('api/chat', 'invalid')

    async def test_queue_rejects_overload_without_losing_lock(self):""")
p.write_text(s,encoding='utf-8')
