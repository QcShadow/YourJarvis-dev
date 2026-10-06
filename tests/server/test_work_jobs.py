"""Background work ownership, partial results and cancellation invariants."""

import asyncio
import json

import pytest

from openjarvis.server.work_jobs import (
    BackgroundWork,
    JobConflict,
    QueueFull,
    WorkStore,
)

REQ = {"model": "test", "messages": [{"role": "user", "content": "do work"}]}


async def wait_for(store, job_id, status):
    async with asyncio.timeout(3):
        while store.get(job_id)["status"] != status:
            await asyncio.sleep(0.01)
    return store.get(job_id)


def test_store_idempotency_capacity_and_atomic_claim(tmp_path):
    store = WorkStore(tmp_path / "jobs.db", capacity=1)
    job = store.submit(REQ, "chat", "key")
    assert store.submit(REQ, "chat", "key")["id"] == job["id"]
    with pytest.raises(JobConflict):
        store.submit(REQ, "different", "key")
    with pytest.raises(QueueFull):
        store.submit(REQ, "chat")
    assert store.claim()["id"] == job["id"]
    assert store.claim() is None
    assert "request" not in store.get(job["id"])
    store.close()


def test_summary_is_safe_and_tracks_queue_state(tmp_path):
    store = WorkStore(tmp_path / "jobs.db")
    queued = store.submit(REQ, "chat")
    summary = store.summary()
    assert summary["counts"] == {"queued": 1}
    assert summary["active"] == 1 and summary["total"] == 1
    assert "prompt" not in summary and "request" not in summary
    store.patch(queued["id"], status="completed", phase="completed")
    assert store.summary()["active"] == 0
    store.close()


def test_metrics_aggregates_models_tools_and_tokens_without_content(tmp_path):
    store = WorkStore(tmp_path / "jobs.db")
    first = store.submit(
        {"model": "worker-a", "messages": [{"role": "user", "content": "secret"}]},
        "chat",
    )
    store.patch(
        first["id"],
        status="completed",
        phase="completed",
        usage={"total_tokens": 12},
        tool_calls=[{"tool": "calculator", "status": "success"}],
        started_at=10.0,
        finished_at=12.5,
    )
    second = store.submit(
        {"model": "worker-a", "messages": [{"role": "user", "content": "secret 2"}]},
        "chat",
    )
    store.patch(
        second["id"],
        status="failed",
        phase="failed",
        usage={"total_tokens": 8},
        tool_calls=[{"tool": "calculator", "status": "error"}],
    )
    metrics = store.metrics()
    assert metrics["total_jobs"] == 2
    assert metrics["total_tokens"] == 20
    assert metrics["by_model"]["worker-a"]["completed"] == 1
    assert metrics["by_model"]["worker-a"]["failed"] == 1
    assert metrics["by_model"]["worker-a"]["avg_duration_seconds"] == 2.5
    assert metrics["tools"]["calculator"] == {"calls": 2, "success": 1, "error": 1}
    assert "secret" not in json.dumps(metrics)
    store.close()


def test_recovery_never_assumes_unknown_or_live_process_dead(tmp_path):
    path = tmp_path / "jobs.db"
    old = WorkStore(path, owner="old")
    job = old.submit(REQ, "chat")
    old.claim()
    old.patch(
        job["id"],
        content="partial",
        tool_calls=[{"tool": "file_write", "status": "running"}],
    )
    new = WorkStore(path, owner="new")
    new.recover_dead_owners(lambda pid: None)
    assert new.get(job["id"])["status"] == "running"
    identity = old.get(job["id"], internal=True)["owner_started"]
    new.recover_dead_owners(lambda pid: identity)
    assert new.get(job["id"])["status"] == "running"
    new.recover_dead_owners(lambda pid: False)
    recovered = new.get(job["id"])
    assert recovered["status"] == "interrupted" and recovered["content"] == "partial"
    assert new.claim() is None
    old.close()
    new.close()


