"""Private single-reader native command session; no retries or metadata authority."""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any
from time import monotonic


def call_later(delay, callback, *args):
    """Use the owning event loop; separate seam for controlled-clock policy tests."""
    return asyncio.get_running_loop().call_later(delay, callback, *args)


class CommandSession:
    """One authenticated socket, leased by the native owner's existing lock.

    Authentication uses the raw recv path before start_reader. Afterwards only
    the reader touches raw recv; callers receive from a bounded request inbox.
    A lease without an exact command-bearing response is never kept warm.
    """

    def __init__(self, socket: Any, context: Any, current, error_type) -> None:
        self.socket = socket
        self.context = context
        self.current = current
        self.error_type = error_type
        self.authenticated = False
        self.shuffle_switch = None
        self.reader: asyncio.Task | None = None
        self.command: str | None = None
        self._busy = False
        self.confirmed = False
        self.tainted = False
        self.failed = False
        self.inbox: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._close_task: asyncio.Task | None = None
        self._close_cancel_reported = False
        self._activity = monotonic()
        self._last_play = 0.0
        self._playing_until = 0.0
        self._idle_timer = None

    def observe_playing(self, until: float) -> None:
        """Retain only a bounded positive observation, not a source or send."""
        now = monotonic()
        if self._playing_until > now and until <= now:
            self._last_play = now
        elif until > now:
            self._last_play = until
        self._playing_until = until
        self._arm_idle()

    def _idle_deadline(self) -> float:
        return max(self._activity, self._last_play) + 300

    def _arm_idle(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        if self.valid() and not self._busy:
            self._idle_timer = call_later(max(0, self._idle_deadline() - monotonic()), self._expire)

    def _expire(self) -> None:
        self._idle_timer = None
        if self._busy or not self.valid():
            return
        if monotonic() < self._idle_deadline():
            self._arm_idle()
            return
        self.invalidate()
        self._start_close()

    def _start_close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name='audio command close')
            # Idle/read failure cleanup may have no waiting request. Retrieve a
            # close exception so task errors never leak credentials to the loop.
            self._close_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())

    def valid(self) -> bool:
        return not self.failed and self.current()

    def begin(self) -> None:
        if not self.valid() or self._busy or not self.inbox.empty():
            raise self.error_type('Native command session is no longer reusable')
        self._busy = True
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        self.confirmed = False

    def start_reader(self, shuffle_switch) -> None:
        self.authenticated = True
        self.shuffle_switch = shuffle_switch
        self.reader = asyncio.create_task(self._read(), name='audio command replies')

    def invalidate(self) -> None:
        self.failed = True
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        if self.inbox.empty():
            self.inbox.put_nowait(None)
        self._start_close()

    async def send(self, command: str) -> None:
        if not self.valid():
            raise self.error_type('Native command session authority changed')
        if self.authenticated:
            self.command = command
            if command.split('/')[2] not in ('status', 'getstatus'):
                self._activity = monotonic()
        await self.socket.send(command)

    async def recv(self):
        if not self.authenticated:
            return await self.socket.recv()
        if not self.valid():
            raise self.error_type('Native command session was lost or superseded')
        message = await self.inbox.get()
        if message is None or not self.valid():
            raise self.error_type('Native command session was lost or superseded')
        return message

    @staticmethod
    def _object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate native field')
            result[key] = value
        return result

    async def _read(self) -> None:
        try:
            while self.valid():
                # Buffered traffic must not starve the deadline/cancellation.
                await asyncio.sleep(0)
                message = await self.socket.recv()
                try:
                    payload = json.loads(message, object_pairs_hook=self._object) if isinstance(message, str) else None
                except ValueError as error:
                    if str(error) != 'duplicate native field' and self.command is not None:
                        # Preserve the owning proof parser's tolerance of
                        # unrelated malformed frames, never warm reuse.
                        self.tainted = True
                        self.inbox.put_nowait(message)
                        continue
                    self.invalidate()
                    break
                except (TypeError, RecursionError):
                    self.invalidate()
                    break
                if not isinstance(payload, dict):
                    continue
                # Only known unsolicited envelopes can be drained while idle.
                # Never let an event envelope carrying a result/error bypass
                # command qualification.
                if (not payload.get('error') and 'command' not in payload
                    and not any(k.endswith(('_result', '_error')) for k in payload)
                    and any(isinstance(payload.get(k), list) for k in ('audio_event', 'audio_sync_event'))):
                    if self.command is None:
                        continue
                if self.command is None:
                    self.invalidate()
                    break
                echo = payload.get('command')
                expected = self.command.split('/?q&', 1)[0]
                if echo is not None and echo != expected:
                    # Foreign results cannot settle _reply. Let the existing
                    # source-proof race inspect a neutral frame instead of
                    # failing independently qualified playback.
                    self.tainted = True
                    self.inbox.put_nowait('{}')
                    continue
                if echo == expected:
                    self.confirmed = True
                # Keep old command-less response compatibility for this request,
                # but no subsequent lease may trust that uncorrelated stream.
                self.inbox.put_nowait(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A receive/decode/buffer failure is not a playable success. Error
            # text can contain endpoints/authentication, so never retain it.
            self.invalidate()
        finally:
            self.invalidate()

    def finish(self) -> bool:
        keep = self.valid() and self.confirmed and not self.tainted and self.inbox.empty()
        self.command = None
        self._busy = False
        if keep:
            self._arm_idle()
        return keep

    async def close(self) -> None:
        """Idempotent bounded cleanup, shared by request/unload/revocation."""
        self.invalidate()
        self._start_close()
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            # A cancelled context exit is an outcome of that owned request,
            # not a fresh cancellation of every later unload/reconciliation.
            # Never swallow cancellation directed at the current caller.
            caller = asyncio.current_task()
            if self._close_task.cancelled() and caller is not None and not caller.cancelling():
                if self._close_cancel_reported:
                    return
                self._close_cancel_reported = True
            raise

    async def _close(self) -> None:
        if self.reader is not None:
            self.reader.cancel()
            with suppress(asyncio.CancelledError):
                await self.reader
        # websockets itself has close_timeout=2. Bound even external contexts;
        # the transport abort prevents a cancelled close leaving native IO live.
        try:
            async with asyncio.timeout(3):
                await self.context.__aexit__(None, None, None)
        except TimeoutError:
            transport = getattr(self.socket, 'transport', None)
            if transport is not None:
                transport.abort()
