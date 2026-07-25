"""Group 4 -- import safety and the app object (SPEC section 8.4).

Two properties, both of which are really about stdio hygiene:

* ``import notes_mcp.server`` must succeed with **no** ``NOTES_DIR`` set and must
  write nothing to stdout, because stdout is the JSON-RPC channel. Checking that
  from inside pytest is not enough -- the module is already imported and other
  tests have configured it -- so the honest version runs a fresh interpreter.
* the FastMCP app must expose exactly the three documented tools, no more.

The ``main()`` failure modes live here too: a missing or bogus ``NOTES_DIR`` has
to explain itself on stderr and exit non-zero, and a good one has to start up and
sit waiting for input.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from conftest import EXPECTED_TOOL_NAMES, FIXTURE_NOTES, REPO_ROOT, run_async
from notes_mcp import server

#: Startup should be near-instant; anything slower than this is a hang.
STARTUP_TIMEOUT = 20.0
#: How long we watch a healthy server idle before declaring it alive.
IDLE_SECONDS = 3.0


def child_env(**overrides: str) -> dict[str, str]:
    """A clean environment for a child interpreter: no NOTES_DIR unless asked.

    ``PYTHONPATH`` points at ``src/`` so the child imports the package whether or
    not it happens to be installed in the venv.
    """
    env = dict(os.environ)
    env.pop("NOTES_DIR", None)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env.update(overrides)
    return env


def run_child(*args: str, env: dict[str, str], timeout: float = STARTUP_TIMEOUT):
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=str(REPO_ROOT.parent),  # nothing may depend on the working directory
    )


# --------------------------------------------------------------------------- #
# Importing is safe
# --------------------------------------------------------------------------- #


def test_import_without_notes_dir_is_silent_and_succeeds():
    script = textwrap.dedent(
        """
        import asyncio, os, sys

        assert "NOTES_DIR" not in os.environ

        import notes_mcp.server as srv

        # Nothing may be resolved at import time ...
        try:
            srv.notes_dir()
        except RuntimeError:
            pass
        else:
            raise AssertionError("notes_dir() must refuse before configuration")

        # ... and nothing may be registered yet.
        assert asyncio.run(srv.mcp.list_resources()) == []
        names = sorted(tool.name for tool in asyncio.run(srv.mcp.list_tools()))
        assert names == ["list_notes", "read_note", "search_notes"], names
        print("import-ok", file=sys.stderr)
        """
    )

    done = run_child("-c", script, env=child_env())

    assert done.returncode == 0, done.stderr
    # The one assertion that protects the protocol: not a byte on stdout.
    assert done.stdout == ""
    assert "import-ok" in done.stderr


def test_module_is_importable_as_a_module_path():
    """``python -m notes_mcp.server`` is the one documented launch command, so the
    module must be runnable that way (here: rejected cleanly, no NOTES_DIR)."""
    done = run_child("-m", "notes_mcp.server", env=child_env())

    assert done.returncode == 1
    assert done.stdout == ""


# --------------------------------------------------------------------------- #
# The app object
# --------------------------------------------------------------------------- #


def test_app_exposes_exactly_the_expected_tools():
    tools = run_async(server.mcp.list_tools())

    assert {tool.name for tool in tools} == EXPECTED_TOOL_NAMES
    assert len(tools) == len(EXPECTED_TOOL_NAMES)


def test_every_tool_documents_itself_for_the_model():
    tools = {tool.name: tool for tool in run_async(server.mcp.list_tools())}

    for tool in tools.values():
        assert tool.description and tool.description.strip()

    search_tool = tools["search_notes"]
    schema = search_tool.inputSchema
    assert schema["properties"]["query"]["type"] == "string"
    assert schema["properties"]["max_results"]["default"] == 5
    assert schema["required"] == ["query"]
    # The docstring is the model's instruction sheet (SPEC section 6.1).
    assert "Search all markdown notes" in search_tool.description
    assert "read_note" in search_tool.description

    assert tools["read_note"].inputSchema["required"] == ["path"]
    assert tools["list_notes"].inputSchema.get("properties", {}) == {}


def test_server_identity_and_alias():
    assert server.mcp.name == "notes-mcp"
    assert server.app is server.mcp


def test_tools_are_plain_callables_too():
    """FastMCP's decorator returns the function unchanged, which is what lets the
    rest of this suite call the tools directly."""
    for name in EXPECTED_TOOL_NAMES:
        assert callable(getattr(server, name))
        assert getattr(server, name).__doc__


# --------------------------------------------------------------------------- #
# main(): configuration failures and a healthy start
# --------------------------------------------------------------------------- #


def test_missing_notes_dir_exits_non_zero_with_a_stderr_message():
    done = run_child("-m", "notes_mcp.server", env=child_env())

    assert done.returncode != 0
    assert done.stdout == ""
    assert "NOTES_DIR is not set" in done.stderr


@pytest.mark.parametrize("bad", ["/definitely/not/a/real/folder", "__file__"])
def test_bad_notes_dir_exits_non_zero_with_a_stderr_message(bad):
    # "__file__" stands in for "a path that exists but is not a directory".
    target = str(FIXTURE_NOTES / "alpha.md") if bad == "__file__" else bad

    done = run_child("-m", "notes_mcp.server", env=child_env(NOTES_DIR=target))

    assert done.returncode != 0
    assert done.stdout == ""
    assert "not an existing directory" in done.stderr
    assert "Traceback" not in done.stderr


def test_valid_notes_dir_starts_and_waits_for_stdio():
    """Started with stdin held open, the server must keep running and must not
    print anything to stdout before a client says anything."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "notes_mcp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_env(NOTES_DIR=str(FIXTURE_NOTES)),
        cwd=str(REPO_ROOT.parent),
    )
    still_running = False
    try:
        # wait(), unlike communicate(), leaves stdin open -- otherwise the server
        # would see EOF straight away and shut down (see the test below).
        proc.wait(timeout=IDLE_SECONDS)
    except subprocess.TimeoutExpired:
        still_running = True
        proc.kill()
        proc.wait()

    stdout, stderr = proc.stdout.read(), proc.stderr.read()
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        stream.close()

    assert still_running, (
        f"server exited early (rc={proc.returncode}) stdout={stdout!r} stderr={stderr!r}"
    )
    assert stdout == ""  # stdout stays clean until the protocol uses it
    assert "serving 5 note(s)" in stderr
    assert str(FIXTURE_NOTES) in stderr


def test_server_shuts_down_cleanly_when_the_client_disconnects():
    """stdin closed immediately: the server should stop, quietly and with a zero
    exit code, rather than hanging or dumping a traceback."""
    done = subprocess.run(
        [sys.executable, "-m", "notes_mcp.server"],
        input="",
        capture_output=True,
        text=True,
        timeout=STARTUP_TIMEOUT,
        env=child_env(NOTES_DIR=str(FIXTURE_NOTES)),
        cwd=str(REPO_ROOT.parent),
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout == ""
    assert "Traceback" not in done.stderr
