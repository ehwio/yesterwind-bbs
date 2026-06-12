"""Tests for the files module — areas, file CRUD, xyzmodem transfers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yesterwind_bbs.auth import signup
from yesterwind_bbs.db.models import AccessLevel, Base
from yesterwind_bbs.files import (
    AreaNameTaken,
    AreaNotFound,
    DuplicateFilename,
    FileError,
    FileNotFound,
    PermissionDenied,
    create_area,
    delete_file,
    file_count,
    get_area,
    get_file,
    list_areas,
    list_files,
    read_file_bytes,
    register_file,
    send_file_xyzmodem,
    update_area,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def sysop(db_session):
    user = await signup(db_session, "sysoplord", "supersecret99")
    await db_session.commit()
    return user


@pytest.fixture
async def user(db_session, sysop):
    u = await signup(db_session, "regularjoe", "password123")
    u.access_level = AccessLevel.USER
    await db_session.commit()
    return u


@pytest.fixture
async def new_user(db_session, sysop):
    u = await signup(db_session, "newbie", "password123")
    await db_session.commit()
    return u


@pytest.fixture
async def area(db_session, sysop, tmp_path, monkeypatch):
    monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
    a = await create_area(db_session, "Games", "games", actor=sysop, description="Game files")
    await db_session.commit()
    return a


@pytest.fixture
async def file_entry(db_session, area, user, tmp_path, monkeypatch):
    monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
    entry = await register_file(
        db_session, area.id, "SuperGame.zip", b"fake zip content", actor=user
    )
    await db_session.commit()
    return entry


# ── Exception hierarchy ───────────────────────────────────────────────────────


class TestExceptions:
    def test_area_not_found_is_file_error(self):
        assert issubclass(AreaNotFound, FileError)

    def test_file_not_found_is_file_error(self):
        assert issubclass(FileNotFound, FileError)

    def test_permission_denied_is_file_error(self):
        assert issubclass(PermissionDenied, FileError)

    def test_area_name_taken_is_file_error(self):
        assert issubclass(AreaNameTaken, FileError)

    def test_duplicate_filename_is_file_error(self):
        assert issubclass(DuplicateFilename, FileError)


# ── create_area ───────────────────────────────────────────────────────────────


class TestCreateArea:
    async def test_sysop_creates_area(self, db_session, sysop, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        a = await create_area(db_session, "Utilities", "utils", actor=sysop)
        assert a.id is not None
        assert a.name == "Utilities"
        assert a.is_active is True

    async def test_creates_directory(self, db_session, sysop, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        await create_area(db_session, "Demo Files", "demos", actor=sysop)
        assert (tmp_path / "demos").is_dir()

    async def test_non_sysop_cannot_create(self, db_session, user, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        with pytest.raises(PermissionDenied):
            await create_area(db_session, "Rebels", "rebels", actor=user)

    async def test_duplicate_name_raises(self, db_session, sysop, area, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        with pytest.raises(AreaNameTaken):
            await create_area(db_session, "Games", "games2", actor=sysop)

    async def test_duplicate_name_case_insensitive(
        self, db_session, sysop, area, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        with pytest.raises(AreaNameTaken):
            await create_area(db_session, "GAMES", "games2", actor=sysop)

    async def test_whitespace_stripped(self, db_session, sysop, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        a = await create_area(db_session, "  Padded  ", "padded", actor=sysop)
        assert a.name == "Padded"

    async def test_custom_levels(self, db_session, sysop, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        a = await create_area(
            db_session,
            "Sysop Files",
            "sysop",
            actor=sysop,
            read_level=AccessLevel.SYSOP,
            upload_level=AccessLevel.SYSOP,
        )
        assert a.read_level == AccessLevel.SYSOP
        assert a.upload_level == AccessLevel.SYSOP


# ── list_areas ────────────────────────────────────────────────────────────────


class TestListAreas:
    async def test_user_sees_user_areas(self, db_session, user, area):
        areas = await list_areas(db_session, user)
        assert any(a.id == area.id for a in areas)

    async def test_user_cannot_see_sysop_area(self, db_session, sysop, user, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        sysop_area = await create_area(
            db_session,
            "Sysop Only",
            "sysop",
            actor=sysop,
            read_level=AccessLevel.SYSOP,
        )
        await db_session.commit()
        areas = await list_areas(db_session, user)
        assert not any(a.id == sysop_area.id for a in areas)

    async def test_sysop_sees_all(self, db_session, sysop, area, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        sysop_area = await create_area(
            db_session,
            "Sysop Only",
            "sysop",
            actor=sysop,
            read_level=AccessLevel.SYSOP,
        )
        await db_session.commit()
        areas = await list_areas(db_session, sysop)
        ids = {a.id for a in areas}
        assert area.id in ids
        assert sysop_area.id in ids

    async def test_inactive_hidden(self, db_session, user, area):
        area.is_active = False
        await db_session.commit()
        areas = await list_areas(db_session, user)
        assert not any(a.id == area.id for a in areas)


# ── get_area ──────────────────────────────────────────────────────────────────


class TestGetArea:
    async def test_returns_area(self, db_session, user, area):
        a = await get_area(db_session, area.id, user)
        assert a.id == area.id

    async def test_inactive_raises(self, db_session, user, area):
        area.is_active = False
        await db_session.commit()
        with pytest.raises(AreaNotFound):
            await get_area(db_session, area.id, user)

    async def test_missing_raises(self, db_session, user):
        with pytest.raises(AreaNotFound):
            await get_area(db_session, 9999, user)

    async def test_below_read_level_raises(self, db_session, new_user, area):
        with pytest.raises(PermissionDenied):
            await get_area(db_session, area.id, new_user)


# ── update_area ───────────────────────────────────────────────────────────────


class TestUpdateArea:
    async def test_rename(self, db_session, sysop, area):
        a = await update_area(db_session, area.id, actor=sysop, name="Renamed")
        assert a.name == "Renamed"

    async def test_deactivate(self, db_session, sysop, area):
        a = await update_area(db_session, area.id, actor=sysop, is_active=False)
        assert a.is_active is False

    async def test_duplicate_name_raises(self, db_session, sysop, area, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        await create_area(db_session, "Other", "other", actor=sysop)
        await db_session.commit()
        with pytest.raises(AreaNameTaken):
            await update_area(db_session, area.id, actor=sysop, name="Other")

    async def test_same_name_allowed(self, db_session, sysop, area):
        a = await update_area(db_session, area.id, actor=sysop, name="Games")
        assert a.name == "Games"

    async def test_non_sysop_cannot_update(self, db_session, user, area):
        with pytest.raises(PermissionDenied):
            await update_area(db_session, area.id, actor=user, name="Hijacked")

    async def test_missing_raises(self, db_session, sysop):
        with pytest.raises(AreaNotFound):
            await update_area(db_session, 9999, actor=sysop, name="Ghost")


# ── register_file ─────────────────────────────────────────────────────────────


class TestRegisterFile:
    async def test_creates_entry_and_file(self, db_session, area, user, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        data = b"hello world"
        entry = await register_file(db_session, area.id, "test.txt", data, actor=user)
        assert entry.id is not None
        assert entry.display_name == "test.txt"
        assert entry.size_bytes == len(data)
        assert entry.sha256 is not None
        assert (tmp_path / area.path / entry.stored_name).exists()

    async def test_increments_files_uploaded(self, db_session, area, user, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        before = user.files_uploaded
        await register_file(db_session, area.id, "inc.bin", b"data", actor=user)
        assert user.files_uploaded == before + 1

    async def test_increments_bytes_uploaded(self, db_session, area, user, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        data = b"x" * 512
        before = user.bytes_uploaded
        await register_file(db_session, area.id, "big.bin", data, actor=user)
        assert user.bytes_uploaded == before + 512

    async def test_below_upload_level_denied(
        self, db_session, area, new_user, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        with pytest.raises(PermissionDenied):
            await register_file(db_session, area.id, "fail.bin", b"x", actor=new_user)

    async def test_duplicate_display_name_raises(
        self, db_session, area, user, file_entry, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        with pytest.raises(DuplicateFilename):
            await register_file(db_session, area.id, "SuperGame.zip", b"other", actor=user)

    async def test_duplicate_display_name_case_insensitive(
        self, db_session, area, user, file_entry, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        with pytest.raises(DuplicateFilename):
            await register_file(db_session, area.id, "SUPERGAME.ZIP", b"other", actor=user)

    async def test_stored_name_uses_uuid(self, db_session, area, user, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        entry = await register_file(db_session, area.id, "original.zip", b"data", actor=user)
        assert entry.stored_name != "original.zip"
        assert entry.stored_name.endswith(".zip")

    async def test_sha256_correct(self, db_session, area, user, tmp_path, monkeypatch):
        import hashlib

        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        data = b"checksum me"
        entry = await register_file(db_session, area.id, "check.bin", data, actor=user)
        assert entry.sha256 == hashlib.sha256(data).hexdigest()

    async def test_missing_area_raises(self, db_session, user, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        with pytest.raises(AreaNotFound):
            await register_file(db_session, 9999, "x.bin", b"x", actor=user)


# ── list_files ────────────────────────────────────────────────────────────────


class TestListFiles:
    async def test_returns_active_files(self, db_session, area, user, file_entry):
        files = await list_files(db_session, area.id, user)
        assert any(f.id == file_entry.id for f in files)

    async def test_inactive_excluded(self, db_session, area, user, file_entry):
        file_entry.is_active = False
        await db_session.commit()
        files = await list_files(db_session, area.id, user)
        assert not any(f.id == file_entry.id for f in files)

    async def test_access_check(self, db_session, area, new_user):
        with pytest.raises(PermissionDenied):
            await list_files(db_session, area.id, new_user)

    async def test_pagination(self, db_session, area, user, tmp_path, monkeypatch):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        for i in range(5):
            await register_file(
                db_session, area.id, f"file{i}.bin", f"data{i}".encode(), actor=user
            )
        await db_session.commit()

        page1 = await list_files(db_session, area.id, user, limit=3, offset=0)
        page2 = await list_files(db_session, area.id, user, limit=3, offset=3)
        assert len(page1) == 3
        ids1 = {f.id for f in page1}
        ids2 = {f.id for f in page2}
        assert ids1.isdisjoint(ids2)


# ── get_file ──────────────────────────────────────────────────────────────────


class TestGetFile:
    async def test_returns_entry(self, db_session, area, user, file_entry):
        f = await get_file(db_session, file_entry.id, user)
        assert f.id == file_entry.id

    async def test_inactive_raises(self, db_session, area, user, file_entry):
        file_entry.is_active = False
        await db_session.commit()
        with pytest.raises(FileNotFound):
            await get_file(db_session, file_entry.id, user)

    async def test_missing_raises(self, db_session, user):
        with pytest.raises(FileNotFound):
            await get_file(db_session, 9999, user)


# ── delete_file ───────────────────────────────────────────────────────────────


class TestDeleteFile:
    async def test_sysop_can_delete(
        self, db_session, area, sysop, file_entry, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        deleted = await delete_file(db_session, file_entry.id, actor=sysop)
        assert deleted.is_active is False

    async def test_file_removed_from_disk(
        self, db_session, area, sysop, file_entry, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        disk_path = tmp_path / area.path / file_entry.stored_name
        assert disk_path.exists()
        await delete_file(db_session, file_entry.id, actor=sysop)
        assert not disk_path.exists()

    async def test_keep_on_disk_flag(
        self, db_session, area, sysop, file_entry, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        disk_path = tmp_path / area.path / file_entry.stored_name
        await delete_file(db_session, file_entry.id, actor=sysop, remove_from_disk=False)
        assert disk_path.exists()

    async def test_regular_user_cannot_delete(self, db_session, area, user, file_entry):
        with pytest.raises(PermissionDenied):
            await delete_file(db_session, file_entry.id, actor=user)

    async def test_already_deleted_raises(
        self, db_session, area, sysop, file_entry, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        await delete_file(db_session, file_entry.id, actor=sysop)
        await db_session.commit()
        with pytest.raises(FileNotFound):
            await delete_file(db_session, file_entry.id, actor=sysop)


# ── read_file_bytes ───────────────────────────────────────────────────────────


class TestReadFileBytes:
    async def test_returns_correct_bytes(
        self, db_session, area, user, file_entry, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        entry, data = await read_file_bytes(db_session, file_entry.id, user)
        assert data == b"fake zip content"
        assert entry.id == file_entry.id

    async def test_increments_download_count(
        self, db_session, area, user, file_entry, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        before = file_entry.download_count
        await read_file_bytes(db_session, file_entry.id, user)
        assert file_entry.download_count == before + 1

    async def test_increments_user_stats(
        self, db_session, area, user, file_entry, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))
        before_count = user.files_downloaded
        before_bytes = user.bytes_downloaded
        await read_file_bytes(db_session, file_entry.id, user)
        assert user.files_downloaded == before_count + 1
        assert user.bytes_downloaded == before_bytes + len(b"fake zip content")


# ── file_count ────────────────────────────────────────────────────────────────


class TestFileCount:
    async def test_counts_active(self, db_session, area, file_entry):
        assert await file_count(db_session, area.id) == 1

    async def test_excludes_inactive_by_default(self, db_session, area, file_entry):
        file_entry.is_active = False
        await db_session.commit()
        assert await file_count(db_session, area.id) == 0

    async def test_include_inactive_flag(self, db_session, area, file_entry):
        file_entry.is_active = False
        await db_session.commit()
        assert await file_count(db_session, area.id, include_inactive=True) == 1


# ── xyzmodem transfers ────────────────────────────────────────────────────────


class _QueueTransport:
    """Minimal async queue-backed transport for in-process protocol testing."""

    def __init__(self, tx: asyncio.Queue, rx: asyncio.Queue) -> None:
        self._tx = tx
        self._rx = rx

    async def read(self, n: int) -> bytes:
        out = bytearray()
        for _ in range(n):
            out.append(await self._rx.get())
        return bytes(out)

    async def read_byte(self) -> int:
        return await self._rx.get()

    async def write(self, data: bytes) -> None:
        for b in data:
            await self._tx.put(b)

    async def read_with_timeout(self, n: int, timeout: float) -> bytes:
        return await asyncio.wait_for(self.read(n), timeout=timeout)

    async def read_byte_with_timeout(self, timeout: float) -> int:
        return await asyncio.wait_for(self.read_byte(), timeout=timeout)

    async def purge(self) -> None:
        while not self._rx.empty():
            self._rx.get_nowait()


def _piped_transports():
    """Return (side_a, side_b) — bytes written to A emerge from B and vice versa."""
    a_to_b: asyncio.Queue = asyncio.Queue()
    b_to_a: asyncio.Queue = asyncio.Queue()
    return _QueueTransport(a_to_b, b_to_a), _QueueTransport(b_to_a, a_to_b)


class TestXyzmodemTransfers:
    async def test_send_and_receive_zmodem(
        self, db_session, sysop, area, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("yesterwind_bbs.files.config.FILES_DIR", str(tmp_path))

        from yesterwind_xyzmodem import ZModem

        data = b"Hello from BBS via ZModem!" * 10
        entry = await register_file(db_session, area.id, "hello.bin", data, actor=sysop)
        await db_session.commit()

        # bbs_transport = BBS side (sender); remote_transport = caller side (receiver)
        bbs_transport, remote_transport = _piped_transports()

        async def _bbs_send():
            import io as _io

            zm = ZModem(bbs_transport)
            return await zm.send([(entry.display_name, _io.BytesIO(data), len(data))])

        async def _remote_receive():
            zm = ZModem(remote_transport)
            return await zm.receive(output_dir=str(tmp_path / "recv"))

        (tmp_path / "recv").mkdir()
        sent_bytes, received_names = await asyncio.gather(_bbs_send(), _remote_receive())

        assert sent_bytes > 0
        assert len(received_names) == 1
        received_data = (Path(received_names[0])).read_bytes()
        assert received_data == data

    async def test_send_missing_file_raises(self, db_session, sysop, area):
        with pytest.raises(FileNotFound):
            # Error fires before any I/O — safe to pass None for streams
            await send_file_xyzmodem(
                db_session, 9999, sysop, None, None, protocol="zmodem"
            )
