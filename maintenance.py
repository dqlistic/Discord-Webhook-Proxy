import argparse
import asyncio
import json
import math
import os
import re
import secrets
import sys
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis

LOCK_RENEW_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

LOCK_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

LOCK_TTL_MS = 30000


def validate_prefix(value: str) -> str:
    prefix = value.strip()
    if not prefix or len(prefix) > 64 or re.fullmatch(r"[A-Za-z0-9_.:-]+", prefix) is None:
        raise SystemExit("Queue prefix must contain only letters, digits, periods, underscores, colons, or hyphens.")
    return prefix


def finite_positive_float(value: float, minimum: float, maximum: float) -> float:
    if not math.isfinite(value):
        raise SystemExit("Numeric maintenance options must be finite.")
    return min(maximum, max(minimum, value))


def maintenance_lock_key(prefix: str) -> str:
    return f"{prefix}:control:maintenance"


def ensure_lock_active(lost_event: asyncio.Event) -> None:
    if lost_event.is_set():
        raise RuntimeError("Maintenance lock was lost during the operation.")


async def renew_maintenance_lock(
    client: redis.Redis,
    key: str,
    token: str,
    stop_event: asyncio.Event,
    lost_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=LOCK_TTL_MS / 3000)
            return
        except TimeoutError:
            pass
        try:
            renewed = await client.eval(LOCK_RENEW_LUA, 1, key, token, str(LOCK_TTL_MS))
        except Exception:
            lost_event.set()
            return
        if int(renewed or 0) != 1:
            lost_event.set()
            return


