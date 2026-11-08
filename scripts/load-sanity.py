import concurrent.futures
import sys
import time
import urllib.error
import urllib.request

REQUEST_COUNT = 50
WORKERS = 10
MAX_P95_SECONDS = 2.0


def probe(endpoint):
    started = time.perf_counter()
    with urllib.request.urlopen(endpoint, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"Health endpoint returned HTTP {response.status}")
    return time.perf_counter() - started


def main():
    endpoint = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/api/health/"
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(probe, endpoint) for _ in range(REQUEST_COUNT)]
        results = []
        failures = []
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except (OSError, urllib.error.URLError, RuntimeError) as exc:
                failures.append(str(exc))

    if failures:
        print(f"{len(failures)} of {REQUEST_COUNT} requests failed: {failures[0]}", file=sys.stderr)
        return 1

    results.sort()
    p95 = results[int(len(results) * 0.95) - 1]
    print(f"{REQUEST_COUNT} requests passed; p95={p95:.3f}s")
    if p95 > MAX_P95_SECONDS:
        print(f"p95 exceeded the {MAX_P95_SECONDS:.1f}s sanity limit.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
