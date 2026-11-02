"""SAR-04a: short, local-filesystem transactions; no application paths migrated.

Use one stable lock_root OUTSIDE deletable batch directories, e.g.
DATA_DIR/.transactions. Never remove/replace its lockfiles while workers run.
All participants must share that root and canonical, case-sensitive logical IDs.
Separate opens plus POSIX flock coordinate threads and cooperating local
processes; this is not a worker ownership, distributed FS or recovery protocol.

Order: sorted batch IDs -> sorted bulk run IDs -> history. Template transactions
are independent and cannot be nested with any other transaction. Nesting the
same resource is rejected, not reentrant. Operations must be synchronous, short,
and contain no provider/network/WebSocket calls, OCR computation or event-loop
waits. Async callers must use run_async, never run_sync on the event loop.

A positive timeout covers all acquisitions and admission with one monotonic
budget, checked again before callback invocation. Zero means one non-waiting
attempt per lock; async zero-timeout admission gets a separate bounded 5s loop
handshake. No callback runs if its start check finds the deadline expired. Once
running, callbacks have no preemptive time limit.

A cancellation checkpoint before submission delivers pending requests; a
subsequent baseline distinguishes consumed historical cancellation counts from
new requests, without uncancel(). Cancellation before the loop's grant prevents
the callback. After the grant it waits for actual pre-start checks, operation
(if started), and cleanup, including repeated cancel. A deadline may still reject
a granted operation before it starts. File atomicity remains atomic_io's job;
no automatic recovery is performed. Lockfile opens reject symlinks and nonregular
files; a trusted, stable root remains a prerequisite.
"""

import asyncio
import contextvars
import errno
import fcntl
import hashlib
import inspect
import math
import os
import stat
import threading
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, Iterable, Iterator, Literal, Optional, TypeVar, cast

T = TypeVar("T")
Kind = Literal["batch", "bulk", "history", "template"]
_RANK = {"batch": 0, "bulk": 1, "history": 2, "template": 3}
_MAX_TIMEOUT = 300.0
_IMMEDIATE_ADMISSION_TIMEOUT = 5.0


class TransactionError(Exception):
    code = "transaction_failed"

    def __init__(self) -> None:
        super().__init__(self.code)


class TransactionTimeout(TransactionError):
    code = "transaction_timeout"


class TransactionOrderError(TransactionError):
    code = "transaction_lock_order"


class TransactionUsageError(TransactionError):
    code = "transaction_invalid_usage"


class TransactionIOError(TransactionError):
    code = "transaction_lock_io_failed"


class TransactionOperationError(TransactionError):
    code = "transaction_operation_failed"


class _Cancelled(TransactionError):
    code = "transaction_cancelled"


@dataclass(frozen=True)
class Resource:
    kind: Kind
    identifier: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in _RANK or not isinstance(self.identifier, str) or not self.identifier:
            raise TransactionUsageError()
        if self.kind in {"history", "template"} and self.identifier != "registry":
            raise TransactionUsageError()

    @property
    def order(self) -> tuple[int, str]:
        return _RANK[self.kind], self.identifier

    @classmethod
    def batch(cls, identifier: str) -> "Resource":
        return cls("batch", identifier)

    @classmethod
    def bulk(cls, identifier: str) -> "Resource":
        return cls("bulk", identifier)

    @classmethod
    def history(cls) -> "Resource":
        return cls("history", "registry")

    @classmethod
    def templates(cls) -> "Resource":
        return cls("template", "registry")


# Context propagation through run_async preserves logical nesting. OS flock,
# rather than this variable, provides mutual exclusion, also across instances.
_HELD: contextvars.ContextVar[tuple[str, tuple[Resource, ...]]] = contextvars.ContextVar(
    "transaction_held", default=("", ())
)


@dataclass
class _Outcome(Generic[T]):
    value: Optional[T] = None
    error: Optional[BaseException] = None


class _Admission:
    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self.ready = threading.Event()
        self.guard = threading.Lock()
        self.allowed: Optional[bool] = None
        self.deadline: Optional[float] = None
        self.expired = False

    def cancel(self) -> None:
        with self.guard:
            self.cancelled.set()
            self.ready.set()


