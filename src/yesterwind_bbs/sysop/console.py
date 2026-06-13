"""
Sysop management console.

Run via `bbs-sysop` or `docker exec -it bbs bbs-sysop`.

Navigation is keyboard-driven; no mouse required.  All destructive
operations prompt for confirmation before committing.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from yesterwind_bbs import config
from yesterwind_bbs.auth import (
    AuthError,
    InvalidCredentials,
    hash_password,
    login,
    validate_password,
)
from yesterwind_bbs.db.engine import get_session, init_db
from yesterwind_bbs.db.models import AccessLevel, User
from yesterwind_bbs.files import (
    AreaNotFound,
    FileError,
    create_area,
    file_count,
    get_area,
    list_areas,
    update_area,
)
from yesterwind_bbs.messages import (
    BoardNotFound,
    MessageError,
    create_board,
    get_board,
    list_boards,
    message_count,
    update_board,
)

console = Console()


# ── Small helpers ─────────────────────────────────────────────────────────────


def _header(title: str) -> None:
    console.print(Panel(f"[bold cyan]{title}[/]", expand=False))


def _success(msg: str) -> None:
    console.print(f"[bold green]✓[/] {msg}")


def _error(msg: str) -> None:
    console.print(f"[bold red]✗[/] {msg}")


def _warn(msg: str) -> None:
    console.print(f"[bold yellow]![/] {msg}")


def _fmt_level(level: int) -> str:
    if level >= AccessLevel.SYSOP:
        return f"[bold red]SYSOP ({level})[/]"
    elif level >= AccessLevel.USER:
        return f"[green]USER ({level})[/]"
    else:
        return f"[dim]NEW ({level})[/]"


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "[dim]never[/]"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


# ── Authentication ────────────────────────────────────────────────────────────


async def _authenticate() -> User | None:
    """Prompt for sysop credentials. Returns the User or None on failure."""
    console.print()
    console.print(
        Panel(
            f"[bold cyan]{config.BBS_NAME}[/]\n[dim]Sysop Console[/]",
            expand=False,
        )
    )
    console.print()

    for attempt in range(3):
        username = Prompt.ask("[cyan]Username[/]")
        password = Prompt.ask("[cyan]Password[/]", password=True)
        try:
            async with get_session() as session:
                user = await login(session, username, password)
            if not user.is_sysop:
                _error("That account does not have sysop access.")
                return None
            return user
        except InvalidCredentials:
            _error(f"Invalid credentials. {2 - attempt} attempt(s) remaining.")
        except AuthError as exc:
            _error(str(exc))
            return None
    return None


# ── User management ───────────────────────────────────────────────────────────


async def _users_menu(actor: User) -> None:
    while True:
        _header("User Management")
        console.print("[1] List users")
        console.print("[2] Find user")
        console.print("[3] Set access level")
        console.print("[4] Activate / deactivate account")
        console.print("[5] Reset password")
        console.print("[B] Back")
        choice = Prompt.ask("Choice").strip().upper()

        if choice == "1":
            await _list_users()
        elif choice == "2":
            await _find_user()
        elif choice == "3":
            await _set_access_level(actor)
        elif choice == "4":
            await _toggle_active(actor)
        elif choice == "5":
            await _reset_password(actor)
        elif choice == "B":
            return


async def _list_users(*, search: str | None = None) -> None:
    from sqlalchemy import func, select

    from yesterwind_bbs.db.models import User as UserModel

    async with get_session() as session:
        q = select(UserModel).order_by(UserModel.access_level.desc(), UserModel.username)
        if search:
            q = q.where(func.lower(UserModel.username).contains(search.lower()))
        result = await session.execute(q)
        users = list(result.scalars().all())

    if not users:
        _warn("No users found.")
        return

    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("ID", style="dim", width=5)
    t.add_column("Username", min_width=16)
    t.add_column("Level", min_width=14)
    t.add_column("Active", width=7)
    t.add_column("Logins", width=7)
    t.add_column("Last login")
    t.add_column("Email")

    for u in users:
        t.add_row(
            str(u.id),
            u.username,
            Text.from_markup(_fmt_level(u.access_level)),
            "[green]yes[/]" if u.is_active else "[red]no[/]",
            str(u.login_count),
            Text.from_markup(_fmt_dt(u.last_login_at)),
            u.email or "[dim]-[/]",
        )
    console.print(t)


async def _find_user() -> None:
    term = Prompt.ask("Search username (partial OK)")
    await _list_users(search=term)


async def _get_user_by_name(prompt: str = "Username") -> User | None:
    from sqlalchemy import func, select

    from yesterwind_bbs.db.models import User as UserModel

    name = Prompt.ask(prompt)
    async with get_session() as session:
        result = await session.execute(
            select(UserModel).where(func.lower(UserModel.username) == name.strip().lower())
        )
        user = result.scalar_one_or_none()
    if user is None:
        _error(f"User '{name}' not found.")
    return user


async def _set_access_level(actor: User) -> None:
    user = await _get_user_by_name()
    if user is None:
        return

    console.print(f"Current level: {_fmt_level(user.access_level)}")
    console.print(f"  [1] NEW    ({AccessLevel.NEW})")
    console.print(f"  [2] USER   ({AccessLevel.USER})")
    console.print(f"  [3] SYSOP  ({AccessLevel.SYSOP})")
    console.print("  [C] Custom integer")
    choice = Prompt.ask("New level").strip().upper()

    level_map = {"1": AccessLevel.NEW, "2": AccessLevel.USER, "3": AccessLevel.SYSOP}
    if choice in level_map:
        new_level = level_map[choice]
    elif choice == "C":
        new_level = IntPrompt.ask("Enter custom access level")
    else:
        _warn("Cancelled.")
        return

    if not Confirm.ask(f"Set [bold]{user.username}[/] to level {new_level}?"):
        _warn("Cancelled.")
        return

    async with get_session() as session:
        from sqlalchemy import select

        from yesterwind_bbs.db.models import User as UserModel

        result = await session.execute(select(UserModel).where(UserModel.id == user.id))
        live_user = result.scalar_one()
        live_user.access_level = new_level

    _success(f"{user.username} access level set to {new_level}.")


async def _toggle_active(actor: User) -> None:
    user = await _get_user_by_name()
    if user is None:
        return

    state = "active" if user.is_active else "inactive"
    action = "deactivate" if user.is_active else "activate"
    console.print(f"Account is currently [bold]{state}[/].")

    if not Confirm.ask(f"[bold]{action.capitalize()}[/] {user.username}?"):
        _warn("Cancelled.")
        return

    async with get_session() as session:
        from sqlalchemy import select

        from yesterwind_bbs.db.models import User as UserModel

        result = await session.execute(select(UserModel).where(UserModel.id == user.id))
        live_user = result.scalar_one()
        live_user.is_active = not live_user.is_active

    _success(f"{user.username} {action}d.")


async def _reset_password(actor: User) -> None:
    user = await _get_user_by_name()
    if user is None:
        return

    new_pw = Prompt.ask(f"New password for [bold]{user.username}[/]", password=True)
    try:
        validate_password(new_pw)
    except AuthError as exc:
        _error(str(exc))
        return

    if not Confirm.ask(f"Reset password for [bold]{user.username}[/]?"):
        _warn("Cancelled.")
        return

    async with get_session() as session:
        from sqlalchemy import select

        from yesterwind_bbs.db.models import User as UserModel

        result = await session.execute(select(UserModel).where(UserModel.id == user.id))
        live_user = result.scalar_one()
        live_user.password_hash = hash_password(new_pw)

    _success(f"Password reset for {user.username}.")


# ── Message board management ──────────────────────────────────────────────────


async def _boards_menu(actor: User) -> None:
    while True:
        _header("Message Boards")
        console.print("[1] List boards")
        console.print("[2] Create board")
        console.print("[3] Edit board")
        console.print("[4] Toggle active")
        console.print("[B] Back")
        choice = Prompt.ask("Choice").strip().upper()

        if choice == "1":
            await _list_boards_display(actor)
        elif choice == "2":
            await _create_board(actor)
        elif choice == "3":
            await _edit_board(actor)
        elif choice == "4":
            await _toggle_board(actor)
        elif choice == "B":
            return


async def _list_boards_display(actor: User) -> None:
    async with get_session() as session:
        boards = await list_boards(session, actor)

    if not boards:
        _warn("No boards.")
        return

    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("ID", style="dim", width=5)
    t.add_column("Name", min_width=20)
    t.add_column("Read", width=8)
    t.add_column("Post", width=8)
    t.add_column("Active", width=7)
    t.add_column("Sort", width=5)
    t.add_column("Messages", width=9)

    for b in boards:
        async with get_session() as session:
            count = await message_count(session, b.id)
        t.add_row(
            str(b.id),
            b.name,
            str(b.read_level),
            str(b.post_level),
            "[green]yes[/]" if b.is_active else "[red]no[/]",
            str(b.sort_order),
            str(count),
        )
    console.print(t)


async def _create_board(actor: User) -> None:
    name = Prompt.ask("Board name")
    description = Prompt.ask("Description", default="")
    read_level = IntPrompt.ask("Read level", default=AccessLevel.USER)
    post_level = IntPrompt.ask("Post level", default=AccessLevel.USER)
    sort_order = IntPrompt.ask("Sort order", default=0)

    try:
        async with get_session() as session:
            board = await create_board(
                session,
                name,
                actor=actor,
                description=description or None,
                read_level=read_level,
                post_level=post_level,
                sort_order=sort_order,
            )
        _success(f"Board '{board.name}' created (id={board.id}).")
    except MessageError as exc:
        _error(str(exc))


async def _edit_board(actor: User) -> None:
    board_id = IntPrompt.ask("Board ID")
    try:
        async with get_session() as session:
            board = await get_board(session, board_id, actor)
    except (BoardNotFound, MessageError) as exc:
        _error(str(exc))
        return

    console.print(f"Editing [bold]{board.name}[/] (leave blank to keep current)")
    name = Prompt.ask("Name", default=board.name)
    description = Prompt.ask("Description", default=board.description or "")
    read_level = IntPrompt.ask("Read level", default=board.read_level)
    post_level = IntPrompt.ask("Post level", default=board.post_level)
    sort_order = IntPrompt.ask("Sort order", default=board.sort_order)

    try:
        async with get_session() as session:
            await update_board(
                session,
                board_id,
                actor=actor,
                name=name,
                description=description or None,
                read_level=read_level,
                post_level=post_level,
                sort_order=sort_order,
            )
        _success(f"Board '{name}' updated.")
    except MessageError as exc:
        _error(str(exc))


async def _toggle_board(actor: User) -> None:
    board_id = IntPrompt.ask("Board ID")
    try:
        async with get_session() as session:
            board = await get_board(session, board_id, actor)
    except (BoardNotFound, MessageError) as exc:
        _error(str(exc))
        return

    state = "active" if board.is_active else "inactive"
    action = "deactivate" if board.is_active else "activate"
    if not Confirm.ask(f"{action.capitalize()} [bold]{board.name}[/] (currently {state})?"):
        _warn("Cancelled.")
        return

    try:
        async with get_session() as session:
            await update_board(session, board_id, actor=actor, is_active=not board.is_active)
        _success(f"Board '{board.name}' {action}d.")
    except MessageError as exc:
        _error(str(exc))


# ── File area management ──────────────────────────────────────────────────────


async def _areas_menu(actor: User) -> None:
    while True:
        _header("File Areas")
        console.print("[1] List areas")
        console.print("[2] Create area")
        console.print("[3] Edit area")
        console.print("[4] Toggle active")
        console.print("[B] Back")
        choice = Prompt.ask("Choice").strip().upper()

        if choice == "1":
            await _list_areas_display(actor)
        elif choice == "2":
            await _create_area(actor)
        elif choice == "3":
            await _edit_area(actor)
        elif choice == "4":
            await _toggle_area(actor)
        elif choice == "B":
            return


async def _list_areas_display(actor: User) -> None:
    async with get_session() as session:
        areas = await list_areas(session, actor)

    if not areas:
        _warn("No file areas.")
        return

    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("ID", style="dim", width=5)
    t.add_column("Name", min_width=20)
    t.add_column("Path", min_width=16)
    t.add_column("Read", width=6)
    t.add_column("Upload", width=7)
    t.add_column("Active", width=7)
    t.add_column("Files", width=6)

    for a in areas:
        async with get_session() as session:
            count = await file_count(session, a.id)
        t.add_row(
            str(a.id),
            a.name,
            a.path,
            str(a.read_level),
            str(a.upload_level),
            "[green]yes[/]" if a.is_active else "[red]no[/]",
            str(count),
        )
    console.print(t)


async def _create_area(actor: User) -> None:
    name = Prompt.ask("Area name")
    path = Prompt.ask("Storage path (relative to FILES_DIR)")
    description = Prompt.ask("Description", default="")
    read_level = IntPrompt.ask("Read level", default=AccessLevel.USER)
    upload_level = IntPrompt.ask("Upload level", default=AccessLevel.USER)
    sort_order = IntPrompt.ask("Sort order", default=0)

    try:
        async with get_session() as session:
            area = await create_area(
                session,
                name,
                path,
                actor=actor,
                description=description or None,
                read_level=read_level,
                upload_level=upload_level,
                sort_order=sort_order,
            )
        _success(f"Area '{area.name}' created at {config.FILES_DIR}/{path}.")
    except FileError as exc:
        _error(str(exc))


async def _edit_area(actor: User) -> None:
    area_id = IntPrompt.ask("Area ID")
    try:
        async with get_session() as session:
            area = await get_area(session, area_id, actor)
    except (AreaNotFound, FileError) as exc:
        _error(str(exc))
        return

    console.print(f"Editing [bold]{area.name}[/] (leave blank to keep current)")
    name = Prompt.ask("Name", default=area.name)
    description = Prompt.ask("Description", default=area.description or "")
    read_level = IntPrompt.ask("Read level", default=area.read_level)
    upload_level = IntPrompt.ask("Upload level", default=area.upload_level)
    sort_order = IntPrompt.ask("Sort order", default=area.sort_order)

    try:
        async with get_session() as session:
            await update_area(
                session,
                area_id,
                actor=actor,
                name=name,
                description=description or None,
                read_level=read_level,
                upload_level=upload_level,
                sort_order=sort_order,
            )
        _success(f"Area '{name}' updated.")
    except FileError as exc:
        _error(str(exc))


async def _toggle_area(actor: User) -> None:
    area_id = IntPrompt.ask("Area ID")
    try:
        async with get_session() as session:
            area = await get_area(session, area_id, actor)
    except (AreaNotFound, FileError) as exc:
        _error(str(exc))
        return

    state = "active" if area.is_active else "inactive"
    action = "deactivate" if area.is_active else "activate"
    if not Confirm.ask(f"{action.capitalize()} [bold]{area.name}[/] (currently {state})?"):
        _warn("Cancelled.")
        return

    try:
        async with get_session() as session:
            await update_area(session, area_id, actor=actor, is_active=not area.is_active)
        _success(f"Area '{area.name}' {action}d.")
    except FileError as exc:
        _error(str(exc))


# ── Status panel ──────────────────────────────────────────────────────────────


async def _show_status() -> None:
    from sqlalchemy import func, select

    from yesterwind_bbs.db.models import Session as BbsSession
    from yesterwind_bbs.db.models import User as UserModel

    async with get_session() as session:
        user_count = (
            await session.execute(select(func.count()).select_from(UserModel))
        ).scalar_one()
        sysop_count = (
            await session.execute(
                select(func.count())
                .select_from(UserModel)
                .where(UserModel.access_level >= AccessLevel.SYSOP)
            )
        ).scalar_one()
        active_sessions = (
            await session.execute(
                select(func.count())
                .select_from(BbsSession)
                .where(
                    BbsSession.disconnected_at == None  # noqa: E711
                )
            )
        ).scalar_one()

    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold cyan")
    t.add_column()
    t.add_row("BBS name:", config.BBS_NAME)
    t.add_row("Host:", f"{config.BBS_HOSTNAME}:{config.BBS_PORT}")
    t.add_row("Database:", config.DATABASE_URL)
    t.add_row("Files root:", config.FILES_DIR)
    t.add_row("Total users:", str(user_count))
    t.add_row("Sysops:", str(sysop_count))
    t.add_row("Active nodes:", str(active_sessions))
    t.add_row("Time:", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    console.print(Panel(t, title="[bold cyan]BBS Status[/]", expand=False))


# ── Active nodes ──────────────────────────────────────────────────────────────


async def _show_nodes() -> None:
    from sqlalchemy import select

    from yesterwind_bbs.db.models import Session as BbsSession
    from yesterwind_bbs.db.models import User as UserModel

    async with get_session() as session:
        result = await session.execute(
            select(BbsSession, UserModel)
            .outerjoin(UserModel, BbsSession.user_id == UserModel.id)
            .where(BbsSession.disconnected_at == None)  # noqa: E711
            .order_by(BbsSession.connected_at)
        )
        rows = result.all()

    if not rows:
        _warn("No active connections.")
        return

    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("Node", width=5)
    t.add_column("User", min_width=16)
    t.add_column("Terminal", width=10)
    t.add_column("Remote addr", min_width=18)
    t.add_column("Connected")
    t.add_column("Last activity")

    for bbs_session, user in rows:
        t.add_row(
            str(bbs_session.node_number),
            user.username if user else "[dim](not logged in)[/]",
            bbs_session.terminal,
            bbs_session.remote_addr,
            Text.from_markup(_fmt_dt(bbs_session.connected_at)),
            Text.from_markup(_fmt_dt(bbs_session.last_activity_at)),
        )
    console.print(t)


# ── Main menu ─────────────────────────────────────────────────────────────────


async def _main_menu(actor: User) -> None:
    while True:
        console.print()
        _header(f"Main Menu  [dim]({actor.username})[/dim]")
        console.print("[S] Status")
        console.print("[N] Active nodes")
        console.print("[U] Users")
        console.print("[B] Message boards")
        console.print("[F] File areas")
        console.print("[Q] Quit")
        choice = Prompt.ask("Choice").strip().upper()

        if choice == "S":
            await _show_status()
        elif choice == "N":
            await _show_nodes()
        elif choice == "U":
            await _users_menu(actor)
        elif choice == "B":
            await _boards_menu(actor)
        elif choice == "F":
            await _areas_menu(actor)
        elif choice == "Q":
            console.print("[dim]Goodbye.[/]")
            return


# ── First-run setup ───────────────────────────────────────────────────────────


async def _is_first_run() -> bool:
    from sqlalchemy import func, select

    async with get_session() as session:
        result = await session.execute(select(func.count()).select_from(User))
        return (result.scalar() or 0) == 0


async def _first_run_setup() -> User:
    """Interactive wizard that creates the initial sysop account."""
    console.print(
        Panel(
            "[bold yellow]Welcome to Yesterwind BBS![/]\n\n"
            "No accounts exist yet. Let's create the first sysop account.",
            title="First-run setup",
            expand=False,
        )
    )
    while True:
        username = Prompt.ask("[bold]Sysop username[/]").strip()
        if not username:
            _error("Username cannot be empty.")
            continue
        password = Prompt.ask("[bold]Password[/]", password=True)
        try:
            validate_password(password)
        except Exception as exc:
            _error(str(exc))
            continue
        confirm = Prompt.ask("[bold]Confirm password[/]", password=True)
        if password != confirm:
            _error("Passwords do not match.")
            continue
        break

    pw_hash = hash_password(password)
    async with get_session() as session:
        user = User(
            username=username,
            password_hash=pw_hash,
            access_level=AccessLevel.SYSOP,
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)

    _success(f"Sysop account [bold]{username}[/] created. Welcome!")
    return user


# ── Entry point ───────────────────────────────────────────────────────────────


async def _run() -> None:
    await init_db()
    if await _is_first_run():
        actor = await _first_run_setup()
    else:
        actor = await _authenticate()
        if actor is None:
            _error("Authentication failed. Exiting.")
            sys.exit(1)
    _success(f"Logged in as [bold]{actor.username}[/] (level {actor.access_level})")
    await _main_menu(actor)


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/]")


if __name__ == "__main__":
    main()
