"""
File area CRUD and xyzmodem transfer helpers.

On-disk layout (relative to config.FILES_DIR):
  <area.path>/<stored_name>

stored_name is always a UUID4 + original extension to avoid collisions.
The original filename shown to callers is FileEntry.display_name.

Transfer integration:
  send_file()    — wraps ZModem.send (falls back to YModem / XModem per caller choice)
  receive_file() — wraps ZModem.receive, then registers the resulting file
"""

from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yesterwind_bbs import config
from yesterwind_bbs.db.models import AccessLevel, FileArea, FileEntry, User

# ── Exceptions ────────────────────────────────────────────────────────────────


class FileError(Exception):
    """Base class for all file-layer errors."""


class AreaNotFound(FileError):
    """Raised when a file area does not exist or is inactive."""


class FileNotFound(FileError):
    """Raised when a FileEntry does not exist or is inactive."""


class PermissionDenied(FileError):
    """Raised when the caller lacks sufficient access."""


class AreaNameTaken(FileError):
    """Raised when an area with that name already exists."""


class DuplicateFilename(FileError):
    """Raised when display_name already exists in this area."""


# ── Internal helpers ──────────────────────────────────────────────────────────


def _files_root() -> Path:
    return Path(config.FILES_DIR)


def _area_dir(area: FileArea) -> Path:
    return _files_root() / area.path


def _stored_name(display_name: str) -> str:
    suffix = Path(display_name).suffix
    return f"{uuid.uuid4().hex}{suffix}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Area operations ───────────────────────────────────────────────────────────


async def list_areas(
    session: AsyncSession,
    actor: User,
) -> list[FileArea]:
    """Return all active areas the actor has at least read access to."""
    result = await session.execute(
        select(FileArea)
        .where(
            FileArea.is_active == True,  # noqa: E712
            FileArea.read_level <= actor.access_level,
        )
        .order_by(FileArea.sort_order, FileArea.name)
    )
    return list(result.scalars().all())


async def get_area(
    session: AsyncSession,
    area_id: int,
    actor: User,
) -> FileArea:
    """
    Fetch a single active area by id.

    Raises:
        AreaNotFound     — area doesn't exist or is inactive
        PermissionDenied — actor is below read_level
    """
    result = await session.execute(select(FileArea).where(FileArea.id == area_id))
    area = result.scalar_one_or_none()
    if area is None or not area.is_active:
        raise AreaNotFound(f"File area {area_id} not found.")
    if actor.access_level < area.read_level:
        raise PermissionDenied("You do not have access to this file area.")
    return area


async def create_area(
    session: AsyncSession,
    name: str,
    path: str,
    *,
    actor: User,
    description: str | None = None,
    read_level: int = AccessLevel.USER,
    upload_level: int = AccessLevel.USER,
    sort_order: int = 0,
) -> FileArea:
    """
    Create a new file area. Only sysops may create areas.
    The on-disk directory is created immediately.

    Raises:
        PermissionDenied — actor is not a sysop
        AreaNameTaken    — an area with that name already exists
    """
    if not actor.is_sysop:
        raise PermissionDenied("Only sysops can create file areas.")

    name = name.strip()
    existing = await session.execute(
        select(FileArea).where(func.lower(FileArea.name) == name.lower())
    )
    if existing.scalar_one_or_none() is not None:
        raise AreaNameTaken(f"A file area named '{name}' already exists.")

    area = FileArea(
        name=name,
        path=path,
        description=description,
        read_level=read_level,
        upload_level=upload_level,
        sort_order=sort_order,
    )
    session.add(area)
    await session.flush()

    _area_dir(area).mkdir(parents=True, exist_ok=True)
    return area


