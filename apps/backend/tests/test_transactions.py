"""SAR-04a: real local flock, deterministic contention and cancellation."""

import asyncio
import errno
import os
import multiprocessing
import shutil
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import transactions as module
from app.core.transactions import (
    Resource, TransactionCoordinator, TransactionIOError, TransactionOperationError,
    TransactionOrderError, TransactionTimeout, TransactionUsageError,
)

SECRET = "SENTINEL-private-provider-token-and-OCR"


@pytest.fixture
def coordinator(tmp_path):
    return TransactionCoordinator(tmp_path / "locks", batches_root=tmp_path / "batches", timeout=3)


def wait(event):
    assert event.wait(5), "Synchronization event timed out"


def test_same_batch_serializes_across_threads_and_instances(coordinator, monkeypatch):
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    second_entered = threading.Event()
    other = TransactionCoordinator(coordinator.lock_root, batches_root=coordinator.lock_root.parent / "batches")
    real_flock = module.fcntl.flock

    def flock(fd, flags):
        try:
            return real_flock(fd, flags)
        except BlockingIOError:
            attempted.set()
            raise

    monkeypatch.setattr(module.fcntl, "flock", flock)

    def first():
        entered.set()
        wait(release)

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(coordinator.run_sync, [Resource.batch("a")], first)
        wait(entered)
        b = pool.submit(other.run_sync, [Resource.batch("a")], second_entered.set)
        try:
            wait(attempted)
            assert not second_entered.is_set()
        finally:
            release.set()
        a.result(5)
        b.result(5)
    assert second_entered.is_set()


def test_different_batches_can_execute_in_parallel(coordinator):
    together = threading.Barrier(2)
    with ThreadPoolExecutor(2) as pool:
        jobs = [pool.submit(coordinator.run_sync, [Resource.batch(n)], lambda: together.wait(3)) for n in ("a", "b")]
        for job in jobs:
            job.result(5)


def test_timeout_does_not_invoke_callback(coordinator):
    entered, release, mutated = threading.Event(), threading.Event(), threading.Event()

    def hold():
        entered.set()
        wait(release)

    with ThreadPoolExecutor(1) as pool:
        job = pool.submit(coordinator.run_sync, [Resource.batch("a")], hold)
        wait(entered)
        try:
            with pytest.raises(TransactionTimeout):
                coordinator.run_sync([Resource.batch("a")], mutated.set, timeout=0)
        finally:
            release.set()
        job.result(5)
    assert not mutated.is_set()


def test_exception_is_neutral_and_lock_is_released(coordinator, caplog):
    def fail():
        raise RuntimeError(SECRET)

    with pytest.raises(TransactionOperationError) as error:
        coordinator.run_sync([Resource.batch("a")], fail)
    assert SECRET not in str(error.value)
    assert SECRET not in "".join(traceback.format_exception(error.value))
    assert SECRET not in caplog.text
    assert coordinator.run_sync([Resource.batch("a")], lambda: 42, timeout=0) == 42


def test_lock_identity_survives_batch_directory_recreation(coordinator, tmp_path):
    batch = tmp_path / "batches" / "a"
    batch.mkdir(parents=True)
    resource = Resource.batch("a")
    entered, release = threading.Event(), threading.Event()

    def hold():
        entered.set()
        wait(release)

    with ThreadPoolExecutor(1) as pool:
        holder = pool.submit(coordinator.run_sync, [resource], hold)
        wait(entered)
        lock = coordinator.lock_path(resource)
        inode = lock.stat().st_ino
        try:
            assert batch not in lock.parents
            shutil.rmtree(batch)
            batch.mkdir()
            with pytest.raises(TransactionTimeout):
                coordinator.run_sync([resource], lambda: None, timeout=0)
            assert lock.stat().st_ino == inode
        finally:
            release.set()
        holder.result(5)
    coordinator.run_sync([resource], lambda: None)
    assert lock.stat().st_ino == inode


