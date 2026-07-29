import json
import os
import sys
import types
from types import SimpleNamespace

import httpx

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


def require(condition: bool, name: str) -> None:
    if not condition:
        raise SystemExit(f"Self-test failed: {name}")


def require_http_exception(callback, name: str) -> None:
    try:
        callback()
    except main.HTTPException:
        return
    raise SystemExit(f"Self-test failed: {name}")


def config(api_key: str = "secret") -> SimpleNamespace:
    return SimpleNamespace(
        api_key=api_key,
        max_query_length=8192,
        max_query_fields=64,
        retry_schedule_seconds=(1.0, 5.0, 30.0, 300.0),
        retry_backoff_multiplier=2.0,
        max_retry_delay_seconds=300.0,
    )


def run() -> None:
    query, priority, thread_id = main.sanitize_query_string(
        "thread_id=123&ApiKey=secret&wait=true",
        config(),
        None,
    )
    require(priority, "query API key priority")
    require(thread_id == "123", "thread identifier")
    require(query == "thread_id=123&wait=true", "query API key removal")

    query, priority, thread_id = main.sanitize_query_string(
        "thread_id=123",
        config(),
        "secret",
    )
    require(priority, "header API key priority")
    require(thread_id == "123", "header API key thread")
    require(query == "thread_id=123", "header API key query")

    require_http_exception(
        lambda: main.sanitize_query_string("ApiKey=wrong", config(), None),
        "invalid priority key rejection",
    )
    require_http_exception(
        lambda: main.sanitize_query_string("thread_id=1&thread_id=2", config(), None),
        "duplicate thread rejection",
    )
    require_http_exception(
        lambda: main.validate_content_type("application/json\x00", 200),
        "content type control character rejection",
    )

    webhook = main.webhook_key("123", "token")
    first = main.target_key(webhook, "thread_id:456")
    second = main.target_key(webhook, "thread_id:456")
    other = main.target_key(webhook, "thread_id:789")
    require(first == second, "stable thread target")
    require(first != other, "isolated thread target")
    require(main.target_key(webhook, "webhook") == webhook, "base target compatibility")

    context = main.derive_target_context(
        None,
        "application/json",
        json.dumps({"thread_name": "Announcements"}).encode(),
    )
    require(context.startswith("thread_name:"), "thread name isolation")

    body = b'{"content":"hello"}'
    first_fingerprint = main.request_fingerprint(body, "thread_id=1", "application/json")
    second_fingerprint = main.request_fingerprint(body, "thread_id=2", "application/json")
    require(first_fingerprint != second_fingerprint, "query-sensitive fingerprint")

    expected = (1.0, 5.0, 30.0, 300.0)
    for attempt, minimum in enumerate(expected, 1):
        delay = main.retry_delay_seconds(attempt, config())
        require(minimum <= delay < minimum + 0.25, f"retry delay {attempt}")

    require(
        main.estimated_storage_bytes("YWJj", "wait=true", "application/json", "token", 2048)
        == 2048 + 4 + 9 + 16 + 5,
        "storage charge",
    )

    blocked = main.parse_blacklisted_webhooks(
        "https://discord.com/api/webhooks/123/token,invalid"
    )
    require(main.webhook_key("123", "token") in blocked, "blacklist parsing")
    require(len(blocked) == 1, "invalid blacklist omission")

    upstream_body = b'{"message":"Unknown Webhook","code":10015}'
    upstream = httpx.Response(
        404,
        content=upstream_body,
        headers={
            "Content-Type": "application/json",
            "X-RateLimit-Remaining": "1",
        },
    )
    result = main.upstream_delivery_result(upstream, 1, "request-1", 1024)
    require(result["status_code"] == "404", "upstream status relay")
    require(main.decode_body(result["body_b64"]) == upstream_body, "upstream body relay")
    response = main.delivery_response(result, "fallback")
    require(response.status_code == 404, "terminal response status")
    require(response.body == upstream_body, "terminal response body")
    require(response.headers["x-proxy-request-id"] == "request-1", "request identifier header")

    empty_upstream = httpx.Response(404, content=b"")
    empty_result = main.upstream_delivery_result(empty_upstream, 2, "request-2", 1024)
    empty_payload = json.loads(main.decode_body(empty_result["body_b64"]))
    require(empty_payload["code"] is None, "empty upstream code")
    require("HTTP 404" in empty_payload["message"], "empty upstream message")


if __name__ == "__main__":
    run()