async def update_area(
    session: AsyncSession,
    area_id: int,
    *,
    actor: User,
    name: str | None = None,
    description: str | None = None,
    read_level: int | None = None,
    upload_level: int | None = None,
    sort_order: int | None = None,
    is_active: bool | None = None,
) -> FileArea:
    """
    Update area metadata. Only sysops may update areas.

    Raises:
        PermissionDenied — actor is not a sysop
        AreaNotFound     — area doesn't exist
        AreaNameTaken    — new name conflicts with existing area
    """
    if not actor.is_sysop:
        raise PermissionDenied("Only sysops can update file areas.")

    result = await session.execute(select(FileArea).where(FileArea.id == area_id))
    area = result.scalar_one_or_none()
    if area is None:
        raise AreaNotFound(f"File area {area_id} not found.")

    if name is not None:
        name = name.strip()
        conflict = await session.execute(
            select(FileArea).where(
                func.lower(FileArea.name) == name.lower(),
                FileArea.id != area_id,
            )
        )
        if conflict.scalar_one_or_none() is not None:
            raise AreaNameTaken(f"A file area named '{name}' already exists.")
        area.name = name

    if description is not None:
        area.description = description
    if read_level is not None:
        area.read_level = read_level
    if upload_level is not None:
        area.upload_level = upload_level
    if sort_order is not None:
        area.sort_order = sort_order
    if is_active is not None:
        area.is_active = is_active

    await session.flush()
    return area


# ── File listing ──────────────────────────────────────────────────────────────


