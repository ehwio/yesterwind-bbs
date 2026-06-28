"""
Splash screens for Yesterwind BBS.

Each function returns raw bytes ready to write to the telnet stream.
ANSI splash uses 256-colour VT100; other terminal types get plain ASCII.
"""

from __future__ import annotations

import math

from yesterwind_bbs import config

_R = "\x1b[0m"  # SGR reset


# ── Low-level ANSI helpers ────────────────────────────────────────────────────


def _e(fg: int | None = None, bg: int | None = None, bold: bool = False) -> str:
    parts: list[str] = []
    if bold:
        parts.append("1")
    if fg is not None:
        parts += ["38", "5", str(fg)]
    if bg is not None:
        parts += ["48", "5", str(bg)]
    return f"\x1b[{';'.join(parts)}m" if parts else ""


# ── Canvas renderer ───────────────────────────────────────────────────────────

_Cell = tuple[str, int | None, int | None, bool]  # (char, fg, bg, bold)


def _new_canvas(rows: int, cols: int, bg: int) -> list[list[_Cell]]:
    return [[(" ", None, bg, False)] * cols for _ in range(rows)]


def _put(
    canvas: list[list[_Cell]],
    r: int,
    c: int,
    ch: str,
    fg: int | None = None,
    bg: int | None = None,
    bold: bool = False,
) -> None:
    rows, cols = len(canvas), len(canvas[0])
    if 0 <= r < rows and 0 <= c < cols:
        canvas[r][c] = (ch, fg, bg, bold)


def _fill(
    canvas: list[list[_Cell]],
    r: int,
    c0: int,
    c1: int,
    ch: str = " ",
    fg: int | None = None,
    bg: int | None = None,
    bold: bool = False,
) -> None:
    for c in range(c0, min(c1, len(canvas[0]))):
        canvas[r][c] = (ch, fg, bg, bold)


def _text(
    canvas: list[list[_Cell]],
    r: int,
    c: int,
    s: str,
    fg: int | None = None,
    bg: int | None = None,
    bold: bool = False,
) -> None:
    for i, ch in enumerate(s):
        _put(canvas, r, c + i, ch, fg, bg, bold)


def _render(canvas: list[list[_Cell]]) -> bytes:
    """Render canvas to telnet bytes (CRLF line endings, CP437 encoded)."""
    out: list[str] = []
    for row in canvas:
        line = ""
        cur: _Cell = ("", -1, -1, False)
        for cell in row:
            _, cfg, cbg, cbold = cur
            ch, fg, bg, bold = cell
            if fg != cfg or bg != cbg or bold != cbold:
                line += _e(fg, bg, bold)
                cur = cell
            line += ch
        line += _R
        out.append(line)
    return ("\r\n".join(out) + "\r\n").encode("cp437", errors="replace")


# ── ANSI 256-colour sunset sailboat splash ────────────────────────────────────

# Sky gradient: bg colour per row (rows 0-13, dark to golden horizon)
_SKY: list[int] = [17, 17, 18, 18, 54, 54, 90, 90, 124, 124, 166, 166, 202, 208]

# Ocean gradient: bg colour per row starting at row 14
_SEA: list[int] = [33, 32, 27, 26, 25, 24, 20, 19, 18, 17]

# Palette shortcuts
_STAR = 255  # star white
_TITLE_FG = 255  # title white
_SUB_FG = 253  # subtitle light grey
_SAIL_FG = 231  # sail bright white
_BOOM_FG = 248  # boom/hull edge grey
_HULL_BG = 130  # warm brown hull body
_HULL_DK = 88  # dark red hull underside
_MAST_FG = 252  # mast grey-white
_WAKE_FG = 51  # bright cyan wake
_WAVE_HI = 39  # lighter wave highlight
_WAVE_LO = 27  # darker wave trough
_SUN_CORE = 226  # pure yellow sun core
_SUN_MID = 220  # golden sun mid
_SUN_EDGE = 214  # orange sun edge
_SUN_HAZE = 208  # orange-red haze

