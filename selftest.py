import asyncio
import json
import os
import unittest
from types import SimpleNamespace

import httpx

os.environ.setdefault("RedisUrl", "redis://localhost:6379/0")

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

    def test_priority_key_is_stripped_and_discord_confirmation_is_forced(self) -> None:
        query, priority, thread_id, response_wait = main.sanitize_query_string(
            "thread_id=123&ApiKey=secret&wait=true",
            self.config(),
            None,
        )
        self.assertTrue(priority)
        self.assertTrue(response_wait)
        self.assertEqual(thread_id, "123")
        self.assertEqual(query, "thread_id=123&wait=true")

    def test_missing_wait_is_forced_upstream_but_preserves_client_semantics(self) -> None:
        query, priority, thread_id, response_wait = main.sanitize_query_string(
            "thread_id=123",
            self.config(),
            "secret",
        )
        self.assertTrue(priority)
        self.assertFalse(response_wait)
        self.assertEqual(thread_id, "123")
        self.assertEqual(query, "thread_id=123&wait=true")

    def test_false_wait_is_replaced_upstream(self) -> None:
        query, _, _, response_wait = main.sanitize_query_string(
            "wait=false&thread_id=123",
            self.config(),
            None,
        )
        self.assertFalse(response_wait)
        self.assertEqual(query, "thread_id=123&wait=true")

    def test_duplicate_or_invalid_wait_is_rejected(self) -> None:
        with self.assertRaises(main.HTTPException):
            main.sanitize_query_string("wait=true&wait=false", self.config(), None)
        with self.assertRaises(main.HTTPException):
            main.sanitize_query_string("wait=sometimes", self.config(), None)

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

    def test_nonfinite_retry_headers_are_ignored(self) -> None:
        response = httpx.Response(
            429,
            content=b'{"retry_after":NaN}',
            headers={
                "Retry-After": "Infinity",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset-After": "NaN",
            },
        )
        self.assertEqual(main.get_retry_after_seconds(response), 1.0)
        self.assertIsNone(main.get_bucket_reset_after_seconds(response))

    def test_storage_charge_has_overhead(self) -> None:
        charge = main.estimated_storage_bytes("YWJj", "wait=true", "application/json", "token", 2048)
        self.assertEqual(charge, 2048 + 4 + 9 + 16 + 5)

    def test_content_type_control_character_rejected(self) -> None:
        with self.assertRaises(main.HTTPException):
            main.validate_content_type("application/json\x00", 200)
        with self.assertRaises(main.HTTPException):
            main.validate_content_type("application/☃", 200)

    def test_json_payload_rejects_non_objects_and_nonfinite_numbers(self) -> None:
        self.assertEqual(main.parse_json_object(b'{"content":"hello"}'), {"content": "hello"})
        for body in (b"[]", b'"text"', b'{"value":NaN}', b'{"value":Infinity}'):
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    main.parse_json_object(body)

    def test_invalid_blacklist_configuration_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            main.parse_blacklisted_webhooks("not-a-webhook")

    def test_terminal_discord_error_is_returned_verbatim(self) -> None:
        upstream = httpx.Response(
            404,
            json={"message": "Unknown Webhook", "code": 10015},
            headers={"Content-Type": "application/json"},
        )
        result = main.delivery_result_from_response(upstream, "discarded", 262144, 1)
        response = main.delivery_result_response(result, "request", False, False, "webhook", False)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.body), {"message": "Unknown Webhook", "code": 10015})
        self.assertEqual(response.headers["x-proxy-delivery-state"], "discarded")

    def test_no_wait_success_returns_confirmed_no_content(self) -> None:
        upstream = httpx.Response(
            200,
            json={"id": "123"},
            headers={"Content-Type": "application/json"},
        )
        result = main.delivery_result_from_response(
            upstream,
            "delivered",
            262144,
            1,
            include_body=False,
        )
        response = main.delivery_result_response(result, "request", False, False, "webhook", False)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.body, b"")

    def test_retry_result_is_truthful_accepted_response(self) -> None:
        upstream = httpx.Response(
            429,
            json={"message": "You are being rate limited.", "retry_after": 2.5},
            headers={"Content-Type": "application/json", "Retry-After": "2.5"},
        )
        result = main.delivery_result_from_response(
            upstream,
            "retrying",
            262144,
            1,
            main.now_ms() + 2500,
        )
        response = main.delivery_result_response(result, "request", False, False, "webhook", False)
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(payload["delivery_status"], "retrying")
        self.assertEqual(payload["upstream_status"], 429)
        self.assertEqual(payload["upstream_response"]["retry_after"], 2.5)

    def test_claim_scripts_require_current_fencing_metadata(self) -> None:
        self.assertIn("not current_meta", main.FINALIZE_JOB_LUA)
        self.assertIn("if not meta then", main.RESCHEDULE_JOB_LUA)


class StubHTTPClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.called = False

    async def post(self, url: str, content: bytes, headers: dict[str, str]) -> httpx.Response:
        self.called = True
        return self.response


class RaisingHTTPClient:
    def __init__(self, exception: Exception) -> None:
        self.exception = exception
        self.called = False

    async def post(self, url: str, content: bytes, headers: dict[str, str]) -> httpx.Response:
        self.called = True
        raise self.exception


class CapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_byte_budget_rejects_then_recovers_capacity(self) -> None:
        budget = main.AsyncByteBudget(10)
        first = await budget.acquire(7, 0.01)
        blocked = await budget.acquire(5, 0.001)
        await budget.release(first)
        recovered = await budget.acquire(5, 0.01)
        self.assertEqual(first, 7)
        self.assertEqual(blocked, 0)
        self.assertEqual(recovered, 5)

    async def test_slow_request_body_has_total_deadline(self) -> None:
        async def receive() -> dict:
            await asyncio.sleep(0.05)
            return {"type": "http.request", "body": b"x", "more_body": False}

        request = main.Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "https",
                "path": "/",
                "raw_path": b"/",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("test", 443),
                "http_version": "1.1",
            },
            receive,
        )
        with self.assertRaises(main.HTTPException) as captured:
            await main.read_limited_body(request, 1024, 0.001)
        self.assertEqual(captured.exception.status_code, 408)


class WorkerBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def state(self, response: httpx.Response, blacklisted: set[str] | None = None) -> tuple[main.AppState, dict]:
        state = object.__new__(main.AppState)
        state.config = SimpleNamespace(
            blacklisted_webhook_keys=blacklisted or set(),
            delivery_result_max_body_bytes=262144,
            max_retries=4,
            retry_schedule_seconds=(1.0, 5.0, 30.0, 300.0),
            retry_backoff_multiplier=2.0,
            max_retry_delay_seconds=300.0,
            max_content_type_length=200,
            max_query_length=8192,
            http_timeout_seconds=20.0,
            job_ttl_seconds=3600,
        )
        state.http_client = StubHTTPClient(response)
        captured: dict = {"finalized": [], "stats": [], "rescheduled": []}

        async def finalize(*args, **kwargs):
            captured["finalized"].append((args, kwargs))
            return "finalized"

        async def increment(field: str, amount: int = 1):
            captured["stats"].append((field, amount))

        async def record_invalid():
            captured["invalid_recorded"] = True

        async def set_backoff(*args):
            captured.setdefault("backoffs", []).append(args)

        async def reschedule(**kwargs):
            captured["rescheduled"].append(kwargs)
            return "rescheduled"

        state.finalize_job = finalize
        state.increment_stat = increment
        state.record_invalid_request = record_invalid
        state.set_webhook_backoff = set_backoff
        state.set_global_backoff = set_backoff
        state.reschedule_job = reschedule
        return state, captured

    def job(self, response_wait: str = "0") -> dict[str, str]:
        webhook_key_value = main.webhook_key("123", "token")
        body = b'{"content":"hello"}'
        query_string = "wait=true"
        content_type = "application/json"
        created_at_ms = main.now_ms()
        return {
            "job_id": "job",
            "webhook_id": "123",
            "webhook_token": "token",
            "webhook_key": webhook_key_value,
            "body_b64": main.encode_body(body),
            "body_sha256": main.sha256_bytes(body),
            "request_sha256": main.request_fingerprint(body, query_string, content_type),
            "content_type": content_type,
            "query_string": query_string,
            "created_at_ms": str(created_at_ms),
            "expires_at_ms": str(created_at_ms + 3_600_000),
            "attempts": "0",
            "response_wait": response_wait,
        }

    async def test_worker_discards_and_surfaces_unknown_webhook(self) -> None:
        upstream = httpx.Response(
            404,
            json={"message": "Unknown Webhook", "code": 10015},
            headers={"Content-Type": "application/json"},
        )
        state, captured = self.state(upstream)
        webhook_key_value = main.webhook_key("123", "token")
        await main.AppState.process_job(state, "job", self.job(), "target", "entry", webhook_key_value, "claim")
        self.assertEqual(len(captured["finalized"]), 1)
        result = captured["finalized"][0][1]["delivery_result"]
        self.assertEqual(result["delivery_state"], "discarded")
        self.assertEqual(result["http_status"], "404")
        self.assertIn(("discarded", 1), captured["stats"])
        self.assertEqual(captured["rescheduled"], [])

    async def test_worker_surfaces_permanent_discord_statuses(self) -> None:
        webhook_key_value = main.webhook_key("123", "token")
        for status_code in (400, 401, 403, 404, 418):
            with self.subTest(status_code=status_code):
                upstream = httpx.Response(
                    status_code,
                    json={"message": f"Discord {status_code}", "code": status_code},
                    headers={"Content-Type": "application/json"},
                )
                state, captured = self.state(upstream)
                await main.AppState.process_job(
                    state,
                    "job",
                    self.job(),
                    "target",
                    "entry",
                    webhook_key_value,
                    "claim",
                )
                result = captured["finalized"][0][1]["delivery_result"]
                response = main.delivery_result_response(
                    result,
                    "request",
                    False,
                    False,
                    "webhook",
                    False,
                )
                self.assertEqual(response.status_code, status_code)
                self.assertEqual(json.loads(response.body)["code"], status_code)
                self.assertEqual(captured["rescheduled"], [])

    async def test_worker_retries_transient_discord_statuses(self) -> None:
        webhook_key_value = main.webhook_key("123", "token")
        for status_code in (408, 409, 425, 500, 502, 503):
            with self.subTest(status_code=status_code):
                upstream = httpx.Response(
                    status_code,
                    json={"message": f"Discord {status_code}"},
                    headers={"Content-Type": "application/json"},
                )
                state, captured = self.state(upstream)
                await main.AppState.process_job(
                    state,
                    "job",
                    self.job(),
                    "target",
                    "entry",
                    webhook_key_value,
                    "claim",
                )
                self.assertEqual(captured["finalized"], [])
                self.assertEqual(len(captured["rescheduled"]), 1)
                self.assertEqual(
                    captured["rescheduled"][0]["delivery_result"]["upstream_status"],
                    str(status_code),
                )

    async def test_worker_keeps_rate_limited_job_and_publishes_retry_state(self) -> None:
        upstream = httpx.Response(
            429,
            json={"message": "You are being rate limited.", "retry_after": 2},
            headers={"Content-Type": "application/json", "Retry-After": "2"},
        )
        state, captured = self.state(upstream)
        webhook_key_value = main.webhook_key("123", "token")
        await main.AppState.process_job(state, "job", self.job(), "target", "entry", webhook_key_value, "claim")
        self.assertEqual(captured["finalized"], [])
        self.assertEqual(len(captured["rescheduled"]), 1)
        result = captured["rescheduled"][0]["delivery_result"]
        self.assertEqual(result["delivery_state"], "retrying")
        self.assertEqual(result["upstream_status"], "429")
        self.assertTrue(captured["invalid_recorded"])

    async def test_rate_limits_do_not_consume_permanent_failure_budget(self) -> None:
        upstream = httpx.Response(
            429,
            json={"message": "You are being rate limited.", "retry_after": 2},
            headers={"Content-Type": "application/json", "Retry-After": "2"},
        )
        state, captured = self.state(upstream)
        job = self.job()
        job["attempts"] = str(state.config.max_retries)
        webhook_key_value = main.webhook_key("123", "token")
        await main.AppState.process_job(
            state,
            "job",
            job,
            "target",
            "entry",
            webhook_key_value,
            "claim",
        )
        self.assertEqual(captured["finalized"], [])
        self.assertEqual(captured["rescheduled"][0]["attempts"], state.config.max_retries + 1)

    async def test_worker_discards_corrupt_stored_payload_without_network(self) -> None:
        upstream = httpx.Response(204)
        state, captured = self.state(upstream)
        job = self.job()
        job["body_b64"] = "not-base64"
        webhook_key_value = main.webhook_key("123", "token")
        await main.AppState.process_job(state, "job", job, "target", "entry", webhook_key_value, "claim")
        self.assertFalse(state.http_client.called)
        self.assertEqual(len(captured["finalized"]), 1)
        result = captured["finalized"][0][1]["delivery_result"]
        self.assertEqual(result["delivery_state"], "discarded")
        self.assertEqual(result["http_status"], "500")

    async def test_worker_rechecks_blacklist_before_network(self) -> None:
        upstream = httpx.Response(204)
        webhook_key_value = main.webhook_key("123", "token")
        state, captured = self.state(upstream, {webhook_key_value})
        await main.AppState.process_job(state, "job", self.job(), "target", "entry", webhook_key_value, "claim")
        self.assertFalse(state.http_client.called)
        self.assertEqual(len(captured["finalized"]), 1)
        self.assertNotIn("delivery_result", captured["finalized"][0][1])

    async def test_worker_discards_corrupt_webhook_identity_without_network(self) -> None:
        upstream = httpx.Response(204)
        state, captured = self.state(upstream)
        job = self.job()
        job["webhook_token"] = "../channels"
        webhook_key_value = main.webhook_key("123", "token")
        await main.AppState.process_job(state, "job", job, "target", "entry", webhook_key_value, "claim")
        self.assertFalse(state.http_client.called)
        result = captured["finalized"][0][1]["delivery_result"]
        self.assertEqual(result["result_code"], "invalid_stored_payload")

    async def test_worker_discards_expired_payload_without_network(self) -> None:
        state, captured = self.state(httpx.Response(204))
        job = self.job()
        job["expires_at_ms"] = str(main.now_ms() - 1)
        job["created_at_ms"] = str(main.now_ms() - 3_600_000)
        webhook_key_value = main.webhook_key("123", "token")
        await main.AppState.process_job(
            state,
            "job",
            job,
            "target",
            "entry",
            webhook_key_value,
            "claim",
        )
        self.assertFalse(state.http_client.called)
        result = captured["finalized"][0][1]["delivery_result"]
        self.assertEqual(result["result_code"], "delivery_deadline_reached")

    async def test_worker_retries_timeout_and_network_failures(self) -> None:
        webhook_key_value = main.webhook_key("123", "token")
        request = httpx.Request("POST", "https://discord.com")
        for exception, expected_status in (
            (httpx.ReadTimeout("timed out", request=request), "504"),
            (httpx.ConnectError("unavailable", request=request), "502"),
        ):
            with self.subTest(exception=type(exception).__name__):
                state, captured = self.state(httpx.Response(204))
                state.http_client = RaisingHTTPClient(exception)
                await main.AppState.process_job(
                    state,
                    "job",
                    self.job(),
                    "target",
                    "entry",
                    webhook_key_value,
                    "claim",
                )
                self.assertEqual(len(captured["rescheduled"]), 1)
                result = captured["rescheduled"][0]["delivery_result"]
                self.assertEqual(result["delivery_state"], "retrying")
                self.assertEqual(result["http_status"], expected_status)

    async def test_worker_normalizes_unexpected_informational_and_redirect_statuses(self) -> None:
        webhook_key_value = main.webhook_key("123", "token")
        for status_code in (103, 302):
            with self.subTest(status_code=status_code):
                state, captured = self.state(httpx.Response(status_code))
                await main.AppState.process_job(
                    state,
                    "job",
                    self.job(),
                    "target",
                    "entry",
                    webhook_key_value,
                    "claim",
                )
                result = captured["finalized"][0][1]["delivery_result"]
                self.assertEqual(result["http_status"], "502")
                self.assertEqual(result["upstream_status"], str(status_code))
                self.assertEqual(result["result_code"], "unexpected_upstream_status")

    async def test_stale_finalize_does_not_increment_delivery_counters(self) -> None:
        webhook_key_value = main.webhook_key("123", "token")
        state, captured = self.state(httpx.Response(204))

        async def stale_finalize(*args, **kwargs):
            captured["finalized"].append((args, kwargs))
            return "stale"

        state.finalize_job = stale_finalize
        await main.AppState.process_job(
            state,
            "job",
            self.job(),
            "target",
            "entry",
            webhook_key_value,
            "claim",
        )
        self.assertNotIn(("sent", 1), captured["stats"])