def test_requested_batches_are_sorted_and_valid_nesting_works(coordinator):
    seen = []

    def operation():
        seen.extend(r.identifier for r in module._HELD.get()[1])
        return coordinator.run_sync([Resource.bulk("run")], lambda: coordinator.run_sync([Resource.history()], lambda: "ok"))

    assert coordinator.run_sync([Resource.batch("b"), Resource.batch("a")], operation) == "ok"
    assert seen == ["a", "b"]
    coordinator.run_sync([Resource.templates()], lambda: None)


@pytest.mark.parametrize("outer,inner", [
    (Resource.batch("b"), Resource.batch("a")),
    (Resource.batch("a"), Resource.batch("a")),
    (Resource.bulk("run"), Resource.batch("a")),
    (Resource.history(), Resource.bulk("run")),
    (Resource.templates(), Resource.batch("a")),
    (Resource.batch("a"), Resource.templates()),
])
def test_reversed_or_reentrant_nesting_is_rejected(coordinator, outer, inner):
    with pytest.raises(TransactionOrderError):
        coordinator.run_sync([outer], lambda: coordinator.run_sync([inner], lambda: None))
    coordinator.run_sync([outer], lambda: None, timeout=0)


def test_mixed_template_transaction_and_duplicate_resources_are_rejected(coordinator):
    with pytest.raises(TransactionOrderError):
        coordinator.run_sync([Resource.batch("a"), Resource.templates()], lambda: None)
    with pytest.raises(TransactionUsageError):
        coordinator.run_sync([Resource.batch("a"), Resource.batch("a")], lambda: None)


@pytest.mark.parametrize("timeout", [-1, float("inf"), float("nan"), 301])
def test_invalid_timeout_is_neutral(tmp_path, timeout):
    with pytest.raises(TransactionUsageError):
        TransactionCoordinator(tmp_path / "locks", batches_root=tmp_path / "batches", timeout=timeout)