async def wait_for_processing_drain(
    client: redis.Redis,
    prefix: str,
    timeout_seconds: float,
    lost_event: asyncio.Event,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while int(await client.zcard(f"{prefix}:processing:jobs")) > 0:
        if lost_event.is_set():
            raise RuntimeError("Maintenance lock was lost while waiting for in-flight jobs.")
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError("Timed out waiting for in-flight jobs to drain.")
        await asyncio.sleep(0.1)


@asynccontextmanager
async def maintenance_barrier(client: redis.Redis, prefix: str, drain_timeout_seconds: float):
    key = maintenance_lock_key(prefix)
    token = secrets.token_hex(32)
    acquired = await client.set(key, token, nx=True, px=LOCK_TTL_MS)
    if not acquired:
        raise RuntimeError("Another maintenance operation is already active.")
    stop_event = asyncio.Event()
    lost_event = asyncio.Event()
    renewal_task = asyncio.create_task(
        renew_maintenance_lock(client, key, token, stop_event, lost_event),
        name="maintenance-lock-renewal",
    )
    try:
        await wait_for_processing_drain(client, prefix, drain_timeout_seconds, lost_event)
        if lost_event.is_set():
            raise RuntimeError("Maintenance lock was lost before the operation started.")
        yield key, lost_event
        ensure_lock_active(lost_event)
    finally:
        stop_event.set()
        renewal_task.cancel()
        await asyncio.gather(renewal_task, return_exceptions=True)
        try:
            await client.eval(LOCK_RELEASE_LUA, 1, key, token)
        except Exception:
            pass


def env_value(name: str, default: str = "", legacy_names: tuple[str, ...] = ()) -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    for legacy_name in legacy_names:
        legacy_value = os.getenv(legacy_name)
        if legacy_value is not None:
            return legacy_value
    return default


def output(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def parse_queue_entry(entry: str) -> tuple[str, int, str]:
    parts = entry.split("|", 2)
    if len(parts) == 1:
        return parts[0], 0, ""
    try:
        charge = int(parts[1])
    except ValueError:
        charge = 0
    webhook_key = parts[2] if len(parts) == 3 else ""
    return parts[0], max(charge, 0), webhook_key


def estimate_storage(job: dict[str, str]) -> int:
    stored = job.get("storage_bytes", "")
    try:
        value = int(stored)
        if value > 0:
            return value
    except ValueError:
        pass
    return (
        len(job.get("body_b64", ""))
        + len(job.get("query_string", ""))
        + len(job.get("content_type", ""))
        + len(job.get("webhook_token", ""))
        + 768
    )


async def delete_keys(client: redis.Redis, keys: list[str]) -> int:
    deleted = 0
    for offset in range(0, len(keys), 500):
        batch = keys[offset : offset + 500]
        if batch:
            deleted += int(await client.unlink(*batch))
    return deleted


async def audit(client: redis.Redis, prefix: str, top: int) -> dict[str, Any]:
    queue_prefix = f"{prefix}:webhook-queue:"
    job_prefix = f"{prefix}:job:"
    deadletter_prefix = f"{prefix}:deadletter:"
    deadletter_index_key = f"{prefix}:deadletter:index"
    deadletter_bytes_key = f"{prefix}:deadletter:bytes"
    queue_count = 0
    job_count = 0
    deadletter_count = 0
    namespace_keys = 0
    queue_entries = 0
    top_queues: list[tuple[int, str]] = []

    async for key in client.scan_iter(match=f"{prefix}:*", count=1000):
        namespace_keys += 1
        if key.startswith(queue_prefix):
            queue_count += 1
            length = int(await client.llen(key))
            queue_entries += length
            top_queues.append((length, key[len(queue_prefix) :]))
        elif key.startswith(job_prefix):
            job_count += 1
        elif key.startswith(deadletter_prefix) and key not in {deadletter_index_key, deadletter_bytes_key}:
            deadletter_count += 1

    top_queues.sort(reverse=True)
    memory = await client.info("memory")
    stats = await client.hgetall(f"{prefix}:stats")
    return {
        "database_keys": int(await client.dbsize()),
        "namespace_keys": namespace_keys,
        "deadletter_bytes_counter": int(await client.get(deadletter_bytes_key) or 0),
        "deadletter_hashes": deadletter_count,
        "idempotency_index_entries": int(await client.zcard(f"{prefix}:idempotency:index")),
        "jobs": job_count,
        "memory": {
            "used_memory": int(memory.get("used_memory", 0)),
            "used_memory_peak": int(memory.get("used_memory_peak", 0)),
            "maxmemory": int(memory.get("maxmemory", 0)),
            "mem_fragmentation_ratio": float(memory.get("mem_fragmentation_ratio", 0.0)),
        },
        "pending_bytes_counter": int(await client.get(f"{prefix}:pending:bytes") or 0),
        "pending_jobs_counter": int(await client.get(f"{prefix}:pending:jobs") or 0),
        "processing_jobs": int(await client.zcard(f"{prefix}:processing:jobs")),
        "queue_entries": queue_entries,
        "queues": queue_count,
        "ready_targets": int(await client.zcard(f"{prefix}:ready:webhooks")),
        "stats": stats,
        "top_queues": [
            {"target_key": target_key, "length": length}
            for length, target_key in top_queues[:top]
        ],
    }


def nonnegative_integer(value: str | None, default: int = 0) -> int:
    try:
        return max(0, int(value or default))
    except (TypeError, ValueError):
        return max(0, default)


async def reconcile(client: redis.Redis, prefix: str, lost_event: asyncio.Event) -> dict[str, Any]:
    queue_prefix = f"{prefix}:webhook-queue:"
    job_prefix = f"{prefix}:job:"
    webhook_job_prefix = f"{prefix}:pending:webhook-jobs:"
    webhook_bytes_prefix = f"{prefix}:pending:webhook-bytes:"
    target_bytes_prefix = f"{prefix}:pending:target-bytes:"
    webhook_jobs: defaultdict[str, int] = defaultdict(int)
    webhook_bytes: defaultdict[str, int] = defaultdict(int)
    target_bytes: defaultdict[str, int] = defaultdict(int)
    seen_job_ids: set[str] = set()
    total_jobs = 0
    total_bytes = 0
    migrated_entries = 0
    removed_stale_entries = 0
    removed_duplicate_entries = 0
    repaired_jobs = 0
    requeued_orphan_jobs = 0
    removed_invalid_orphan_jobs = 0
    nonempty_targets: dict[str, int] = {}
    old_ready_targets = set(await client.zrange(f"{prefix}:ready:webhooks", 0, -1))

    async for queue_key in client.scan_iter(match=f"{queue_prefix}*", count=200):
        ensure_lock_active(lost_event)
        target_key = queue_key[len(queue_prefix) :]
        length = int(await client.llen(queue_key))
        stale_entries: list[tuple[str, bool]] = []
        index = 0
        while index < length:
            ensure_lock_active(lost_event)
            entries = await client.lrange(queue_key, index, min(index + 499, length - 1))
            if not entries:
                break
            for relative_index, entry in enumerate(entries):
                absolute_index = index + relative_index
                job_id, charge, entry_webhook_key = parse_queue_entry(entry)
                if not job_id:
                    stale_entries.append((entry, False))
                    continue
                if job_id in seen_job_ids:
                    stale_entries.append((entry, True))
                    continue

                job_key = f"{job_prefix}{job_id}"
                job = await client.hgetall(job_key)
                if not job:
                    stale_entries.append((entry, False))
                    continue

                webhook_key = job.get("webhook_key", entry_webhook_key)
                if not webhook_key:
                    stale_entries.append((entry, False))
                    await client.unlink(job_key)
                    continue

                charge = charge or estimate_storage(job)
                canonical_entry = f"{job_id}|{charge}|{webhook_key}"
                mapping: dict[str, str] = {}
                if entry != canonical_entry:
                    await client.lset(queue_key, absolute_index, canonical_entry)
                    migrated_entries += 1
                if job.get("queue_entry") != canonical_entry:
                    mapping["queue_entry"] = canonical_entry
                if job.get("target_key") != target_key:
                    mapping["target_key"] = target_key
                if job.get("storage_bytes") != str(charge):
                    mapping["storage_bytes"] = str(charge)
                if mapping:
                    await client.hset(job_key, mapping=mapping)
                    repaired_jobs += 1

                seen_job_ids.add(job_id)
                total_jobs += 1
                total_bytes += charge
                webhook_jobs[webhook_key] += 1
                webhook_bytes[webhook_key] += charge
                target_bytes[target_key] += charge
            index += len(entries)

        for stale_entry, duplicate in stale_entries:
            removed = int(await client.lrem(queue_key, 1, stale_entry))
            removed_stale_entries += removed
            if duplicate:
                removed_duplicate_entries += removed

        current_length = int(await client.llen(queue_key))
        if current_length == 0:
            await client.unlink(queue_key, f"{target_bytes_prefix}{target_key}")
            await client.zrem(f"{prefix}:ready:webhooks", target_key)
            continue

        head_entry = await client.lindex(queue_key, 0)
        if head_entry:
            head_job_id, _, _ = parse_queue_entry(head_entry)
            available_at = await client.hget(f"{job_prefix}{head_job_id}", "available_at_ms")
            nonempty_targets[target_key] = nonnegative_integer(available_at)

    async for job_key in client.scan_iter(match=f"{job_prefix}*", count=500):
        ensure_lock_active(lost_event)
        job_id = job_key[len(job_prefix) :]
        if not job_id or job_id in seen_job_ids:
            continue
        job = await client.hgetall(job_key)
        webhook_key = job.get("webhook_key", "")
        target_key = job.get("target_key", "")
        if not webhook_key or not target_key:
            removed_invalid_orphan_jobs += int(await client.unlink(job_key))
            continue
        charge = estimate_storage(job)
        canonical_entry = f"{job_id}|{charge}|{webhook_key}"
        await client.hset(
            job_key,
            mapping={
                "queue_entry": canonical_entry,
                "storage_bytes": str(charge),
            },
        )
        queue_key = f"{queue_prefix}{target_key}"
        queue_was_empty = int(await client.llen(queue_key)) == 0
        await client.rpush(queue_key, canonical_entry)
        await client.persist(queue_key)
        seen_job_ids.add(job_id)
        total_jobs += 1
        total_bytes += charge
        webhook_jobs[webhook_key] += 1
        webhook_bytes[webhook_key] += charge
        target_bytes[target_key] += charge
        if queue_was_empty or target_key not in nonempty_targets:
            nonempty_targets[target_key] = nonnegative_integer(job.get("available_at_ms"))
        requeued_orphan_jobs += 1

    ensure_lock_active(lost_event)
    stale_counter_keys: list[str] = []
    for pattern in (
        f"{webhook_job_prefix}*",
        f"{webhook_bytes_prefix}*",
        f"{target_bytes_prefix}*",
    ):
        async for key in client.scan_iter(match=pattern, count=1000):
            ensure_lock_active(lost_event)
            stale_counter_keys.append(key)
    await delete_keys(client, stale_counter_keys)

    ensure_lock_active(lost_event)
    runtime_keys: list[str] = []
    for pattern in (
        f"{prefix}:claim:*",
        f"{prefix}:lock:*",
        f"{prefix}:discord:webhook-lock:*",
    ):
        async for key in client.scan_iter(match=pattern, count=1000):
            ensure_lock_active(lost_event)
            runtime_keys.append(key)
    runtime_keys.append(f"{prefix}:processing:meta")
    stale_runtime_keys_removed = await delete_keys(client, runtime_keys)

    ensure_lock_active(lost_event)
    pipe = client.pipeline(transaction=True)
    pipe.set(f"{prefix}:pending:jobs", total_jobs)
    pipe.set(f"{prefix}:pending:bytes", total_bytes)
    pipe.delete(f"{prefix}:ready:webhooks")
    for webhook_key, count in webhook_jobs.items():
        pipe.set(f"{webhook_job_prefix}{webhook_key}", count)
    for webhook_key, size in webhook_bytes.items():
        pipe.set(f"{webhook_bytes_prefix}{webhook_key}", size)
    for target_key, size in target_bytes.items():
        pipe.set(f"{target_bytes_prefix}{target_key}", size)
    if nonempty_targets:
        pipe.zadd(f"{prefix}:ready:webhooks", nonempty_targets)
    await pipe.execute()
    ensure_lock_active(lost_event)

    return {
        "migrated_entries": migrated_entries,
        "pending_bytes": total_bytes,
        "pending_jobs": total_jobs,
        "removed_duplicate_entries": removed_duplicate_entries,
        "removed_invalid_orphan_jobs": removed_invalid_orphan_jobs,
        "removed_stale_entries": removed_stale_entries,
        "repaired_jobs": repaired_jobs,
        "requeued_orphan_jobs": requeued_orphan_jobs,
        "stale_ready_targets_removed": len(old_ready_targets.difference(nonempty_targets)),
        "stale_runtime_keys_removed": stale_runtime_keys_removed,
        "targets": len(nonempty_targets),
        "webhooks": len(webhook_jobs),
    }


async def purge_all(client: redis.Redis, prefix: str, lock_key: str, lost_event: asyncio.Event) -> dict[str, Any]:
    deleted = 0
    matched = 0
    while True:
        ensure_lock_active(lost_event)
        batch: list[str] = []
        async for key in client.scan_iter(match=f"{prefix}:*", count=1000):
            ensure_lock_active(lost_event)
            if key == lock_key:
                continue
            batch.append(key)
            if len(batch) >= 1000:
                break
        if not batch:
            break
        matched += len(batch)
        deleted += await delete_keys(client, batch)
    ensure_lock_active(lost_event)
    return {"deleted_keys": deleted, "matched_keys": matched, "prefix": prefix}


async def main() -> None:
    parser = argparse.ArgumentParser(prog="maintenance.py")
    parser.add_argument("command", choices={"audit", "reconcile", "purge-all"})
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--prefix", default=env_value("QueuePrefix", "discord_proxy", ("QUEUE_PREFIX",)))
    parser.add_argument("--confirm-prefix", default="")
    parser.add_argument("--drain-timeout", type=float, default=120.0)
    args = parser.parse_args()
    args.prefix = validate_prefix(args.prefix)
    if args.command == "purge-all" and args.confirm_prefix != args.prefix:
        raise SystemExit("purge-all requires --confirm-prefix with the exact queue prefix.")

    redis_url = env_value("RedisUrl", "", ("REDIS_URL",)).strip()
    if not redis_url:
        raise SystemExit("RedisUrl is required.")

    client = redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    try:
        await client.ping()
        if args.command == "audit":
            result = await audit(client, args.prefix, min(1000, max(1, args.top)))
        else:
            async with maintenance_barrier(
                client,
                args.prefix,
                finite_positive_float(args.drain_timeout, 1.0, 3600.0),
            ) as barrier:
                lock_key, lost_event = barrier
                if args.command == "reconcile":
                    result = await reconcile(client, args.prefix, lost_event)
                else:
                    result = await purge_all(client, args.prefix, lock_key, lost_event)
        output(result)
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
