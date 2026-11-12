"""Synthetic native wire peer; no TCP, household IDs or access imports.

Runs the real RSA/AES authentication and command/reply parsers. Queue recv has
one consumer; authentication and user-command delays are independently counted.
"""
import asyncio
import json
from Crypto.PublicKey import RSA

_KEY = RSA.generate(2048).public_key().export_key().decode()


class Peer:
    def __init__(self, *, open_delay=0, auth_delay=0, close_delay=0, reply_delay=0):
        self.open_delay = open_delay
        self.auth_delay = auth_delay
        self.close_delay = close_delay
        self.reply_delay = reply_delay
        self.sockets = []
        self.opens = self.auths = self.closes = 0
        self.sends = []
        self.response = None
        self.on_send = None
        self.tasks = set()

    def connect(self, *args, **kwargs):
        peer = self
        class Context:
            async def __aenter__(self):
                await asyncio.sleep(peer.open_delay)
                peer.opens += 1
                self.socket = Socket(peer)
                peer.sockets.append(self.socket)
                return self.socket

            async def __aexit__(self, *_args):
                await self.socket.close()
        return Context()

    async def finish(self):
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for socket in self.sockets:
            await socket.close()


class Socket:
    def __init__(self, peer):
        self.peer = peer
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait('LWSS V 16.1.10.1 | ~API:1.6~ | Session-Token: synthetic-session')
        self.closed = False
        self.reading = False
        self.read_count = 0

    async def recv(self):
        assert not self.reading, 'Competing socket recv consumers'
        self.reading = True
        self.read_count += 1
        try:
            result = await self.incoming.get()
            if isinstance(result, BaseException):
                raise result
            return result
        finally:
            self.reading = False

    def put(self, payload):
        self.incoming.put_nowait(json.dumps(payload) if isinstance(payload, dict) else payload)

    async def send(self, command):
        if self.closed:
            raise OSError('synthetic disconnected before send')
        if command == 'audio/cfg/getkey/full':
            self.put({'command': command, 'getkey_result': [{'pubkey': _KEY}]})
            return
        if command.startswith('secure/authenticate/'):
            self.peer.auths += 1
            await asyncio.sleep(self.peer.auth_delay)
            self.put({'command': command, 'authenticate_result': 'authentication successful'})
            return
        self.peer.sends.append(command)
        if self.peer.on_send:
            await self.peer.on_send(self, command)
        async def respond():
            await asyncio.sleep(self.peer.reply_delay)
            if self.peer.response:
                result = self.peer.response(command)
            else:
                action = command.split('/')[2]
                if action == 'status':
                    result = {'status_result': [{'playerid': int(command.split('/')[1]), 'mode': 'pause', 'eventype': 0, 'audiopath': 'spotify:track:synthetic'}]}
                elif action == 'position':
                    result = {'position_result': [{'position': float(command.split('/')[3])}]}
                else:
                    result = {action + '_result': True}
                result['command'] = command
            if result is not None:
                self.put(result)
        task = asyncio.create_task(respond())
        self.peer.tasks.add(task)
        task.add_done_callback(self.peer.tasks.discard)

    async def close(self):
        if not self.closed:
            self.closed = True
            self.peer.closes += 1
            self.put(OSError('synthetic socket closed'))
            await asyncio.sleep(self.peer.close_delay)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.timers = []

    def time(self):
        return self.now

    def call_later(self, delay, callback, *args):
        class Timer:
            cancelled = False
            def cancel(self):
                self.cancelled = True
        timer = Timer()
        self.timers.append((self.now + delay, timer, callback, args))
        return timer

    async def advance(self, seconds):
        target = self.now + seconds
        for _ in range(10000):
            pending = sorted((t for t in self.timers if not t[1].cancelled and t[0] <= target), key=lambda t: t[0])
            if not pending:
                break
            item = pending[0]
            self.timers.remove(item)
            self.now = item[0]
            item[2](*item[3])
            await settle()
        else:
            raise RuntimeError('synthetic timer spin')
        self.now = target
        await settle()


async def settle():
    for _ in range(12):
        await asyncio.sleep(0)
