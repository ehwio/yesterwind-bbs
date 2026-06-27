# Contributing to Yesterwind BBS

Thanks for your interest. This is a retro telnet BBS server — the goal is clean
async Python that works reliably with everything from a modern terminal emulator
to a 1985 Atari 8-bit.

## Quick start

```bash
git clone https://github.com/ehwio/yesterwind-bbs
cd yesterwind-bbs
uv sync                    # install deps + dev tools
cp .env.example .env       # edit at minimum SECRET_KEY
uv run bbs                 # start the server on port 23
```

Connect with any telnet client: `telnet localhost 23`

To create the first sysop account: `uv run bbs-sysop`

## Before opening a PR

Run the full check suite and make sure everything passes:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run pytest
```

If ruff format reports files to reformat, run `uv run ruff format src/ tests/`
and commit the result. CI will reject unformatted code.

## Branch and commit conventions

- Branch from `main`: `feature/<slug>`, `fix/<slug>`, `docs/<slug>`
- Keep commits focused — one logical change per commit
- Commit messages: short imperative subject, blank line, then body if needed
- Never push directly to `main`

## Code style

- **Async throughout.** All I/O is `async`/`await`. No blocking calls inside coroutines.
- **No comments explaining what the code does** — names should do that. Add a
  comment only when the *why* is non-obvious (a hidden constraint, a protocol
  quirk, a workaround for a specific bug).
- **No unnecessary abstractions.** Add what the current task needs; don't
  design for hypothetical future requirements.
- **Terminal-agnostic.** Text that reaches the wire goes through a `Terminal`
  codec. Never write raw ANSI escape codes outside `terminal/ansi.py`.
- Line length: 100 characters (enforced by ruff).

## Adding a terminal type

1. Subclass `Terminal` in `src/yesterwind_bbs/terminal/`.
2. Add an entry to `TerminalType` in `terminal/base.py`.
3. Wire it into `TERMINAL_MENU` and `TerminalType.from_choice()`.
4. Export it from `terminal/__init__.py`.
5. Add tests in `tests/test_terminal.py`.

## Adding a file transfer protocol

The transfer layer lives in the companion library
[yesterwind-xyzmodem](https://github.com/ehwio/yesterwind-xyzmodem). Changes
to transfer protocols belong there. The BBS integrates them via
`files.py:send_file_xyzmodem()` and `receive_file_xyzmodem()`.

## Adding a door

See `docs/doors-spec.md` for the planned doors architecture. The subsystem is
not yet implemented — contributions here are very welcome.

## Reporting bugs

Open an issue at https://github.com/ehwio/yesterwind-bbs/issues. Include:

- What you did
- What you expected
- What actually happened (include full tracebacks)
- Your telnet client and terminal type if relevant

## License

By contributing you agree that your contributions will be licensed under the
MIT License.