def test_infrastructure_failure_is_neutral(coordinator, monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise PermissionError(SECRET)

    monkeypatch.setattr(module.os, "open", fail)
    with pytest.raises(TransactionIOError) as error:
        coordinator.run_sync([Resource.batch("a")], lambda: pytest.fail("must not run"))
    assert SECRET not in "".join(traceback.format_exception(error.value)) + caplog.text


def test_partial_acquisition_failure_releases_previous_locks(coordinator, monkeypatch):
    real_lock = coordinator._lock

    def lock(resource, deadline, cancelled, **kwargs):
        if resource.identifier == "b":
            raise TransactionIOError()
        return real_lock(resource, deadline, cancelled, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(coordinator, "_lock", lock)
        with pytest.raises(TransactionIOError):
            coordinator.run_sync([Resource.batch("a"), Resource.batch("b")], lambda: None)
    coordinator.run_sync([Resource.batch("a")], lambda: None, timeout=0)


def test_async_wrapper_keeps_event_loop_responsive_and_cancels_waiter(coordinator, monkeypatch):
    held, release, contended = threading.Event(), threading.Event(), threading.Event()
    called = threading.Event()
    real_flock = module.fcntl.flock

    def flock(fd, flags):
        try:
            return real_flock(fd, flags)
        except BlockingIOError:
            contended.set()
            raise

    monkeypatch.setattr(module.fcntl, "flock", flock)

    def hold():
        held.set()
        wait(release)

    with ThreadPoolExecutor(1) as pool:
        holder = pool.submit(coordinator.run_sync, [Resource.batch("a")], hold)
        wait(held)

        async def scenario():
            task = asyncio.create_task(coordinator.run_async([Resource.batch("a")], called.set))
            assert await asyncio.to_thread(contended.wait, 3)
            task.cancel()
            # Release immediately: admission must reject the cancelled owner,
            # even if the executor acquires the file before its handler runs.
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await coordinator.run_async([Resource.batch("a")], lambda: "free") == "free"

        try:
            asyncio.run(scenario())
        finally:
            release.set()
        holder.result(5)
    assert not called.is_set()


@pytest.mark.parametrize("fail", [False, True])
def test_repeated_cancel_joins_operation_before_release(coordinator, caplog, fail):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    resource = Resource.batch("a")

    def operation():
        entered.set()
        wait(release)
        exited.set()
        if fail:
            raise RuntimeError(SECRET)
        return "committed"

    async def scenario():
        task = asyncio.create_task(coordinator.run_async([resource], operation))
        assert await asyncio.to_thread(entered.wait, 3)
        for _ in range(3):
            task.cancel()
            # Explicit loop turn, not a timing-based sleep.
            checkpoint = asyncio.get_running_loop().create_future()
            asyncio.get_running_loop().call_soon(checkpoint.set_result, None)
            await checkpoint
            assert not task.done()
        with pytest.raises(TransactionTimeout):
            await asyncio.to_thread(coordinator.run_sync, [resource], lambda: None, timeout=0)
        release.set()
        with pytest.raises(TransactionOperationError if fail else asyncio.CancelledError):
            await task
        assert exited.is_set()
        assert await coordinator.run_async([resource], lambda: 7) == 7

    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert SECRET not in caplog.text
    assert "Traceback" not in caplog.text


def test_sync_entrypoint_rejects_event_loop_use(coordinator):
    async def scenario():
        with pytest.raises(TransactionUsageError):
            coordinator.run_sync([Resource.batch("a")], lambda: None)
    asyncio.run(scenario())


def test_awaitable_callback_is_rejected_and_closed(coordinator):
    async def invalid():
        return 1
    with pytest.raises(TransactionUsageError):
        coordinator.run_sync([Resource.batch("a")], invalid)


def _process_hold(root, entered, release):
    coordinator = TransactionCoordinator(Path(root), batches_root=Path(root).parent / "batches", timeout=3)

    def operation():
        entered.set()
        if not release.wait(8):
            raise RuntimeError("Process synchronization timed out")
    coordinator.run_sync([Resource.batch("a")], operation)


def test_local_processes_share_lock_identity(coordinator):
    context = multiprocessing.get_context("spawn")
    entered, release = context.Event(), context.Event()
    process = context.Process(target=_process_hold, args=(str(coordinator.lock_root), entered, release))
    process.start()
    try:
        wait(entered)
        with pytest.raises(TransactionTimeout):
            coordinator.run_sync([Resource.batch("a")], lambda: None, timeout=0)
        coordinator.run_sync([Resource.batch("b")], lambda: None, timeout=0)
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
    assert process.exitcode == 0
    coordinator.run_sync([Resource.batch("a")], lambda: None, timeout=0)


@pytest.mark.parametrize("location", ["batches", "batches/a/locks"])
def test_lock_root_cannot_be_in_deletable_batch_tree(tmp_path, location):
    with pytest.raises(TransactionUsageError):
        TransactionCoordinator(tmp_path / location, batches_root=tmp_path / "batches")


def test_cancellation_of_queued_executor_work_never_mutates(coordinator):
    release, mutated = threading.Event(), threading.Event()

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(1))
        occupied = loop.create_future()

        def occupy():
            loop.call_soon_threadsafe(occupied.set_result, None)
            wait(release)

        blocker = loop.run_in_executor(None, occupy)
        await asyncio.wait_for(occupied, 3)
        submitted = loop.create_future()
        original_submit = loop.run_in_executor

        def submit(*args):
            result = original_submit(*args)
            submitted.set_result(None)
            return result

        loop.run_in_executor = submit
        task = asyncio.create_task(coordinator.run_async([Resource.batch("a")], mutated.set))
        await submitted
        loop.run_in_executor = original_submit
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await blocker
        assert not mutated.is_set()

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_context_and_order_survive_async_executor_boundary(coordinator):
    def operation():
        assert module._HELD.get()[1] == (Resource.batch("a"),)
        return coordinator.run_sync([Resource.history()], lambda: 9)

    async def scenario():
        assert await coordinator.run_async([Resource.batch("a")], operation) == 9
        with pytest.raises(TransactionOrderError):
            await coordinator.run_async([Resource.history()], lambda: coordinator.run_sync([Resource.batch("a")], lambda: None))
    asyncio.run(scenario())


def test_timeout_on_second_resource_releases_first(coordinator):
    held, release = threading.Event(), threading.Event()
    mutated = []

    def hold():
        held.set()
        wait(release)

    with ThreadPoolExecutor(1) as pool:
        holder = pool.submit(coordinator.run_sync, [Resource.batch("b")], hold)
        wait(held)
        try:
            with pytest.raises(TransactionTimeout):
                coordinator.run_sync([Resource.batch("a"), Resource.batch("b")], lambda: mutated.append(True), timeout=0)
            coordinator.run_sync([Resource.batch("a")], lambda: None, timeout=0)
        finally:
            release.set()
        holder.result(5)
    assert not mutated


def test_async_timeout_does_not_mutate_later(coordinator):
    held, release, mutated = threading.Event(), threading.Event(), threading.Event()

    def hold():
        held.set()
        wait(release)

    with ThreadPoolExecutor(1) as pool:
        holder = pool.submit(coordinator.run_sync, [Resource.batch("a")], hold)
        wait(held)

        async def scenario():
            with pytest.raises(TransactionTimeout):
                await coordinator.run_async([Resource.batch("a")], mutated.set, timeout=0.02)
        try:
            asyncio.run(scenario())
        finally:
            release.set()
        holder.result(5)
    assert not mutated.is_set()


def test_async_callback_failure_has_no_sensitive_traceback(coordinator, caplog):
    def operation():
        raise RuntimeError(SECRET)

    async def scenario():
        with pytest.raises(TransactionOperationError) as error:
            await coordinator.run_async([Resource.batch("a")], operation)
        assert SECRET not in "".join(traceback.format_exception(error.value))
        assert await coordinator.run_async([Resource.batch("a")], lambda: True)
    asyncio.run(scenario())
    assert SECRET not in caplog.text


@pytest.fixture
def clock(monkeypatch):
    value = [0.0]
    # Replace only the component's clock; leave asyncio's real clock intact.
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: value[0]))
    return value


