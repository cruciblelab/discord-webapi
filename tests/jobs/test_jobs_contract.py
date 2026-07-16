"""Shared behavior contract every JobQueue implementation must satisfy.

Both InProcessJobQueue and RedisJobQueue run against this exact suite --
the concrete mechanism guaranteeing the dashboard's jobs API never
accidentally depends on in-process-only behavior.
"""

import asyncio

from discord_webapi.jobs import JobQueue


async def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition never became true within timeout")


async def test_enqueue_returns_pending_status(job_queue: JobQueue) -> None:
    status = await job_queue.enqueue("noop", {"x": 1}, guild_id=999)

    assert status.state == "pending"
    assert status.job_type == "noop"
    assert status.guild_id == 999
    assert status.payload == {"x": 1}
    assert status.result is None
    assert status.error is None


async def test_get_status_of_unknown_job_returns_none(job_queue: JobQueue) -> None:
    assert await job_queue.get_status("does-not-exist") is None


async def test_job_is_processed_and_succeeds(job_queue: JobQueue) -> None:
    async def handler(payload: dict) -> dict:
        return {"doubled": payload["n"] * 2}

    job_queue.register_worker("double", handler)
    await job_queue.start()

    status = await job_queue.enqueue("double", {"n": 21})

    async def done() -> bool:
        current = await job_queue.get_status(status.job_id)
        return current is not None and current.state in ("succeeded", "failed")

    await _wait_until(done)

    final = await job_queue.get_status(status.job_id)
    assert final is not None
    assert final.state == "succeeded"
    assert final.result == {"doubled": 42}
    assert final.error is None


async def test_job_handler_exception_marks_job_failed(job_queue: JobQueue) -> None:
    async def handler(payload: dict) -> dict:
        raise ValueError("boom")

    job_queue.register_worker("always_fails", handler)
    await job_queue.start()

    status = await job_queue.enqueue("always_fails", {})

    async def done() -> bool:
        current = await job_queue.get_status(status.job_id)
        return current is not None and current.state in ("succeeded", "failed")

    await _wait_until(done)

    final = await job_queue.get_status(status.job_id)
    assert final is not None
    assert final.state == "failed"
    assert final.error is not None
    assert "boom" in final.error


async def test_two_jobs_of_different_types_are_both_processed(job_queue: JobQueue) -> None:
    results: list[str] = []

    async def handler_a(payload: dict) -> dict:
        results.append("a")
        return {}

    async def handler_b(payload: dict) -> dict:
        results.append("b")
        return {}

    job_queue.register_worker("type_a", handler_a)
    job_queue.register_worker("type_b", handler_b)
    await job_queue.start()

    status_a = await job_queue.enqueue("type_a", {})
    status_b = await job_queue.enqueue("type_b", {})

    async def both_done() -> bool:
        a = await job_queue.get_status(status_a.job_id)
        b = await job_queue.get_status(status_b.job_id)
        return a is not None and b is not None and a.state == "succeeded" and b.state == "succeeded"

    await _wait_until(both_done)

    assert set(results) == {"a", "b"}