# Geometry
_MAST = 30  # mast column
_SAIL_TOP = 5  # first row sails appear
_SAIL_BOT = 13  # last sky row (boom row)
_HULL_TOP = 14  # first water row — hull body here
_HULL_BOT = 15  # second water row — hull keel
_SUN_CX = 60  # sun centre column
_SUN_CY = 10  # sun centre row
_SUN_RX = 9.5  # horizontal radius (chars)
_SUN_RY = 3.2  # vertical radius (rows)

_STARS = [
    (0, 4),
    (0, 14),
    (0, 27),
    (0, 38),
    (0, 51),
    (0, 65),
    (0, 73),
    (0, 78),
    (1, 10),
    (1, 44),
    (1, 62),
    (1, 76),
    (2, 7),
    (2, 22),
    (2, 56),
    (2, 70),
    (3, 3),
    (3, 18),
    (3, 47),
    (3, 67),
    (4, 11),
    (4, 40),
    (4, 72),
    (5, 23),
    (5, 53),
    (5, 69),
]

# Planet/bright-star accents (drawn as 'o' in a distinct colour)
_PLANETS = [(2, 71, 220), (4, 75, 213)]


def ansi_splash() -> bytes:
    ROWS, COLS = 23, 80
    canvas = _new_canvas(ROWS, COLS, _SKY[0])

    # ── Sky background ────────────────────────────────────────────────────────
    for r in range(14):
        _fill(canvas, r, 0, COLS, bg=_SKY[r])
    for r in range(14, ROWS):
        idx = min(r - 14, len(_SEA) - 1)
        _fill(canvas, r, 0, COLS, bg=_SEA[idx])

    # ── Stars ─────────────────────────────────────────────────────────────────
    for r, c in _STARS:
        _put(canvas, r, c, "*", _STAR, _SKY[r])
    for r, c, col in _PLANETS:
        _put(canvas, r, c, "o", col, _SKY[r], bold=True)

    # ── BBS title ─────────────────────────────────────────────────────────────
    bbs_name = config.BBS_NAME.upper()
    spaced = "  ".join(bbs_name)  # spaced-out letters for drama
    tc = max(0, (COLS - len(spaced)) // 2)
    _text(canvas, 1, tc, spaced, _TITLE_FG, _SKY[1], bold=True)

    tagline = "Connecting the world, one baud at a time."
    tl = max(0, (COLS - len(tagline)) // 2)
    _text(canvas, 3, tl, tagline, _SUB_FG, _SKY[3])

    # ── Sun ───────────────────────────────────────────────────────────────────
    for r in range(7, 14):
        for c in range(49, 73):
            dr = (r - _SUN_CY) / _SUN_RY
            dc = (c - _SUN_CX) / _SUN_RX
            d = math.sqrt(dr * dr + dc * dc)
            bg = _SKY[r]
            if d <= 0.50:
                _put(canvas, r, c, "█", _SUN_CORE, _SUN_CORE)
            elif d <= 0.72:
                _put(canvas, r, c, "█", _SUN_MID, _SUN_MID)
            elif d <= 0.88:
                _put(canvas, r, c, "▓", _SUN_MID, bg)
            elif d <= 1.05:
                _put(canvas, r, c, "▒", _SUN_EDGE, bg)
            elif d <= 1.25:
                _put(canvas, r, c, "░", _SUN_HAZE, bg)

    # ── Sails ─────────────────────────────────────────────────────────────────
    # Both sails grow outward from the mast tip to the boom.
    # spread at row r = r - SAIL_TOP
    for r in range(_SAIL_TOP, _SAIL_BOT + 1):
        spread = r - _SAIL_TOP
        sky_bg = _SKY[r]

        # Mainsail (right of mast): interior sky colour, bright white edge
        r_edge = _MAST + spread + 1
        for c in range(_MAST + 1, r_edge):
            _put(canvas, r, c, " ", None, sky_bg)
        _put(canvas, r, r_edge, "\\", _SAIL_FG, sky_bg, bold=True)

        # Jib (left of mast): interior sky colour, bright white edge
        l_edge = _MAST - spread - 1
        for c in range(l_edge + 1, _MAST):
            _put(canvas, r, c, " ", None, sky_bg)
        _put(canvas, r, l_edge, "/", _SAIL_FG, sky_bg, bold=True)

    # ── Mast (drawn last so it sits in front of sails) ────────────────────────
    for r in range(_SAIL_TOP - 1, _SAIL_BOT):
        _put(canvas, r, _MAST, "|", _MAST_FG, _SKY[r])

    # Mast tip and pennant (row 4, well below the tagline on row 3)
    _put(canvas, _SAIL_TOP - 1, _MAST + 1, ">", 196, _SKY[_SAIL_TOP - 1], bold=True)

    # ── Boom / deck ───────────────────────────────────────────────────────────
    spread_bot = _SAIL_BOT - _SAIL_TOP
    boom_l = _MAST - spread_bot - 1
    boom_r = _MAST + spread_bot + 1
    for c in range(boom_l, boom_r + 1):
        _put(canvas, _SAIL_BOT, c, "_", _BOOM_FG, _SKY[_SAIL_BOT])

    # ── Hull (sits on the water) ───────────────────────────────────────────────
    hull_l, hull_r = boom_l, boom_r

    # Hull body row
    _fill(canvas, _HULL_TOP, hull_l, hull_r + 1, " ", None, _HULL_BG)
    _put(canvas, _HULL_TOP, hull_l, "|", _SAIL_FG, _HULL_BG, bold=True)
    _put(canvas, _HULL_TOP, hull_r, "|", _SAIL_FG, _HULL_BG, bold=True)

    # Hull keel / underside
    _put(canvas, _HULL_BOT, hull_l - 1, "\\", _SAIL_FG, _SEA[1], bold=True)
    _fill(canvas, _HULL_BOT, hull_l, hull_r + 1, "_", _HULL_DK, _HULL_DK)
    _put(canvas, _HULL_BOT, hull_r + 1, "/", _SAIL_FG, _SEA[1], bold=True)

    # Wake / waterline
    wake_l = hull_l - 3
    wake_r = hull_r + 3
    for c in range(wake_l, wake_r + 1):
        ch = "~" if c % 2 == 0 else "-"
        _put(canvas, _HULL_BOT + 1, c, ch, _WAKE_FG, _SEA[2], bold=True)

    # ── Ocean waves ───────────────────────────────────────────────────────────
    for r in range(_HULL_BOT + 2, ROWS - 1):
        idx = min(r - 14, len(_SEA) - 1)
        sea_bg = _SEA[idx]
        # phase shift per row for varied wave pattern
        shift = (r * 5) % 8
        for c in range(COLS):
            phase = (c + shift) % 8
            if phase < 2:
                ch, fg = "~", _WAVE_HI
            elif phase < 4:
                ch, fg = "-", _WAVE_LO
            elif phase < 5:
                ch, fg = "~", _WAVE_HI
            else:
                ch, fg = " ", sea_bg
            _put(canvas, r, c, ch, fg, sea_bg)

    # ── Press any key ─────────────────────────────────────────────────────────
    pak = "[ Press any key to enter ]"
    _fill(canvas, ROWS - 1, 0, COLS, bg=17)
    pc = (COLS - len(pak)) // 2
    _text(canvas, ROWS - 1, pc, pak, 244, 17)

    return _render(canvas)


# ── Plain-text fallback splash ────────────────────────────────────────────────


def plain_splash() -> bytes:
    lines = [
        "",
        f"  {config.BBS_NAME}",
        f"  Sysop: {config.BBS_SYSOP}",
        "  " + "-" * 40,
        "  Connecting the world, one baud at a time.",
        "",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("ascii", errors="replace")
