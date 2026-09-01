"""Exercise an installed Friction executable through its packaged interfaces."""

from __future__ import annotations

import argparse
import os
import pty
import select
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _run_tui(executable: Path, database: Path) -> None:
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [str(executable), "--db", str(database), "tui"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)
    output = bytearray()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"packaged TUI exited early with {process.returncode}: "
                    f"{output.decode(errors='replace')[-2000:]}"
                )
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                output.extend(os.read(master, 65536))
            if database.exists() and b"Friction" in output:
                break
        else:
            raise RuntimeError("packaged TUI did not start before timeout")

        os.write(master, b":q\r")
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        if process.returncode not in {0, -signal.SIGTERM}:
            raise RuntimeError(f"packaged TUI exited with {process.returncode}")
    finally:
        os.close(master)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


async def _run_mcp(executable: Path, database: Path) -> None:
    parameters = StdioServerParameters(
        command=str(executable),
        args=["--db", str(database), "mcp"],
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as client,
    ):
        await client.initialize()
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        if "friction_add" not in names or "friction_get" not in names:
            raise RuntimeError("packaged MCP server is missing required tools")
        added = await client.call_tool(
            "friction_add", {"note": "release acceptance capture"}
        )
        if added.isError or added.structuredContent is None:
            raise RuntimeError("packaged MCP capture failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(f"not an executable file: {executable}")

    with tempfile.TemporaryDirectory(prefix="friction-release-") as directory:
        temporary = Path(directory)
        _run_tui(executable, temporary / "tui.db")
        anyio.run(_run_mcp, executable, temporary / "mcp.db")
    print(f"accepted packaged interfaces from {executable}")


if __name__ == "__main__":
    main()