async def list_files(
    session: AsyncSession,
    area_id: int,
    actor: User,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[FileEntry]:
    """
    Return active FileEntry rows in an area, newest first.

    Raises:
        AreaNotFound     — area doesn't exist or is inactive
        PermissionDenied — actor below read_level
    """
    await get_area(session, area_id, actor)

    result = await session.execute(
        select(FileEntry)
        .where(
            FileEntry.area_id == area_id,
            FileEntry.is_active == True,  # noqa: E712
        )
        .order_by(FileEntry.uploaded_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_file(
    session: AsyncSession,
    file_id: int,
    actor: User,
) -> FileEntry:
    """
    Fetch a single active FileEntry.

    Raises:
        FileNotFound     — entry doesn't exist or is inactive
        AreaNotFound     — parent area is inactive
        PermissionDenied — actor below area's read_level
    """
    result = await session.execute(select(FileEntry).where(FileEntry.id == file_id))
    entry = result.scalar_one_or_none()
    if entry is None or not entry.is_active:
        raise FileNotFound(f"File {file_id} not found.")
    await get_area(session, entry.area_id, actor)
    return entry


# ── Register an already-present file (sysop import / post-upload) ─────────────


async def register_file(
    session: AsyncSession,
    area_id: int,
    display_name: str,
    data: bytes,
    *,
    actor: User,
    description: str | None = None,
) -> FileEntry:
    """
    Write *data* to disk and create a FileEntry row.

    Used by the sysop import flow and by receive_file() after a successful
    xyzmodem transfer. The area must be active and the actor must have at
    least upload_level access.

    Raises:
        AreaNotFound     — area doesn't exist or is inactive
        PermissionDenied — actor below upload_level
        DuplicateFilename — display_name already exists in this area
    """
    result = await session.execute(select(FileArea).where(FileArea.id == area_id))
    area = result.scalar_one_or_none()
    if area is None or not area.is_active:
        raise AreaNotFound(f"File area {area_id} not found.")
    if actor.access_level < area.upload_level:
        raise PermissionDenied("You do not have permission to upload to this area.")

    # Case-insensitive duplicate check within the area
    dup = await session.execute(
        select(FileEntry).where(
            FileEntry.area_id == area_id,
            func.lower(FileEntry.display_name) == display_name.strip().lower(),
            FileEntry.is_active == True,  # noqa: E712
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise DuplicateFilename(f"A file named '{display_name}' already exists in this area.")

    stored = _stored_name(display_name)
    dest = _area_dir(area) / stored
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    entry = FileEntry(
        area_id=area_id,
        uploader_id=actor.id,
        stored_name=stored,
        display_name=display_name.strip(),
        description=description,
        size_bytes=len(data),
        sha256=_sha256(data),
    )
    session.add(entry)
    actor.files_uploaded += 1
    actor.bytes_uploaded += len(data)
    await session.flush()
    return entry


async def delete_file(
    session: AsyncSession,
    file_id: int,
    *,
    actor: User,
    remove_from_disk: bool = True,
) -> FileEntry:
    """
    Soft-delete a FileEntry. Only sysops may delete files.
    Pass remove_from_disk=False to keep the physical file (useful for auditing).

    Raises:
        FileNotFound     — entry doesn't exist or already inactive
        PermissionDenied — actor is not a sysop
    """
    if not actor.is_sysop:
        raise PermissionDenied("Only sysops can delete files.")

    result = await session.execute(select(FileEntry).where(FileEntry.id == file_id))
    entry = result.scalar_one_or_none()
    if entry is None or not entry.is_active:
        raise FileNotFound(f"File {file_id} not found.")

    entry.is_active = False
    await session.flush()

    if remove_from_disk:
        area_result = await session.execute(select(FileArea).where(FileArea.id == entry.area_id))
        area = area_result.scalar_one_or_none()
        if area is not None:
            path = _area_dir(area) / entry.stored_name
            path.unlink(missing_ok=True)

    return entry


# ── Download helper ───────────────────────────────────────────────────────────


async def read_file_bytes(
    session: AsyncSession,
    file_id: int,
    actor: User,
) -> tuple[FileEntry, bytes]:
    """
    Return the FileEntry and its raw bytes, incrementing download_count.

    Raises:
        FileNotFound     — entry doesn't exist or is inactive
        AreaNotFound     — parent area is inactive
        PermissionDenied — actor below area's read_level
    """
    entry = await get_file(session, file_id, actor)

    area_result = await session.execute(select(FileArea).where(FileArea.id == entry.area_id))
    area = area_result.scalar_one()
    path = _area_dir(area) / entry.stored_name

    data = path.read_bytes()
    entry.download_count += 1
    actor.files_downloaded += 1
    actor.bytes_downloaded += len(data)
    await session.flush()
    return entry, data


# ── xyzmodem transfer integration ────────────────────────────────────────────


async def send_file_xyzmodem(
    session: AsyncSession,
    file_id: int,
    actor: User,
    reader,
    writer,
    *,
    protocol: str = "zmodem",
) -> int:
    """
    Send a file to the remote caller via xyzmodem.

    protocol: "zmodem" (default), "ymodem", or "xmodem"
    Returns the number of bytes sent.

    Raises:
        FileNotFound / AreaNotFound / PermissionDenied — via read_file_bytes
    """
    from yesterwind_xyzmodem import XModem, YModem, ZModem
    from yesterwind_xyzmodem.transport import StreamTransport

    entry, data = await read_file_bytes(session, file_id, actor)
    transport = StreamTransport(reader, writer)
    proto = protocol.lower()

    if proto == "zmodem":
        zm = ZModem(transport)
        return await zm.send([(entry.display_name, io.BytesIO(data), len(data))])
    elif proto == "ymodem":
        ym = YModem(transport)
        return await ym.send([(entry.display_name, io.BytesIO(data), len(data))])
    else:
        xm = XModem(transport)
        return await xm.send(io.BytesIO(data), entry.display_name, len(data))


async def receive_file_xyzmodem(
    session: AsyncSession,
    area_id: int,
    actor: User,
    reader,
    writer,
    *,
    protocol: str = "zmodem",
    description: str | None = None,
) -> list[FileEntry]:
    """
    Receive one or more files from the remote caller via xyzmodem and
    register them in the given area.

    protocol: "zmodem" (default), "ymodem", or "xmodem"
    For xmodem, a single unnamed file is expected; the caller must pass
    display_name via description (used as fallback name "upload.bin").

    Returns the list of created FileEntry rows.

    Raises:
        AreaNotFound / PermissionDenied — via register_file
    """
    import tempfile

    from yesterwind_xyzmodem import XModem, YModem, ZModem
    from yesterwind_xyzmodem.transport import StreamTransport

    transport = StreamTransport(reader, writer)
    proto = protocol.lower()

    entries: list[FileEntry] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        if proto == "zmodem":
            zm = ZModem(transport)
            received = await zm.receive(output_dir=tmpdir)
        elif proto == "ymodem":
            ym = YModem(transport)
            received = await ym.receive(output_dir=tmpdir)
        else:
            # XModem: single file, no filename in protocol
            xm = XModem(transport)
            tmp_path = Path(tmpdir) / "upload.bin"
            with tmp_path.open("wb") as fh:
                await xm.receive(fh)
            received = [str(tmp_path)]

        for filepath in received:
            p = Path(filepath)
            data = p.read_bytes()
            display = p.name
            entry = await register_file(
                session,
                area_id,
                display,
                data,
                actor=actor,
                description=description,
            )
            entries.append(entry)

    return entries


# ── Sysop import helpers ──────────────────────────────────────────────────────


async def register_existing_file(
    session: AsyncSession,
    area_id: int,
    disk_path: Path,
    *,
    description: str | None = None,
) -> FileEntry:
    """
    Register a file that already lives on disk inside the area directory.

    Unlike register_file(), the file is not copied or renamed — disk_path
    must already be under _area_dir(area). display_name and stored_name are
    both set to disk_path.name. uploader_id is left NULL (sysop import).

    Raises:
        AreaNotFound      — area doesn't exist or is inactive
        DuplicateFilename — display_name already registered in this area
    """
    result = await session.execute(select(FileArea).where(FileArea.id == area_id))
    area = result.scalar_one_or_none()
    if area is None or not area.is_active:
        raise AreaNotFound(f"File area {area_id} not found.")

    display = disk_path.name
    dup = await session.execute(
        select(FileEntry).where(
            FileEntry.area_id == area_id,
            FileEntry.display_name == display,
            FileEntry.is_active == True,  # noqa: E712
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise DuplicateFilename(f"'{display}' is already registered in this area.")

    data = disk_path.read_bytes()
    entry = FileEntry(
        area_id=area_id,
        uploader_id=None,
        stored_name=display,
        display_name=display,
        description=description,
        size_bytes=len(data),
        sha256=_sha256(data),
    )
    session.add(entry)
    await session.flush()
    return entry


async def scan_area_dir(
    session: AsyncSession,
    area_id: int,
) -> tuple[list[Path], list[FileEntry]]:
    """
    Compare the area's directory against the database.

    Returns:
        new_files    — paths on disk with no active FileEntry
        gone_entries — active FileEntry rows whose stored_name no longer exists on disk
    """
    result = await session.execute(select(FileArea).where(FileArea.id == area_id))
    area = result.scalar_one_or_none()
    if area is None:
        raise AreaNotFound(f"File area {area_id} not found.")

    area_dir = _area_dir(area)
    disk_files: set[str] = set()
    if area_dir.is_dir():
        disk_files = {p.name for p in area_dir.iterdir() if p.is_file()}

    db_result = await session.execute(
        select(FileEntry).where(
            FileEntry.area_id == area_id,
            FileEntry.is_active == True,  # noqa: E712
        )
    )
    db_entries = list(db_result.scalars().all())
    db_names = {e.stored_name for e in db_entries}

    new_files = [area_dir / name for name in sorted(disk_files - db_names)]
    gone_entries = [e for e in db_entries if e.stored_name not in disk_files]
    return new_files, gone_entries


# ── Sysop convenience ─────────────────────────────────────────────────────────


async def file_count(
    session: AsyncSession,
    area_id: int,
    *,
    include_inactive: bool = False,
) -> int:
    """Return the number of files in an area."""
    conditions = [FileEntry.area_id == area_id]
    if not include_inactive:
        conditions.append(FileEntry.is_active == True)  # noqa: E712
    result = await session.execute(select(func.count()).select_from(FileEntry).where(*conditions))
    return result.scalar_one()
