import asyncio
import json
import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("RedisUrl", "redis://localhost:6379/0")

try:
    import redis.asyncio
except ModuleNotFoundError:
    redis_package = types.ModuleType("redis")
    redis_asyncio = types.ModuleType("redis.asyncio")
    redis_exceptions = types.ModuleType("redis.exceptions")

    class RedisError(Exception):
        pass

    redis_asyncio.from_url = lambda *args, **kwargs: None
    redis_asyncio.Redis = object
    redis_exceptions.RedisError = RedisError
    redis_package.asyncio = redis_asyncio
    redis_package.exceptions = redis_exceptions
    sys.modules["redis"] = redis_package
    sys.modules["redis.asyncio"] = redis_asyncio
    sys.modules["redis.exceptions"] = redis_exceptions

import main
import maintenance


class FakeHeaders:
    def __init__(self, values: dict[str, list[str]] | None = None) -> None:
        self.values = {key.lower(): list(items) for key, items in (values or {}).items()}

    def get(self, name: str, default: str | None = None) -> str | None:
        items = self.values.get(name.lower(), [])
        return items[0] if items else default

    def getlist(self, name: str) -> list[str]:
        return list(self.values.get(name.lower(), []))


class FakeRequest:
    def __init__(
        self,
        chunks: list[bytes] | None = None,
        headers: dict[str, list[str]] | None = None,
        delay_seconds: float = 0.0,
        disconnect: bool = False,
    ) -> None:
        self.headers = FakeHeaders(headers)
        self.chunks = chunks or []
        self.delay_seconds = delay_seconds
        self.disconnect = disconnect

    async def stream(self):
        for chunk in self.chunks:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            yield chunk
        if self.disconnect:
            raise main.ClientDisconnect()