class TransactionCoordinator:
    def __init__(self, lock_root: Path, *, batches_root: Path, timeout: float = 5.0) -> None:
        try:
            self.lock_root = Path(lock_root).resolve()
            batch_tree = Path(batches_root).resolve()
        except OSError:
            raise TransactionIOError() from None
        if self.lock_root == batch_tree or batch_tree in self.lock_root.parents:
            raise TransactionUsageError()
        self.timeout = self._timeout(timeout)

    @staticmethod
    def _timeout(value: float) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= _MAX_TIMEOUT:
            raise TransactionUsageError()
        return value

    def lock_path(self, resource: Resource) -> Path:
        digest = hashlib.sha256(resource.identifier.encode("utf-8")).hexdigest()
        return self.lock_root / f"{resource.kind}-{digest}.lock"

    def _ordered(self, resources: Iterable[Resource]) -> tuple[Resource, ...]:
        requested = tuple(resources)
        if not requested or any(not isinstance(r, Resource) for r in requested) or len(set(requested)) != len(requested):
            raise TransactionUsageError()
        ordered = tuple(sorted(requested, key=lambda r: r.order))
        root, held = _HELD.get()
        if held:
            if root != str(self.lock_root) or any(r.kind == "template" for r in (*held, *ordered)):
                raise TransactionOrderError()
            if ordered[0].order <= held[-1].order:
                raise TransactionOrderError()
        if any(r.kind == "template" for r in ordered) and len(ordered) != 1:
            raise TransactionOrderError()
        return ordered

    @contextmanager
    def _lock(self, resource: Resource, deadline: float, cancelled: threading.Event, *, immediate: bool = False) -> Iterator[None]:
        try:
            self.lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            # Fail closed on platforms without non-following opens. NONBLOCK
            # prevents a FIFO from blocking before fstat can reject its type.
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            if not nofollow:
                raise TransactionIOError()
            fd = os.open(self.lock_path(resource), os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK | nofollow, 0o600)
        except OSError:
            raise TransactionIOError() from None
        try:
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise TransactionIOError()
            except OSError:
                raise TransactionIOError() from None
            while True:
                if cancelled.is_set():
                    raise _Cancelled()
                if not immediate and time.monotonic() >= deadline:
                    raise TransactionTimeout()
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if not immediate and time.monotonic() >= deadline:
                        raise TransactionTimeout()
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EAGAIN, errno.EACCES):
                        raise TransactionIOError() from None
                remaining = deadline - time.monotonic()
                if immediate or remaining <= 0:
                    raise TransactionTimeout()
                cancelled.wait(min(0.01, remaining))
            # Closing the independent descriptor releases flock, even on errors.
            yield
        finally:
            try:
                os.close(fd)
            except OSError:
                raise TransactionIOError() from None

    def _execute(
        self, resources: Iterable[Resource], operation: Callable[[], T], timeout: float,
        admission: Optional[_Admission] = None, admit: Optional[Callable[[], None]] = None,
    ) -> T:
        ordered = self._ordered(resources)
        deadline = time.monotonic() + timeout
        immediate = timeout == 0
        cancelled = admission.cancelled if admission else threading.Event()
        with ExitStack() as stack:
            for resource in ordered:
                stack.enter_context(self._lock(resource, deadline, cancelled, immediate=immediate))
            if not immediate and time.monotonic() >= deadline:
                raise TransactionTimeout()
            if admission is not None:
                assert admit is not None
                # A zero timeout means one non-waiting attempt per lock.
                # The cross-thread admission handshake necessarily needs a
                # loop turn; only that special case gets a separate 5s bound.
                with admission.guard:
                    admission.deadline = time.monotonic() + _IMMEDIATE_ADMISSION_TIMEOUT if immediate else deadline
                admit()
                ready = admission.ready.wait(max(0.0, admission.deadline - time.monotonic()))
                with admission.guard:
                    # A grant racing wait's timeout must not be overwritten.
                    if admission.allowed is not True:
                        if not ready:
                            admission.expired = True
                            admission.allowed = False
                        if admission.expired:
                            raise TransactionTimeout()
                        raise _Cancelled()
            elif cancelled.is_set():
                raise _Cancelled()
            root, held = _HELD.get()
            token = _HELD.set((str(self.lock_root), held + ordered))
            try:
                try:
                    start_deadline = admission.deadline if admission is not None else (None if immediate else deadline)
                    if start_deadline is not None and time.monotonic() >= start_deadline:
                        raise TransactionTimeout()
                    value = operation()
                    if inspect.isawaitable(value):
                        if inspect.iscoroutine(value):
                            value.close()
                        raise TransactionUsageError()
                    return value
                except TransactionError:
                    raise
                except Exception:
                    # Public callers get a fixed error; no raw callback text or
                    # traceback leaves the async executor in its Future.
                    raise TransactionOperationError() from None
            finally:
                _HELD.reset(token)

    def run_sync(self, resources: Iterable[Resource], operation: Callable[[], T], *, timeout: Optional[float] = None) -> T:
        """Run one short callback. Exceptions release locks; failures are neutral."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise TransactionUsageError()
        return self._execute(resources, operation, self._timeout(self.timeout if timeout is None else timeout))

    async def run_async(self, resources: Iterable[Resource], operation: Callable[[], T], *, timeout: Optional[float] = None) -> T:
        """Acquire and execute off-loop; always join an admitted operation."""
        ordered = self._ordered(resources)
        limit = self._timeout(self.timeout if timeout is None else timeout)
        admission = _Admission()
        loop = asyncio.get_running_loop()
        owner = asyncio.current_task()
        assert owner is not None
        # Deliver pending cancellation before submission, without changing the
        # caller's cancellation count. Already consumed requests do not raise
        # again here. No executor work exists yet if this checkpoint cancels.
        await asyncio.sleep(0)
        cancellation_baseline = owner.cancelling()

        def decide() -> None:
            with admission.guard:
                assert admission.deadline is not None
                admission.expired = admission.expired or time.monotonic() >= admission.deadline
                admission.allowed = (
                    not admission.expired and not admission.cancelled.is_set()
                    and owner.cancelling() <= cancellation_baseline
                )
                admission.ready.set()

        def request_admission() -> None:
            loop.call_soon_threadsafe(decide)

        def work() -> _Outcome[T]:
            try:
                return _Outcome(value=self._execute(ordered, operation, limit, admission, request_admission))
            except BaseException as exc:
                return _Outcome(error=exc)

        # Explicit outcomes avoid Python 3.14 shield's logging of failed futures
        # on repeated cancellation (the SAR-03 writer follows the same pattern).
        context = contextvars.copy_context()
        future = loop.run_in_executor(None, context.run, work)
        try:
            outcome = await asyncio.shield(future)
        except asyncio.CancelledError:
            admission.cancel()
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    admission.cancel()
            # Retrieve the outcome, even on cancellation; no unobserved Future.
            outcome = future.result()
            # A real operation/I/O failure must not disappear behind CancelledError.
            if outcome.error is not None and not isinstance(outcome.error, _Cancelled):
                raise outcome.error from None
            raise
        if outcome.error is not None:
            raise outcome.error from None
        return cast(T, outcome.value)
