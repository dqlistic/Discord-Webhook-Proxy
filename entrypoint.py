import os
import sys


def env_value(name: str, default: str, legacy_name: str | None = None) -> str:
    value = os.getenv(name)
    if value is None and legacy_name is not None:
        value = os.getenv(legacy_name)
    return default if value is None else value


def bounded_int(name: str, default: int, minimum: int, maximum: int, legacy_name: str | None = None) -> int:
    try:
        value = int(env_value(name, str(default), legacy_name))
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


def main() -> None:
    port = bounded_int("Port", 8000, 1, 65535, "PORT")
    workers = bounded_int("WebConcurrency", 1, 1, 32, "WEB_CONCURRENCY")
    keep_alive = bounded_int("UvicornKeepAlive", 5, 1, 120, "UVICORN_KEEP_ALIVE")
    backlog = bounded_int("UvicornBacklog", 2048, 128, 65535, "UVICORN_BACKLOG")
    graceful_shutdown = bounded_int("UvicornGracefulShutdown", 30, 1, 600, "UVICORN_GRACEFUL_SHUTDOWN")
    incomplete_event_size = bounded_int("UvicornH11MaxIncompleteEventSize", 65536, 16384, 1048576, "UVICORN_H11_MAX_INCOMPLETE_EVENT_SIZE")
    limit_concurrency = bounded_int("UvicornLimitConcurrency", 0, 0, 1000000, "UVICORN_LIMIT_CONCURRENCY")
    max_requests = bounded_int("UvicornLimitMaxRequests", 0, 0, 1000000000, "UVICORN_LIMIT_MAX_REQUESTS")
    max_requests_jitter = bounded_int("UvicornLimitMaxRequestsJitter", 0, 0, 1000000, "UVICORN_LIMIT_MAX_REQUESTS_JITTER")
    forwarded_allow_ips = env_value("ForwardedAllowIps", "*", "FORWARDED_ALLOW_IPS")

    arguments = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--workers",
        str(workers),
        "--http",
        "h11",
        "--proxy-headers",
        "--forwarded-allow-ips",
        forwarded_allow_ips,
        "--timeout-keep-alive",
        str(keep_alive),
        "--timeout-graceful-shutdown",
        str(graceful_shutdown),
        "--h11-max-incomplete-event-size",
        str(incomplete_event_size),
        "--backlog",
        str(backlog),
        "--log-level",
        "critical",
        "--no-access-log",
        "--no-server-header",
    ]
    if limit_concurrency > 0:
        arguments.extend(["--limit-concurrency", str(limit_concurrency)])
    if max_requests > 0:
        arguments.extend(["--limit-max-requests", str(max_requests)])
    if max_requests_jitter > 0:
        arguments.extend(["--limit-max-requests-jitter", str(max_requests_jitter)])
    os.execv(sys.executable, arguments)


if __name__ == "__main__":
    main()