class HardeningTests(unittest.TestCase):
    def config(self, api_key: str = "secret") -> SimpleNamespace:
        return SimpleNamespace(
            api_key=api_key,
            max_query_length=8192,
            max_query_fields=64,
            retry_schedule_seconds=(1.0, 5.0, 30.0, 300.0),
            retry_backoff_multiplier=2.0,
            max_retry_delay_seconds=300.0,
        )

    def test_priority_key_is_stripped(self) -> None:
        query, priority, thread_id = main.sanitize_query_string(
            "thread_id=123&ApiKey=secret&wait=true",
            self.config(),
            None,
        )
        self.assertTrue(priority)
        self.assertEqual(thread_id, "123")
        self.assertEqual(query, "thread_id=123&wait=true")

    def test_header_priority_key(self) -> None:
        query, priority, thread_id = main.sanitize_query_string(
            "thread_id=123",
            self.config(),
            "secret",
        )
        self.assertTrue(priority)
        self.assertEqual(thread_id, "123")
        self.assertEqual(query, "thread_id=123")

    def test_invalid_priority_key_is_rejected(self) -> None:
        with self.assertRaises(main.HTTPException):
            main.sanitize_query_string("ApiKey=wrong", self.config(), None)

    def test_duplicate_thread_is_rejected(self) -> None:
        with self.assertRaises(main.HTTPException):
            main.sanitize_query_string("thread_id=1&thread_id=2", self.config(), None)

    def test_thread_target_is_stable(self) -> None:
        webhook = main.webhook_key("123", "token")
        first = main.target_key(webhook, "thread_id:456")
        second = main.target_key(webhook, "thread_id:456")
        other = main.target_key(webhook, "thread_id:789")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

    def test_base_target_preserves_legacy_key(self) -> None:
        webhook = main.webhook_key("123", "token")
        self.assertEqual(main.target_key(webhook, "webhook"), webhook)

    def test_json_thread_name_isolated(self) -> None:
        body = json.dumps({"thread_name": "Announcements"}).encode()
        context = main.derive_target_context(None, "application/json", body)
        self.assertTrue(context.startswith("thread_name:"))

    def test_idempotency_fingerprint_includes_query(self) -> None:
        body = b'{"content":"hello"}'
        first = main.request_fingerprint(body, "thread_id=1", "application/json")
        second = main.request_fingerprint(body, "thread_id=2", "application/json")
        self.assertNotEqual(first, second)

    def test_retry_schedule_and_jitter_bounds(self) -> None:
        config = self.config()
        with patch("main.secrets.randbelow", side_effect=[0, 249999]):
            minimum = main.retry_delay_seconds(1, config)
            maximum = main.retry_delay_seconds(1, config)
        self.assertEqual(minimum, 1.0)
        self.assertEqual(maximum, 1.249999)

    def test_queue_entry_formats(self) -> None:
        self.assertEqual(main.parse_queue_entry("abc"), ("abc", 0, ""))
        self.assertEqual(main.parse_queue_entry("abc|2048|def"), ("abc", 2048, "def"))

    def test_storage_charge_has_overhead(self) -> None:
        charge = main.estimated_storage_bytes("YWJj", "wait=true", "application/json", "token", 2048)
        self.assertEqual(charge, 2048 + 4 + 9 + 16 + 5)

    def test_content_type_control_character_rejected(self) -> None:
        with self.assertRaises(main.HTTPException):
            main.validate_content_type("application/json\x00", 200)

    def test_nonfinite_environment_float_falls_back(self) -> None:
        with patch.dict(os.environ, {"TEST_FLOAT": "nan"}):
            self.assertEqual(main.get_float_env("TEST_FLOAT", 3.5), 3.5)
        with patch.dict(os.environ, {"TEST_FLOAT": "inf"}):
            self.assertEqual(main.get_float_env("TEST_FLOAT", 3.5), 3.5)

    def test_nonfinite_upstream_delay_rejected(self) -> None:
        self.assertIsNone(main.finite_nonnegative_float("nan"))
        self.assertIsNone(main.finite_nonnegative_float("inf"))
        self.assertEqual(main.finite_nonnegative_float("-1"), 0.0)
        self.assertEqual(main.finite_nonnegative_float("999999"), 86400.0)

    def test_queue_prefix_validation(self) -> None:
        self.assertEqual(main.validate_queue_prefix("proxy:v1"), "proxy:v1")
        with self.assertRaises(RuntimeError):
            main.validate_queue_prefix("proxy*")

    def test_claim_script_repairs_persistent_backoff(self) -> None:
        self.assertIn("if global_backoff_ms == -1 then", main.CLAIM_NEXT_JOB_LUA)
        self.assertIn("redis.call('ZADD', ready_key, now_ms + contention_delay_ms, target_key)", main.CLAIM_NEXT_JOB_LUA)

    def test_rate_limit_checks_block_before_global_increment(self) -> None:
        block_position = main.RATE_LIMIT_LUA.index("local block_ttl")
        global_position = main.RATE_LIMIT_LUA.index("local global_count")
        self.assertLess(block_position, global_position)

    def test_deadletter_does_not_retain_webhook_token(self) -> None:
        source = Path(main.__file__).read_text(encoding="utf-8")
        fields_section = source[source.index('fields = {', source.index("async def push_deadletter")):source.index('storage_bytes = (', source.index("async def push_deadletter"))]
        self.assertNotIn('"webhook_token":', fields_section)


    def test_sensitive_webhook_urls_are_redacted(self) -> None:
        value = "delivery failed for https://discord.com/api/webhooks/123456/secret_TOKEN-123"
        redacted = main.redact_sensitive_text(value)
        self.assertNotIn("secret_TOKEN-123", redacted)
        self.assertIn("[redacted-webhook-url]", redacted)

    def test_http_client_disables_environment_proxying(self) -> None:
        source = Path(main.__file__).read_text(encoding="utf-8")
        self.assertIn("trust_env=False", source)

    def test_maintenance_barrier_is_enforced_in_lua(self) -> None:
        self.assertIn("maintenance_lock_key", main.ENQUEUE_JOB_LUA)
        self.assertIn("maintenance_lock_key", main.CLAIM_NEXT_JOB_LUA)
        self.assertIn("return {'maintenance',", main.ENQUEUE_JOB_LUA)

    def test_runtime_has_no_hot_path_telemetry_calls(self) -> None:
        import ast

        source = Path(main.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_names = {"print", "warn", "warning", "error", "exception", "critical", "assert"}
        calls = []
        assertions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.append(node.func.attr)
            elif isinstance(node, ast.Assert):
                assertions.append(node)
        self.assertTrue(forbidden_names.isdisjoint(calls))
        self.assertFalse(assertions)

    def test_entrypoint_avoids_shell_execution(self) -> None:
        source = Path(__file__).with_name("entrypoint.py").read_text(encoding="utf-8")
        self.assertIn("os.execv(", source)
        self.assertNotIn("sh -c", source)
        self.assertNotIn("shell=True", source)

    def test_docker_runtime_disables_fault_handler_telemetry(self) -> None:
        source = Path(__file__).with_name("Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("PYTHONFAULTHANDLER", source)
        self.assertIn('CMD ["python", "entrypoint.py"]', source)

    def test_hot_path_uses_registered_scripts(self) -> None:
        source = Path(main.__file__).read_text(encoding="utf-8")
        self.assertNotIn("self.redis.eval(", source)
        self.assertIn("self.redis.register_script(", source)


class BodyReaderTests(unittest.IsolatedAsyncioTestCase):

    async def test_byte_budget_blocks_and_recovers(self) -> None:
        budget = main.AsyncByteBudget(10)
        self.assertTrue(await budget.acquire(8, 0.1))
        self.assertFalse(await budget.acquire(3, 0.001))
        await budget.release(8)
        self.assertTrue(await budget.acquire(10, 0.1))
        self.assertEqual(budget.available, 0)

    async def test_byte_budget_clamps_oversized_reservations(self) -> None:
        budget = main.AsyncByteBudget(4)
        self.assertTrue(await budget.acquire(100, 0.1))
        self.assertEqual(budget.available, 0)
        await budget.release(100)
        self.assertEqual(budget.available, 4)

    async def test_reads_body(self) -> None:
        request = FakeRequest([b"abc", b"def"], {"content-length": ["6"]})
        self.assertEqual(await main.read_limited_body(request, 6, 1.0), b"abcdef")

    async def test_rejects_duplicate_content_length(self) -> None:
        request = FakeRequest([b"x"], {"content-length": ["1", "1"]})
        with self.assertRaises(main.HTTPException) as context:
            await main.read_limited_body(request, 10, 1.0)
        self.assertEqual(context.exception.status_code, 400)

    async def test_rejects_negative_content_length(self) -> None:
        request = FakeRequest([b"x"], {"content-length": ["-1"]})
        with self.assertRaises(main.HTTPException) as context:
            await main.read_limited_body(request, 10, 1.0)
        self.assertEqual(context.exception.status_code, 400)

    async def test_rejects_stream_over_limit(self) -> None:
        request = FakeRequest([b"abc", b"def"])
        with self.assertRaises(main.HTTPException) as context:
            await main.read_limited_body(request, 5, 1.0)
        self.assertEqual(context.exception.status_code, 413)

    async def test_times_out_slow_body(self) -> None:
        request = FakeRequest([b"x"], delay_seconds=0.05)
        with self.assertRaises(main.HTTPException) as context:
            await main.read_limited_body(request, 10, 0.001)
        self.assertEqual(context.exception.status_code, 408)

    async def test_converts_client_disconnect(self) -> None:
        request = FakeRequest([b"x"], disconnect=True)
        with self.assertRaises(main.HTTPException) as context:
            await main.read_limited_body(request, 10, 1.0)
        self.assertEqual(context.exception.status_code, 499)


class FakeAuditRedis:
    def __init__(self) -> None:
        self.values = {
            "proxy:pending:jobs": "1",
            "proxy:pending:bytes": "100",
            "proxy:deadletter:bytes": "42",
        }
        self.sorted_sizes = {
            "proxy:idempotency:index": 2,
            "proxy:processing:jobs": 0,
            "proxy:ready:webhooks": 1,
        }

    async def scan_iter(self, match: str, count: int):
        for key in (
            "proxy:webhook-queue:target",
            "proxy:job:job1",
            "proxy:deadletter:index",
            "proxy:deadletter:bytes",
            "proxy:deadletter:job2",
            "proxy:stats",
        ):
            yield key

    async def llen(self, key: str) -> int:
        return 1

    async def info(self, section: str) -> dict[str, int | float]:
        return {
            "used_memory": 1000,
            "used_memory_peak": 2000,
            "maxmemory": 0,
            "mem_fragmentation_ratio": 1.0,
        }

    async def hgetall(self, key: str) -> dict[str, str]:
        return {"accepted": "1"}

    async def dbsize(self) -> int:
        return 6

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def zcard(self, key: str) -> int:
        return self.sorted_sizes.get(key, 0)


class MaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_audit_excludes_deadletter_metadata_keys(self) -> None:
        result = await maintenance.audit(FakeAuditRedis(), "proxy", 20)
        self.assertEqual(result["deadletter_hashes"], 1)
        self.assertEqual(result["namespace_keys"], 6)
        self.assertEqual(result["queue_entries"], 1)

    async def test_maintenance_numeric_options_reject_nonfinite_values(self) -> None:
        with self.assertRaises(SystemExit):
            maintenance.finite_positive_float(float("inf"), 1.0, 10.0)
        self.assertEqual(maintenance.finite_positive_float(0.0, 1.0, 10.0), 1.0)
        self.assertEqual(maintenance.finite_positive_float(20.0, 1.0, 10.0), 10.0)

    async def test_reconcile_contains_duplicate_and_orphan_recovery(self) -> None:
        source = Path(maintenance.__file__).read_text(encoding="utf-8")
        self.assertIn("removed_duplicate_entries", source)
        self.assertIn("requeued_orphan_jobs", source)
        self.assertIn("seen_job_ids", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