class SurfaceBlacklistTests(unittest.IsolatedAsyncioTestCase):
    async def test_blacklist_precedes_saturated_ingress_and_redis(self) -> None:
        webhook_id = "123"
        webhook_token = "sample"
        blocked_key = main.webhook_key(webhook_id, webhook_token)
        fake_state = SimpleNamespace(
            config=SimpleNamespace(
                blacklisted_webhook_keys={blocked_key},
                ingress_wait_seconds=0.001,
            ),
            ingress_slots=asyncio.Semaphore(0),
        )
        main.app.state.state = fake_state
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://proxy.example") as client:
            response = await client.post(
                f"/api/webhooks/{webhook_id}/{webhook_token}",
                content=b'{"content":"must not be read"}',
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "webhook_blocked")
        self.assertEqual(fake_state.ingress_slots._value, 0)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    async def test_blacklist_rejects_trailing_slash_before_ingress(self) -> None:
        webhook_id = "123"
        webhook_token = "sample"
        blocked_key = main.webhook_key(webhook_id, webhook_token)
        fake_state = SimpleNamespace(
            config=SimpleNamespace(
                blacklisted_webhook_keys={blocked_key},
                ingress_wait_seconds=0.001,
            ),
            ingress_slots=asyncio.Semaphore(0),
        )
        main.app.state.state = fake_state
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://proxy.example") as client:
            response = await client.post(
                f"/api/webhooks/{webhook_id}/{webhook_token}/",
                content=b'{"content":"must not be read"}',
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(fake_state.ingress_slots._value, 0)


class ProxyRouteTests(unittest.IsolatedAsyncioTestCase):
    def state(
        self,
        result: dict[str, str] | None,
        capture_result: bool,
    ) -> SimpleNamespace:
        config = SimpleNamespace(
            blacklisted_webhook_keys=set(),
            ingress_wait_seconds=0.01,
            max_body_bytes=1024 * 1024,
            storage_overhead_bytes=2048,
            body_read_timeout_seconds=1.0,
            max_query_length=8192,
            max_query_fields=64,
            api_key="",
            max_idempotency_key_length=128,
            max_content_type_length=200,
            overload_retry_after_seconds=60,
        )
        state = SimpleNamespace(
            config=config,
            ingress_slots=asyncio.Semaphore(1),
            ingress_memory=main.AsyncByteBudget(4 * 1024 * 1024),
            released_waiters=0,
        )

        async def increment_stat(field: str, amount: int = 1) -> None:
            return None

        async def check_rate_limit(subject_key: str) -> dict:
            return {
                "allowed": True,
                "retry_after": 0,
                "blocked": False,
                "count": 1,
                "limit": 120,
            }

        async def preflight_admission(*args, **kwargs) -> None:
            return None

        async def reserve_response_wait() -> bool:
            return capture_result

        async def enqueue_job(**kwargs) -> dict:
            return {
                "status": "accepted",
                "request_id": "request",
                "duplicate": False,
                "job_id": "job",
                "storage_bytes": 2048,
                "cached_result": None,
            }

        async def wait_for_delivery_result(job_id: str) -> dict[str, str] | None:
            return result

        async def finish_response_wait(job_id: str) -> None:
            return None

        def release_response_wait() -> None:
            state.released_waiters += 1

        state.increment_stat = increment_stat
        state.check_rate_limit = check_rate_limit
        state.preflight_admission = preflight_admission
        state.reserve_response_wait = reserve_response_wait
        state.enqueue_job = enqueue_job
        state.wait_for_delivery_result = wait_for_delivery_result
        state.finish_response_wait = finish_response_wait
        state.release_response_wait = release_response_wait
        return state

    async def test_route_surfaces_terminal_discord_error(self) -> None:
        upstream = httpx.Response(
            404,
            json={"message": "Unknown Webhook", "code": 10015},
            headers={"Content-Type": "application/json"},
        )
        result = main.delivery_result_from_response(upstream, "discarded", 262144, 1)
        fake_state = self.state(result, True)
        main.app.state.state = fake_state
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://proxy.example") as client:
            response = await client.post(
                "/api/webhooks/123/sample",
                json={"content": "hello"},
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 10015)
        self.assertEqual(response.headers["x-proxy-delivery-state"], "discarded")
        self.assertEqual(fake_state.ingress_slots._value, 1)
        self.assertEqual(fake_state.released_waiters, 1)

    async def test_route_labels_unobserved_delivery_as_pending(self) -> None:
        fake_state = self.state(None, False)
        main.app.state.state = fake_state
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://proxy.example") as client:
            response = await client.post(
                "/api/webhooks/123/sample",
                json={"content": "hello"},
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["delivery_status"], "delivery_outcome_pending")
        self.assertIn("not confirmed", response.json()["message"])
        self.assertEqual(response.headers["x-proxy-delivery-state"], "delivery_outcome_pending")
        self.assertEqual(fake_state.ingress_slots._value, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