@pytest.mark.asyncio
async def test_submit_is_immediate_and_single_worker_keeps_foreground_free(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()
    runs = []

    async def run(req):
        runs.append(req)
        started.set()
        yield {"text": "partial"}
        await release.wait()
        yield {"usage": {"completion_tokens": 12}}
        yield {"final_content": "complete", "finish_reason": "stop"}

    store = WorkStore(tmp_path / "jobs.db")
    worker = BackgroundWork(store, run)
    jobs = await asyncio.gather(
        *(worker.submit(REQ, "chat", f"key-{i}") for i in range(3))
    )
    await started.wait()
    assert len(runs) == 1
    assert await asyncio.sleep(0, result="foreground response") == "foreground response"
    await worker.cancel(jobs[1]["id"])
    release.set()
    result = await wait_for(store, jobs[0]["id"], "completed")
    assert (
        result["content"] == "complete" and result["usage"]["completion_tokens"] == 12
    )
    await wait_for(store, jobs[2]["id"], "completed")
    assert len(runs) == 2
    assert await worker.close()
    store.close()


@pytest.mark.asyncio
async def test_terminal_notification_is_observational_and_only_for_terminal_result(
    tmp_path,
):
    events = []

    async def notify(job):
        events.append(job)

    async def run(req):
        yield {"final_content": "complete", "finish_reason": "stop"}

    store = WorkStore(tmp_path / "jobs.db")
    worker = BackgroundWork(store, run, on_terminal=notify)
    job = await worker.submit(REQ, "chat")
    result = await wait_for(store, job["id"], "completed")
    assert await worker.close()
    assert events == [
        {
            "id": job["id"],
            "conversation_id": "chat",
            "status": "completed",
            "content": "complete",
        }
    ]
    assert result["status"] == "completed"
    store.close()


@pytest.mark.asyncio
async def test_cancel_and_shutdown_wait_for_started_tool_without_second_cancel(
    tmp_path,
):
    started, release, draining = asyncio.Event(), asyncio.Event(), asyncio.Event()
    later = []

    async def run(req):
        yield {"stage": "tool", "tool": "file_write", "arguments": "{}"}
        started.set()
        task = asyncio.create_task(release.wait())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            draining.set()
            await asyncio.shield(task)
            raise
        later.append("second tool")
        yield {"final_content": "complete", "finish_reason": "stop"}

    store = WorkStore(tmp_path / "jobs.db")
    worker = BackgroundWork(store, run)
    job = await worker.submit(REQ, "chat")
    await started.wait()
    assert (await worker.cancel(job["id"]))["status"] == "cancelling"
    await draining.wait()
    await worker.cancel(job["id"])
    assert not await worker.close(timeout=0.02)
    assert store.get(job["id"])["status"] == "cancelling"
    release.set()
    await wait_for(store, job["id"], "interrupted")
    assert not later
    with pytest.raises(JobConflict, match="side-effecting"):
        await worker.retry(job["id"])
    assert await worker.close()
    store.close()


@pytest.mark.asyncio
async def test_truncated_stream_fails_but_read_only_retry_is_new_work(tmp_path):
    async def run(req):
        yield {"text": "partial"}
        yield {"stage": "tool", "tool": "web_search"}
        yield {
            "stage": "tool_complete",
            "tool": "web_search",
            "success": True,
            "result": "source",
        }
        yield {"final_content": "partial", "finish_reason": "length"}

    store = WorkStore(tmp_path / "jobs.db")
    worker = BackgroundWork(store, run)
    job = await worker.submit(REQ, "chat")
    result = await wait_for(store, job["id"], "failed")
    assert (
        result["content"] == "partial"
        and result["tool_calls"][0]["status"] == "success"
    )
    retry = await worker.retry(job["id"])
    assert retry["id"] != job["id"] and retry["status"] == "queued"
    assert await worker.close()
    store.close()


@pytest.mark.asyncio
async def test_read_only_resume_carries_bounded_checkpoint_without_replaying_state(
    tmp_path,
):
    seen = []

    async def run(req):
        seen.append(req)
        yield {"final_content": "continued", "finish_reason": "stop"}

    store = WorkStore(tmp_path / "jobs.db")
    worker = BackgroundWork(store, run)
    job = store.submit(REQ, "chat")
    store.patch(
        job["id"],
        status="failed",
        phase="failed",
        content="partial answer",
        tool_calls=[
            {
                "tool": "web_search",
                "status": "success",
                "result": "source text",
            }
        ],
    )

    resumed = await worker.resume(job["id"])
    result = await wait_for(store, resumed["id"], "completed")
    assert result["content"] == "continued"
    assert seen[0]["messages"][-1]["content"] == "do work"
    checkpoint = next(
        message for message in seen[0]["messages"] if message["role"] == "system"
    )["content"]
    assert "partial answer" in checkpoint
    assert "source text" in checkpoint
    assert "untrusted data" in checkpoint
    assert await worker.close()
    store.close()


@pytest.mark.asyncio
async def test_resume_rejects_side_effecting_checkpoint(tmp_path):
    async def run(req):
        yield {"final_content": "unused", "finish_reason": "stop"}

    store = WorkStore(tmp_path / "jobs.db")
    worker = BackgroundWork(store, run)
    job = store.submit(REQ, "chat")
    store.patch(
        job["id"],
        status="interrupted",
        phase="interrupted",
        tool_calls=[{"tool": "file_write", "status": "running"}],
    )
    with pytest.raises(JobConflict, match="checkpoint resume is unsafe"):
        await worker.resume(job["id"])
    assert await worker.close()
    store.close()


@pytest.mark.asyncio
async def test_cannot_cancel_task_owned_by_another_live_server(tmp_path):
    path = tmp_path / "jobs.db"
    original = WorkStore(path, owner="original")
    job = original.submit(REQ, "chat")
    other = WorkStore(path, owner="other")

    async def run(req):
        yield {"final_content": "unused", "finish_reason": "stop"}

    worker = BackgroundWork(other, run)
    with pytest.raises(JobConflict, match="another server"):
        await worker.cancel(job["id"])
    assert await worker.close()
    assert original.get(job["id"])["status"] == "queued"
    original.close()
    other.close()
