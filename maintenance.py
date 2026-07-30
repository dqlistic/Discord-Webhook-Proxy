import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from typing import Any

import redis.asyncio as redis


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
        + 2048
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
    queue_count = 0
    job_count = 0
    queue_entries = 0
    top_queues: list[tuple[int, str]] = []

    async for key in client.scan_iter(match=f"{prefix}:*", count=1000):
        if key.startswith(queue_prefix):
            queue_count += 1
            length = int(await client.llen(key))
            queue_entries += length
            top_queues.append((length, key[len(queue_prefix) :]))
        elif key.startswith(job_prefix):
            job_count += 1

    top_queues.sort(reverse=True)
    memory = await client.info("memory")
    stats = await client.hgetall(f"{prefix}:stats")
    return {
        "database_keys": int(await client.dbsize()),
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


async def reconcile(client: redis.Redis, prefix: str) -> dict[str, Any]:
    queue_prefix = f"{prefix}:webhook-queue:"
    job_prefix = f"{prefix}:job:"
    webhook_job_prefix = f"{prefix}:pending:webhook-jobs:"
    webhook_bytes_prefix = f"{prefix}:pending:webhook-bytes:"
    target_bytes_prefix = f"{prefix}:pending:target-bytes:"
    webhook_jobs: defaultdict[str, int] = defaultdict(int)
    webhook_bytes: defaultdict[str, int] = defaultdict(int)
    target_bytes: defaultdict[str, int] = defaultdict(int)
    total_jobs = 0
    total_bytes = 0
    migrated_entries = 0
    removed_stale_entries = 0
    repaired_jobs = 0
    nonempty_targets: dict[str, int] = {}

    async for queue_key in client.scan_iter(match=f"{queue_prefix}*", count=200):
        target_key = queue_key[len(queue_prefix) :]
        length = int(await client.llen(queue_key))
        stale_entries: list[str] = []
        index = 0
        while index < length:
            entries = await client.lrange(queue_key, index, min(index + 499, length - 1))
            if not entries:
                break
            for relative_index, entry in enumerate(entries):
                absolute_index = index + relative_index
                job_id, charge, entry_webhook_key = parse_queue_entry(entry)
                job_key = f"{job_prefix}{job_id}"
                job = await client.hgetall(job_key)
                if not job:
                    stale_entries.append(entry)
                    continue

                webhook_key = job.get("webhook_key", entry_webhook_key)
                if not webhook_key:
                    stale_entries.append(entry)
                    await client.delete(job_key)
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

                total_jobs += 1
                total_bytes += charge
                webhook_jobs[webhook_key] += 1
                webhook_bytes[webhook_key] += charge
                target_bytes[target_key] += charge
            index += len(entries)

        for stale_entry in stale_entries:
            removed_stale_entries += int(await client.lrem(queue_key, 1, stale_entry))

        current_length = int(await client.llen(queue_key))
        if current_length == 0:
            await client.delete(queue_key, f"{target_bytes_prefix}{target_key}")
            await client.zrem(f"{prefix}:ready:webhooks", target_key)
            continue

        head_entry = await client.lindex(queue_key, 0)
        if head_entry:
            head_job_id, _, _ = parse_queue_entry(head_entry)
            available_at = await client.hget(f"{job_prefix}{head_job_id}", "available_at_ms")
            score = int(available_at or 0)
            nonempty_targets[target_key] = score

    stale_counter_keys: list[str] = []
    for pattern in (
        f"{webhook_job_prefix}*",
        f"{webhook_bytes_prefix}*",
        f"{target_bytes_prefix}*",
    ):
        async for key in client.scan_iter(match=pattern, count=1000):
            stale_counter_keys.append(key)
    await delete_keys(client, stale_counter_keys)

    pipe = client.pipeline(transaction=True)
    pipe.set(f"{prefix}:pending:jobs", total_jobs)
    pipe.set(f"{prefix}:pending:bytes", total_bytes)
    for webhook_key, count in webhook_jobs.items():
        pipe.set(f"{webhook_job_prefix}{webhook_key}", count)
    for webhook_key, size in webhook_bytes.items():
        pipe.set(f"{webhook_bytes_prefix}{webhook_key}", size)
    for target_key, size in target_bytes.items():
        pipe.set(f"{target_bytes_prefix}{target_key}", size)
    if nonempty_targets:
        pipe.zadd(f"{prefix}:ready:webhooks", nonempty_targets)
    await pipe.execute()

    ready_targets = await client.zrange(f"{prefix}:ready:webhooks", 0, -1)
    stale_ready = [
        target
        for target in ready_targets
        if not await client.exists(f"{queue_prefix}{target}")
    ]
    if stale_ready:
        await client.zrem(f"{prefix}:ready:webhooks", *stale_ready)

    return {
        "migrated_entries": migrated_entries,
        "pending_bytes": total_bytes,
        "pending_jobs": total_jobs,
        "removed_stale_entries": removed_stale_entries,
        "repaired_jobs": repaired_jobs,
        "stale_ready_targets_removed": len(stale_ready),
        "targets": len(nonempty_targets),
        "webhooks": len(webhook_jobs),
    }


async def purge_all(client: redis.Redis, prefix: str) -> dict[str, Any]:
    deleted = 0
    matched = 0
    while True:
        batch: list[str] = []
        async for key in client.scan_iter(match=f"{prefix}:*", count=1000):
            batch.append(key)
            if len(batch) >= 1000:
                break
        if not batch:
            break
        matched += len(batch)
        deleted += await delete_keys(client, batch)
    return {"deleted_keys": deleted, "matched_keys": matched, "prefix": prefix}


async def purge_obsolete(client: redis.Redis, prefix: str) -> dict[str, Any]:
    matched = 0
    deleted = 0
    batch: list[str] = []
    async for key in client.scan_iter(
        match=f"{prefix}:deadletter:*",
        count=1000,
    ):
        batch.append(key)
        matched += 1
        if len(batch) >= 500:
            deleted += await delete_keys(client, batch)
            batch.clear()
    deleted += await delete_keys(client, batch)
    removed_stats = int(
        await client.hdel(
            f"{prefix}:stats",
            "deadletter",
            "deadletter_dropped",
        )
    )
    return {
        "deleted_keys": deleted,
        "matched_keys": matched,
        "removed_stats_fields": removed_stats,
        "prefix": prefix,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(prog="maintenance.py")
    parser.add_argument("command", choices={"audit", "reconcile", "purge-obsolete", "purge-all"})
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--prefix", default=env_value("QueuePrefix", "discord_proxy", ("QUEUE_PREFIX",)))
    parser.add_argument("--confirm-offline", action="store_true")
    parser.add_argument("--confirm-purge-all", action="store_true")
    args = parser.parse_args()

    redis_url = env_value("RedisUrl", "", ("REDIS_URL",)).strip()
    if not redis_url:
        raise SystemExit("RedisUrl is required.")

    client = redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    try:
        await client.ping()
        if args.command == "audit":
            result = await audit(client, args.prefix, max(1, args.top))
        elif args.command == "reconcile":
            if not args.confirm_offline:
                raise SystemExit("reconcile requires --confirm-offline after all service replicas are stopped.")
            result = await reconcile(client, args.prefix)
        elif args.command == "purge-obsolete":
            result = await purge_obsolete(client, args.prefix)
        else:
            if not args.confirm_purge_all:
                raise SystemExit("purge-all requires --confirm-purge-all.")
            result = await purge_all(client, args.prefix)
        output(result)
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
