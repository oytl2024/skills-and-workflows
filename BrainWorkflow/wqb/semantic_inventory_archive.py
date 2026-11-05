"""Bounded, lossless historical inventory objects; never removes source evidence."""

from __future__ import annotations

import gzip
import hashlib
import io
import math
import operator
import os
from pathlib import Path
import re
import stat
import time
import uuid
import zlib

from wqb.knowledge_clean_compile import _safe_local_path
from wqb.lockfile import json_lock_transition_guard


MAX_UNCOMPRESSED_BYTES = 4 * 1024**3
MAX_COMPRESSED_BYTES = MAX_UNCOMPRESSED_BYTES + 16 * 1024**2
DEFAULT_TIMEOUT_SECONDS = 600.0
CHUNK_BYTES = 1024 * 1024
LOCK_SLEEP_SECONDS = 0.05
HEX_SHA = re.compile(r'[0-9a-f]{64}')
SOURCE_PATH = re.compile(r'machine/semantic_jobs/[0-9a-f]{64}/inventory\.jsonl')
REF_KEYS = {'path', 'sha256', 'uncompressed_sha256', 'uncompressed_bytes'}


def _deadline(timeout_seconds: float) -> float:
    """Input: finite positive seconds (number). Output: monotonic deadline (float)."""
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0):
        raise ValueError('archive timeout must be finite and positive')
    for bound in (MAX_UNCOMPRESSED_BYTES, MAX_COMPRESSED_BYTES, CHUNK_BYTES):
        if type(bound) is not int or bound <= 0:
            raise ValueError('archive byte bounds must be positive integers')
    return time.monotonic() + timeout_seconds


def _tick(deadline: float) -> None:
    """Input: deadline (float). Output: None; reject expired streaming work."""
    if time.monotonic() >= deadline:
        raise ValueError('inventory archive timeout')


def _safe(root: Path, path: Path) -> None:
    """Input: root/path (Path). Output: None; reject unsafe filesystem components."""
    reason = _safe_local_path(root, path)
    if reason:
        raise ValueError('unsafe inventory archive path: ' + reason)