def test_successful_second_flock_after_deadline_cannot_mutate(coordinator, monkeypatch, clock):
    real_flock = module.fcntl.flock
    attempts, mutated = [], []

    def flock(fd, flags):
        attempts.append(fd)
        if len(attempts) == 1:
            raise BlockingIOError(errno.EAGAIN, "busy")
        clock[0] = 2.0
        return real_flock(fd, flags)

    with monkeypatch.context() as patch:
        patch.setattr(module.fcntl, "flock", flock)
        with pytest.raises(TransactionTimeout):
            coordinator.run_sync([Resource.batch("a")], lambda: mutated.append(True), timeout=1)
    assert len(attempts) == 2 and not mutated
    coordinator.run_sync([Resource.batch("a")], lambda: None, timeout=0)


def test_lock_released_after_deadline_is_not_retried(coordinator, monkeypatch, clock):
    entered, release = threading.Event(), threading.Event()
    mutated = []

    def hold():
        entered.set()
        wait(release)

    with ThreadPoolExecutor(1) as pool:
        holder = pool.submit(coordinator.run_sync, [Resource.batch("a")], hold)
        wait(entered)

        class ExpiringWait(threading.Event):
            def wait(self, timeout=None):
                clock[0] = 2.0
                release.set()
                holder.result(3)  # Includes actual descriptor close.
                return False

        try:
            with monkeypatch.context() as patch:
                patch.setattr(module, "threading", SimpleNamespace(Event=ExpiringWait))
                with pytest.raises(TransactionTimeout):
                    coordinator.run_sync([Resource.batch("a")], lambda: mutated.append(True), timeout=1)
        finally:
            release.set()
        holder.result(5)
    assert not mutated
    coordinator.run_sync([Resource.batch("a")], lambda: None, timeout=0)


