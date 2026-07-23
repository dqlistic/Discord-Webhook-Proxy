import json
import os
import sys
import types
import unittest
from types import SimpleNamespace

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
    redis_exceptions.RedisError = RedisError
    redis_package.asyncio = redis_asyncio
    redis_package.exceptions = redis_exceptions
    sys.modules["redis"] = redis_package
    sys.modules["redis.asyncio"] = redis_asyncio
    sys.modules["redis.exceptions"] = redis_exceptions

import main


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

    def test_retry_schedule(self) -> None:
        config = self.config()
        expected = (1.0, 5.0, 30.0, 300.0)
        for attempt, minimum in enumerate(expected, 1):
            delay = main.retry_delay_seconds(attempt, config)
            self.assertGreaterEqual(delay, minimum)
            self.assertLess(delay, minimum + 0.25)

    def test_queue_entry_formats(self) -> None:
        self.assertEqual(main.parse_queue_entry("abc"), ("abc", 0, ""))
        self.assertEqual(main.parse_queue_entry("abc|2048|def"), ("abc", 2048, "def"))

    def test_storage_charge_has_overhead(self) -> None:
        charge = main.estimated_storage_bytes("YWJj", "wait=true", "application/json", "token", 2048)
        self.assertEqual(charge, 2048 + 4 + 9 + 16 + 5)

    def test_content_type_control_character_rejected(self) -> None:
        with self.assertRaises(main.HTTPException):
            main.validate_content_type("application/json\x00", 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