def _identity(info: os.stat_result) -> tuple:
    """Input: stat result. Output: tuple binding file identity, size and mutation times."""
    # Python 3.12 Windows stat/fstat expose different ctime semantics.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _open(root: Path, path: Path):
    """Input: root/path (Path). Output: binary file; pin a checked ordinary single-link file."""
    _safe(root, path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('archive input is not a regular file')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    handle = os.fdopen(fd, 'rb', buffering=0)
    try:
        _unchanged(root, path, handle, _identity(before))
        return handle
    except BaseException:
        handle.close()
        raise


def _unchanged(root: Path, path: Path, handle, identity: tuple) -> None:
    """Input: checked path, binary handle, stat tuple. Output: None; detect replacement/mutation."""
    _safe(root, path)
    current = os.fstat(handle.fileno())
    if (current.st_nlink != 1 or _identity(current) != identity
            or _identity(path.lstat()) != identity):
        raise ValueError('inventory archive source or object changed')


def _ref(ref: dict) -> dict:
    """Input: reference (dict). Output: independent exact validated archive reference (dict)."""
    if type(ref) is not dict or set(ref) != REF_KEYS:
        raise ValueError('invalid inventory archive reference keys')
    result = dict(ref)
    for name in ('sha256', 'uncompressed_sha256'):
        if type(result[name]) is not str or HEX_SHA.fullmatch(result[name]) is None:
            raise ValueError('invalid inventory archive hash')
    size = result['uncompressed_bytes']
    if type(size) is not int or not 0 <= size <= MAX_UNCOMPRESSED_BYTES:
        raise ValueError('invalid inventory archive uncompressed size')
    expected = 'machine/semantic_inventories/' + result['uncompressed_sha256'] + '/retired-inventory.jsonl.gz'
    if type(result['path']) is not str or result['path'] != expected:
        raise ValueError('invalid inventory archive namespace')
    return result


def _verify_handle(root: Path, path: Path, handle, ref: dict, deadline: float) -> None:
    """Input: pinned binary object and validated ref/deadline. Output: None; stream both proofs."""
    identity = _identity(os.fstat(handle.fileno()))
    if identity[2] > MAX_COMPRESSED_BYTES:
        raise ValueError('compressed inventory archive exceeds bound')
    if handle.read(10) != b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff':
        raise ValueError('invalid deterministic inventory gzip header or flags')
    handle.seek(0)
    digest = hashlib.sha256()
    compressed_bytes = 0
    while True:
        _tick(deadline)
        chunk = handle.read(CHUNK_BYTES)
        if not chunk:
            break
        compressed_bytes += len(chunk)
        if compressed_bytes > MAX_COMPRESSED_BYTES:
            raise ValueError('compressed inventory archive exceeds bound')
        digest.update(chunk)
    if digest.hexdigest() != ref['sha256']:
        raise ValueError('compressed inventory archive hash mismatch')
    handle.seek(0)
    digest = hashlib.sha256()
    size = 0
    try:
        with gzip.GzipFile(fileobj=handle, mode='rb') as reader:
            while True:
                _tick(deadline)
                chunk = reader.read(min(CHUNK_BYTES, ref['uncompressed_bytes'] - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > ref['uncompressed_bytes']:
                    raise ValueError('inventory archive exact size exceeded')
                digest.update(chunk)
    except (OSError, EOFError, zlib.error) as exc:
        raise ValueError('invalid gzip inventory archive') from exc
    if size != ref['uncompressed_bytes'] or digest.hexdigest() != ref['uncompressed_sha256']:
        raise ValueError('uncompressed inventory archive hash/size mismatch')
    _unchanged(root, path, handle, identity)
    _tick(deadline)
    handle.seek(0)


def verify_inventory_archive(root: Path, ref: dict, *, timeout_seconds=DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Input: vault root (Path), exact ref (dict), timeout (seconds). Output: verified proof (dict)."""
    deadline = _deadline(timeout_seconds)
    ref = _ref(ref)
    root = Path(os.path.abspath(root))
    path = root / ref['path']
    with _open(root, path) as handle:
        _verify_handle(root, path, handle, ref, deadline)
    return ref


class _BoundedCompressedReader:
    def __init__(self, root, path, handle, ref, deadline, identity):
        """Input: pinned file, identity, ref and deadline. Output: bounded compressed-byte reader."""
        self.root, self.path, self.handle = root, path, handle
        self.ref, self.deadline, self.identity = ref, deadline, identity
        self.digest = hashlib.sha256()
        self.size = 0

    def check(self):
        """Input: self. Output: None; enforce the original deadline and pinned file identity."""
        _tick(self.deadline)
        _unchanged(self.root, self.path, self.handle, self.identity)

    def read(self, size=-1):
        """Input: requested count (int). Output: bounded bytes; hash the exact second-pass input."""
        self.check()
        limit = min(CHUNK_BYTES, self.identity[2] - self.size + 1)
        if size >= 0:
            limit = min(limit, size)
        data = self.handle.read(limit)
        self.size += len(data)
        self.digest.update(data)
        self.check()
        if self.size > min(self.identity[2], MAX_COMPRESSED_BYTES):
            raise ValueError('compressed inventory archive exceeds bound')
        return data

    def finish(self):
        """Input: self. Output: None; require exact second-pass compressed hash and byte count."""
        self.check()
        if self.size != self.identity[2] or self.digest.hexdigest() != self.ref['sha256']:
            raise ValueError('consumed compressed inventory archive hash/size mismatch')


class _OwnedGzipReader(io.BufferedIOBase):
    def __init__(self, source):
        """Input: bounded compressed reader. Output: forward-only binary reader with consumption proof."""
        super().__init__()
        self._source = source
        self._gzip = gzip.GzipFile(fileobj=source, mode='rb')
        self._digest = hashlib.sha256()
        self._size = 0
        self._finished = False

    def _check(self):
        """Input: self. Output: None; reject closed, expired or changed streams before serving bytes."""
        if self.closed:
            raise ValueError('read of closed inventory archive')
        self._source.check()

    def _piece(self, size, line=False):
        """Input: byte limit (int), line mode (bool). Output: bounded, accounted decompressed bytes."""
        try:
            self._check()
            if self._finished:
                return b''
            expected = self._source.ref['uncompressed_bytes']
            limit = min(size, CHUNK_BYTES, expected - self._size + 1)
            data = self._gzip.readline(limit) if line else self._gzip.read(limit)
            self._check()
            self._size += len(data)
            self._digest.update(data)
            if self._size > min(expected, MAX_UNCOMPRESSED_BYTES):
                raise ValueError('consumed inventory archive exact size exceeded')
            if not data or self._size == expected:
                # Validate EOF before returning the last expected bytes, even on sized reads.
                if self._gzip.read(1):
                    raise ValueError('consumed inventory archive exact size exceeded')
                self._source.finish()
                if self._size != expected or self._digest.hexdigest() != self._source.ref['uncompressed_sha256']:
                    raise ValueError('consumed inventory archive hash/size mismatch')
                self._finished = True
            return data
        except (OSError, EOFError, zlib.error) as exc:
            self.close()
            raise ValueError('invalid consumed gzip inventory archive') from exc
        except BaseException:
            self.close()
            raise

    def read(self, size=-1):
        """Input: optional byte count (int). Output: bytes, consumed in bounded verified chunks."""
        self._check()
        size = -1 if size is None else operator.index(size)
        chunks = []
        remaining = size
        while remaining != 0:
            data = self._piece(CHUNK_BYTES if remaining < 0 else remaining)
            if not data:
                break
            chunks.append(data)
            if remaining > 0:
                remaining -= len(data)
        return b''.join(chunks)

    def read1(self, size=-1):
        """Input: byte count (int). Output: at most one bounded chunk of verified bytes."""
        size = operator.index(size)
        return self.read(CHUNK_BYTES if size < 0 else min(size, CHUNK_BYTES))

    def readinto(self, buffer):
        """Input: writable bytes-like buffer. Output: byte count (int), using the bounded read path."""
        view = memoryview(buffer).cast('B')
        data = self.read(len(view))
        view[:len(data)] = data
        return len(data)

    def readinto1(self, buffer):
        """Input: writable bytes-like buffer. Output: byte count (int), at most one chunk."""
        return self.readinto(memoryview(buffer).cast('B')[:CHUNK_BYTES])

    def readline(self, size=-1):
        """Input: optional line byte limit (int). Output: line bytes, with bounded internal reads."""
        self._check()
        size = -1 if size is None else operator.index(size)
        chunks = []
        remaining = size
        while remaining != 0:
            data = self._piece(CHUNK_BYTES if remaining < 0 else remaining, line=True)
            chunks.append(data)
            if not data or data.endswith(b'\n'):
                break
            if remaining > 0:
                remaining -= len(data)
        return b''.join(chunks)

    def readable(self):
        """Input: self. Output: bool; expose only forward binary consumption."""
        return not self.closed

    def close(self):
        """Input: self. Output: None; release both gzip buffering and its owned raw descriptor."""
        try:
            self._gzip.close()
        finally:
            self._source.handle.close()
            super().close()


def open_verified_inventory_archive(root: Path, ref: dict, *, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
    """Input: vault root/ref and timeout. Output: owned binary gzip reader of the verified descriptor."""
    deadline = _deadline(timeout_seconds)
    ref = _ref(ref)
    root = Path(os.path.abspath(root))
    path = root / ref['path']
    handle = _open(root, path)
    try:
        identity = _identity(os.fstat(handle.fileno()))
        _verify_handle(root, path, handle, ref, deadline)
        return _OwnedGzipReader(_BoundedCompressedReader(root, path, handle, ref, deadline, identity))
    except BaseException:
        handle.close()
        raise


def _publish_no_replace(temp: Path, target: Path) -> None:
    """Input: owned temp/target (Path). Output: None; atomically rename without a two-link window."""
    if os.name == 'nt':
        # Windows rename rejects an existing destination; POSIX os.rename would overwrite it.
        os.rename(temp, target)
        return
    import ctypes
    import sys

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        arguments = (-100, os.fsencode(temp), -100, os.fsencode(target), 1)
    elif sys.platform == 'darwin' and hasattr(libc, 'renamex_np'):
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        arguments = (os.fsencode(temp), os.fsencode(target), 4)
    else:
        raise OSError('atomic no-replace inventory publication unavailable')
    rename.restype = ctypes.c_int
    if rename(*arguments):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


def prepare_inventory_archive(root: Path, inventory_path: str, expected_sha256: str,
                              *, timeout_seconds=DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Input: root (Path), canonical source/hash (str), timeout. Output: immutable lossless ref (dict)."""
    deadline = _deadline(timeout_seconds)
    if type(inventory_path) is not str or SOURCE_PATH.fullmatch(inventory_path) is None:
        raise ValueError('inventory source must be canonical legacy plan-local inventory')
    if type(expected_sha256) is not str or HEX_SHA.fullmatch(expected_sha256) is None:
        raise ValueError('invalid expected inventory hash')
    root = Path(os.path.abspath(root))
    source = root / inventory_path
    relative = 'machine/semantic_inventories/' + expected_sha256 + '/retired-inventory.jsonl.gz'
    target = root / relative
    _safe(root, source)
    _safe(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _safe(root, target)
    lock = target.parent / '.retired-inventory.lock'
    _safe(root, lock)
    _safe(root, Path(str(lock) + '.guard'))
    _tick(deadline)
    with json_lock_transition_guard(lock, max(0.000001, deadline - time.monotonic()),
                                    LOCK_SLEEP_SECONDS, 'inventory archive object is busy'):
        _safe(root, Path(str(lock) + '.guard'))
        with _open(root, source) as handle:
            identity = _identity(os.fstat(handle.fileno()))
            if identity[2] > MAX_UNCOMPRESSED_BYTES:
                raise ValueError('inventory source exceeds bound')
            temp = target.parent / ('.retired-inventory.' + uuid.uuid4().hex + '.tmp')
            temp_identity = None
            try:
                _safe(root, temp)
                with temp.open('xb') as output:
                    temp_identity = os.fstat(output.fileno())
                    digest = hashlib.sha256()
                    size = 0
                    with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as writer:
                        while True:
                            _tick(deadline)
                            chunk = handle.read(CHUNK_BYTES)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > MAX_UNCOMPRESSED_BYTES:
                                raise ValueError('inventory source exceeds bound')
                            digest.update(chunk)
                            writer.write(chunk)
                            if output.tell() > MAX_COMPRESSED_BYTES:
                                raise ValueError('compressed inventory archive exceeds bound')
                    output.flush()
                    os.fsync(output.fileno())
                _unchanged(root, source, handle, identity)
                if size != identity[2] or digest.hexdigest() != expected_sha256:
                    raise ValueError('inventory source hash/size mismatch')
                # Hash compressed bytes separately, without retaining the source or gzip in memory.
                compressed = hashlib.sha256()
                with _open(root, temp) as compressed_file:
                    while True:
                        _tick(deadline)
                        chunk = compressed_file.read(CHUNK_BYTES)
                        if not chunk:
                            break
                        compressed.update(chunk)
                ref = dict(path=relative, sha256=compressed.hexdigest(),
                           uncompressed_sha256=expected_sha256, uncompressed_bytes=size)
                if os.path.lexists(target):
                    with _open(root, target) as existing:
                        _verify_handle(root, target, existing, ref, deadline)
                else:
                    _safe(root, target)
                    _tick(deadline)
                    _publish_no_replace(temp, target)
                    temp_identity = None
                    with _open(root, target) as published:
                        _verify_handle(root, target, published, ref, deadline)
                _unchanged(root, source, handle, identity)
                return ref
            finally:
                if temp_identity is not None and os.path.lexists(temp):
                    _safe(root, temp.parent)
                    current = temp.lstat()
                    if (not stat.S_ISLNK(current.st_mode)
                            and not getattr(current, 'st_file_attributes', 0) & 0x400
                            and (current.st_dev, current.st_ino) == (temp_identity.st_dev, temp_identity.st_ino)):
                        temp.unlink()