def test_resources_share_deadline_and_release_all_partial_locks(coordinator, monkeypatch, clock):
    real_flock = module.fcntl.flock
    real_lock = coordinator._lock
    deadlines, mutated = [], []

    def lock(resource, deadline, cancelled, **kwargs):
        deadlines.append(deadline)
        return real_lock(resource, deadline, cancelled, **kwargs)

    def flock(fd, flags):
        result = real_flock(fd, flags)
        clock[0] += 0.6
        return result

    with monkeypatch.context() as patch:
        patch.setattr(coordinator, "_lock", lock)
        patch.setattr(module.fcntl, "flock", flock)
        with pytest.raises(TransactionTimeout):
            coordinator.run_sync([Resource.batch("a"), Resource.batch("b")], lambda: mutated.append(True), timeout=1)
    assert deadlines == [1.0, 1.0] and not mutated
    coordinator.run_sync([Resource.batch("a"), Resource.batch("b")], lambda: None, timeout=0)


@pytest.mark.parametrize("timeout,expired_at", [(1, 2.0), (0, 6.0)])
def test_delayed_async_admission_cannot_start_callback(coordinator, monkeypatch, clock, timeout, expired_at):
    mutated = []

    async def scenario():
        loop = asyncio.get_running_loop()
        schedule = loop.call_soon_threadsafe

        def delayed(callback, *args, **kwargs):
            if getattr(callback, "__name__", None) == "decide":
                clock[0] = expired_at
            return schedule(callback, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(loop, "call_soon_threadsafe", delayed)
            with pytest.raises(TransactionTimeout):
                await coordinator.run_async([Resource.batch("a")], lambda: mutated.append(True), timeout=timeout)
        assert await coordinator.run_async([Resource.batch("a")], lambda: "free", timeout=0) == "free"
    asyncio.run(scenario())
    assert not mutated


def test_deadline_rechecked_after_async_grant_before_callback(coordinator, monkeypatch, clock):
    mutated = []

    class LateWakeup(threading.Event):
        def wait(self, timeout=None):
            result = super().wait(timeout)
            if result:
                clock[0] = 2.0
            return result

    async def scenario():
        with monkeypatch.context() as patch:
            patch.setattr(module, "threading", SimpleNamespace(Event=LateWakeup, Lock=threading.Lock))
            with pytest.raises(TransactionTimeout):
                await coordinator.run_async([Resource.batch("a")], lambda: mutated.append(True), timeout=1)
    asyncio.run(scenario())
    assert not mutated
    coordinator.run_sync([Resource.batch("a")], lambda: None, timeout=0)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_zero_timeout_allows_free_locks_without_elapsed_budget(coordinator, monkeypatch, clock, asynchronous):
    real_flock = module.fcntl.flock

    def slow_success(fd, flags):
        clock[0] += 10.0  # Not contention: zero timeout is a single try.
        return real_flock(fd, flags)

    with monkeypatch.context() as patch:
        patch.setattr(module.fcntl, "flock", slow_success)
        if asynchronous:
            result = asyncio.run(coordinator.run_async([Resource.batch("a"), Resource.batch("b")], lambda: 42, timeout=0))
        else:
            result = coordinator.run_sync([Resource.batch("a"), Resource.batch("b")], lambda: 42, timeout=0)
    assert result == 42


def test_zero_async_timeout_does_not_wait_for_busy_lock(coordinator):
    entered, release, called = threading.Event(), threading.Event(), threading.Event()

    def hold():
        entered.set()
        wait(release)
    with ThreadPoolExecutor(1) as pool:
        holder = pool.submit(coordinator.run_sync, [Resource.batch("a")], hold)
        wait(entered)
        try:
            with pytest.raises(TransactionTimeout):
                asyncio.run(coordinator.run_async([Resource.batch("a")], called.set, timeout=0))
        finally:
            release.set()
        holder.result(5)
    assert not called.is_set()


async def consume_old_cancellation():
    task = asyncio.current_task()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.sleep(0)  # Cancellation checkpoint, no timing delay.
    assert task.cancelling() == 1
    return task


def test_consumed_historical_cancellation_allows_new_transaction(coordinator):
    async def scenario():
        owner = await consume_old_cancellation()
        assert await coordinator.run_async([Resource.batch("a")], lambda: 42) == 42
        assert owner.cancelling() == 1  # Primitive must not uncancel the caller.
    asyncio.run(scenario())


def test_new_cancellation_exactly_before_grant_with_historical_count(coordinator, monkeypatch):
    called = []

    async def scenario():
        owner = await consume_old_cancellation()
        loop = asyncio.get_running_loop()
        schedule = loop.call_soon_threadsafe

        def intercept(callback, *args, **kwargs):
            if getattr(callback, "__name__", None) == "decide":
                def cancel_then_decide():
                    owner.cancel()
                    callback(*args)
                return schedule(cancel_then_decide, **kwargs)
            return schedule(callback, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(loop, "call_soon_threadsafe", intercept)
            with pytest.raises(asyncio.CancelledError):
                await coordinator.run_async([Resource.batch("a")], lambda: called.append(True))
        assert owner.cancelling() == 2
        assert await coordinator.run_async([Resource.batch("a")], lambda: "free") == "free"
    asyncio.run(scenario())
    assert not called


@pytest.mark.parametrize("fail", [False, True])
def test_historical_then_repeated_new_cancel_after_admission(coordinator, caplog, fail):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()

    def operation():
        entered.set()
        wait(release)
        exited.set()
        if fail:
            raise RuntimeError(SECRET)
        return 42

    async def scenario():
        owner = await consume_old_cancellation()

        async def cancel():
            assert await asyncio.to_thread(entered.wait, 3)
            for _ in range(3):
                owner.cancel()
                await asyncio.sleep(0)
                assert not owner.done() and not exited.is_set()
            with pytest.raises(TransactionTimeout):
                await asyncio.to_thread(coordinator.run_sync, [Resource.batch("a")], lambda: None, timeout=0)
            release.set()

        controller = asyncio.create_task(cancel())
        try:
            with pytest.raises(TransactionOperationError if fail else asyncio.CancelledError):
                await coordinator.run_async([Resource.batch("a")], operation)
        finally:
            release.set()
            await controller
        assert owner.cancelling() == 4 and exited.is_set()
        assert await coordinator.run_async([Resource.batch("a")], lambda: "free") == "free"
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert SECRET not in caplog.text and "Traceback" not in caplog.text


def test_pending_cancel_before_entry_never_submits_callback(coordinator):
    called = []

    async def scenario():
        owner = asyncio.current_task()
        owner.cancel()  # Not yet delivered; cannot count this as old/consumed.
        with pytest.raises(asyncio.CancelledError):
            await coordinator.run_async([Resource.batch("a")], lambda: called.append(True))
    asyncio.run(scenario())
    assert not called


def test_lock_symlink_is_rejected_without_open_descriptor(coordinator, tmp_path, monkeypatch, caplog):
    resource = Resource.batch("a")
    coordinator.lock_root.mkdir()
    target = tmp_path / "private-file"
    target.write_text("unchanged")
    coordinator.lock_path(resource).symlink_to(target)
    opened = []
    real_open = module.os.open

    def open_file(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    monkeypatch.setattr(module.os, "open", open_file)
    with pytest.raises(TransactionIOError):
        coordinator.run_sync([resource], lambda: pytest.fail("must not run"))
    assert not opened and target.read_text() == "unchanged"
    assert SECRET not in caplog.text


@pytest.mark.parametrize("fault", ["fifo", "fstat", "flock"])
def test_descriptor_closed_on_type_stat_or_lock_error(coordinator, monkeypatch, caplog, fault):
    resource = Resource.batch("a")
    coordinator.lock_root.mkdir()
    if fault == "fifo":
        os.mkfifo(coordinator.lock_path(resource))
    opened, closed = [], []
    real_open, real_close, real_stat = module.os.open, module.os.close, module.os.fstat

    def open_file(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def close_file(fd):
        closed.append(fd)
        return real_close(fd)

    def fail(*args, **kwargs):
        raise OSError(errno.EIO, SECRET)

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "open", open_file)
        patch.setattr(module.os, "close", close_file)
        if fault == "fstat":
            patch.setattr(module.os, "fstat", fail)
        if fault == "flock":
            patch.setattr(module.fcntl, "flock", fail)
        with pytest.raises(TransactionIOError) as error:
            coordinator.run_sync([resource], lambda: pytest.fail("must not run"))
        assert SECRET not in "".join(traceback.format_exception(error.value))
    assert len(opened) == 1 and opened == closed
    with pytest.raises(OSError) as error:
        real_stat(opened[0])
    assert error.value.errno == errno.EBADF
    assert SECRET not in caplog.text


def test_failed_open_does_not_close_an_unowned_descriptor(coordinator, monkeypatch):
    closed = []

    def fail(*args, **kwargs):
        raise PermissionError(SECRET)

    monkeypatch.setattr(module.os, "open", fail)
    monkeypatch.setattr(module.os, "close", closed.append)
    with pytest.raises(TransactionIOError):
        coordinator.run_sync([Resource.batch("a")], lambda: pytest.fail("must not run"))
    assert not closed


def test_new_cancel_just_after_grant_waits_for_callback(coordinator, monkeypatch):
    issued, entered, release, exited = (threading.Event() for _ in range(4))

    class WaitForCancellation(threading.Event):
        def wait(self, timeout=None):
            result = super().wait(timeout)
            if result:
                wait(issued)  # Hold worker until cancel follows the grant.
            return result

    def operation():
        entered.set()
        wait(release)
        exited.set()

    async def scenario():
        owner = await consume_old_cancellation()
        loop = asyncio.get_running_loop()
        schedule = loop.call_soon_threadsafe

        def intercept(callback, *args, **kwargs):
            if getattr(callback, "__name__", None) == "decide":
                def grant_then_cancel():
                    callback(*args)
                    owner.cancel()
                    issued.set()
                return schedule(grant_then_cancel, **kwargs)
            return schedule(callback, *args, **kwargs)

        async def finish():
            assert await asyncio.to_thread(entered.wait, 3)
            assert not owner.done() and not exited.is_set()
            with pytest.raises(TransactionTimeout):
                await asyncio.to_thread(coordinator.run_sync, [Resource.batch("a")], lambda: None, timeout=0)
            release.set()

        controller = asyncio.create_task(finish())
        try:
            with monkeypatch.context() as patch:
                patch.setattr(module, "threading", SimpleNamespace(Event=WaitForCancellation, Lock=threading.Lock))
                patch.setattr(loop, "call_soon_threadsafe", intercept)
                with pytest.raises(asyncio.CancelledError):
                    await coordinator.run_async([Resource.batch("a")], operation)
        finally:
            release.set()
            await controller
        assert exited.is_set() and owner.cancelling() == 2
    try:
        asyncio.run(scenario())
    finally:
        issued.set()
        release.set()


def test_missing_nofollow_support_fails_closed(coordinator, monkeypatch):
    with monkeypatch.context() as patch:
        patch.delattr(module.os, "O_NOFOLLOW")
        with pytest.raises(TransactionIOError):
            coordinator.run_sync([Resource.batch("a")], lambda: pytest.fail("must not run"))
