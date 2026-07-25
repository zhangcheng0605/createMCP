"""Group 5 -- the live protocol test (SPEC section 8.5), the one that matters most.

Every other test in this suite calls Python functions. This one launches
``python -m notes_mcp.server`` as a **real subprocess**, talks to it over stdio
with the SDK's own client (``mcp.client.stdio.stdio_client`` + ``ClientSession``),
and asserts the whole conversation: ``initialize``, ``tools/list``,
``resources/list``, ``tools/call`` and ``resources/read``. If the server printed a
stray byte to stdout, mis-shaped a URI, or wired a tool up wrongly, the handshake
here breaks -- which is what turns the MCP Inspector pass into a formality.

Shape of the test: one subprocess, one conversation, collected into a
:class:`LiveSession` snapshot by a session-scoped fixture, with the individual
assertions split into small tests so a failure names the request that broke.
Everything runs under :data:`CONVERSATION_TIMEOUT` so a hang fails loudly instead
of blocking the run forever.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from conftest import (
    EXPECTED_TOOL_NAMES,
    FIXTURE_EXCLUDED,
    FIXTURE_NOTES,
    FIXTURE_RELPATHS,
    FIXTURE_URIS,
    REPO_ROOT,
)

#: Hard ceiling on the entire conversation: launch, handshake, every request.
CONVERSATION_TIMEOUT = 60.0
#: Ceiling on any single request, so one wedged handler is diagnosed on its own.
REQUEST_TIMEOUT = timedelta(seconds=20)

TRAVERSAL_ATTEMPT = "../README.md"  # a real markdown file one level above NOTES_DIR


@dataclass
class LiveSession:
    """Everything the real client got back from the real server."""

    init: Any
    tools: list[Any]
    resources: list[Any]
    templates: list[Any]
    search: Any
    phrase_search: Any
    listing: Any
    read_tool: Any
    traversal: Any
    resource_reads: dict[str, Any] = field(default_factory=dict)
    stderr: str = ""


def text_of(call_result: Any) -> str:
    """The text a model would see from a ``tools/call`` result."""
    return "\n".join(block.text for block in call_result.content if block.type == "text")


async def _converse(notes_dir: Path, errlog) -> LiveSession:
    params = StdioServerParameters(
        command=sys.executable,  # the venv interpreter running this test
        args=["-m", "notes_mcp.server"],
        env={
            "NOTES_DIR": str(notes_dir),
            # The child must find the package without relying on the cwd or on an
            # editable install being present.
            "PYTHONPATH": str(REPO_ROOT / "src"),
        },
        # Deliberately somewhere else: nothing may depend on the working directory.
        cwd=str(Path(os.sep)),
    )

    async with stdio_client(params, errlog=errlog) as (read_stream, write_stream):
        async with ClientSession(
            read_stream, write_stream, read_timeout_seconds=REQUEST_TIMEOUT
        ) as session:
            init = await session.initialize()

            tools = (await session.list_tools()).tools
            resources = (await session.list_resources()).resources
            templates = (await session.list_resource_templates()).resourceTemplates

            search = await session.call_tool("search_notes", {"query": "widget"})
            phrase_search = await session.call_tool(
                "search_notes", {"query": "quantum ferret", "max_results": 5}
            )
            listing = await session.call_tool("list_notes", {})
            read_tool = await session.call_tool(
                "read_note", {"path": "notes:///Spaced%20Note.md"}
            )
            traversal = await session.call_tool("read_note", {"path": TRAVERSAL_ATTEMPT})

            reads = {}
            for resource in resources:
                reads[str(resource.uri)] = await session.read_resource(resource.uri)

    return LiveSession(
        init=init,
        tools=list(tools),
        resources=list(resources),
        templates=list(templates),
        search=search,
        phrase_search=phrase_search,
        listing=listing,
        read_tool=read_tool,
        traversal=traversal,
        resource_reads=reads,
    )


@pytest.fixture(scope="session")
def live(tmp_path_factory) -> LiveSession:
    """Run the whole conversation once against a real server subprocess."""
    errlog_path = tmp_path_factory.mktemp("live") / "server-stderr.log"
    with errlog_path.open("w+", encoding="utf-8") as errlog:
        try:
            session = asyncio.run(
                asyncio.wait_for(_converse(FIXTURE_NOTES, errlog), CONVERSATION_TIMEOUT)
            )
        except asyncio.TimeoutError:  # pragma: no cover - only on a real hang
            errlog.flush()
            pytest.fail(
                f"the server did not finish the conversation within "
                f"{CONVERSATION_TIMEOUT}s. Server stderr:\n"
                f"{errlog_path.read_text(encoding='utf-8', errors='replace')}"
            )
    session.stderr = errlog_path.read_text(encoding="utf-8", errors="replace")
    return session


# --------------------------------------------------------------------------- #
# initialize
# --------------------------------------------------------------------------- #


def test_initialize_succeeds(live):
    assert live.init.serverInfo.name == "notes-mcp"
    assert live.init.protocolVersion
    # Both halves of the protocol must be advertised, or a client will not even ask.
    assert live.init.capabilities.tools is not None
    assert live.init.capabilities.resources is not None


def test_startup_banner_went_to_stderr(live):
    """The count and the folder are logged on stderr; stdout carried JSON-RPC only
    (if it had not, ``initialize`` above could not have parsed)."""
    assert "serving 5 note(s)" in live.stderr
    assert str(FIXTURE_NOTES) in live.stderr
    assert "Traceback" not in live.stderr


# --------------------------------------------------------------------------- #
# tools/list
# --------------------------------------------------------------------------- #


def test_tools_list_returns_exactly_the_three_tools(live):
    names = {tool.name for tool in live.tools}

    assert names == EXPECTED_TOOL_NAMES
    assert len(live.tools) == 3


def test_tools_arrive_with_descriptions_and_schemas(live):
    tools = {tool.name: tool for tool in live.tools}

    for tool in tools.values():
        assert tool.description and tool.description.strip()

    assert set(tools["search_notes"].inputSchema["properties"]) == {"query", "max_results"}
    assert tools["search_notes"].inputSchema["required"] == ["query"]
    assert set(tools["read_note"].inputSchema["properties"]) == {"path"}


# --------------------------------------------------------------------------- #
# resources/list
# --------------------------------------------------------------------------- #


def test_resources_list_returns_one_entry_per_fixture_note(live):
    assert [str(resource.uri) for resource in live.resources] == FIXTURE_URIS
    assert [resource.name for resource in live.resources] == FIXTURE_RELPATHS
    assert {resource.mimeType for resource in live.resources} == {"text/markdown"}


def test_resources_list_excludes_hidden_and_non_markdown_files(live):
    listed = " ".join(str(resource.uri) for resource in live.resources)

    for excluded in FIXTURE_EXCLUDED:
        assert excluded.split("/")[-1] not in listed
    assert "obsidian" not in listed
    assert ".txt" not in listed


def test_no_resource_templates_are_advertised(live):
    assert live.templates == []


# --------------------------------------------------------------------------- #
# tools/call
# --------------------------------------------------------------------------- #


def test_search_tool_call_finds_a_known_fixture_term(live):
    assert live.search.isError is False

    text = text_of(live.search)
    assert 'Found 3 note(s) matching "widget":' in text
    assert "notes:///alpha.md" in text
    assert "> The widget is the unit of work here." in text
    # Ranking survives the round trip: 4 hits, then 2, then 1.
    assert text.index("alpha.md") < text.index("beta.md") < text.index("gamma.md")
    # And the decoys are still invisible over the wire.
    assert "ignored.txt" not in text
    assert "obsidian" not in text


def test_search_tool_call_applies_the_phrase_bonus(live):
    text = text_of(live.phrase_search)

    assert live.phrase_search.isError is False
    assert text.index("nested/deep.md") < text.index("Spaced Note.md")


def test_list_notes_tool_call_lists_every_note(live):
    text = text_of(live.listing)

    assert live.listing.isError is False
    assert text.startswith("5 note(s) available:")
    for uri in FIXTURE_URIS:
        assert uri in text


def test_read_note_tool_call_returns_a_note_by_uri(live):
    expected = (FIXTURE_NOTES / "Spaced Note.md").read_text(encoding="utf-8")

    assert live.read_tool.isError is False
    assert text_of(live.read_tool) == expected  # the note's full text, verbatim


def test_read_note_tool_call_refuses_traversal_over_the_wire(live):
    """The security invariant, asserted through the real protocol: a refusal
    arrives as an ordinary tool answer, and the file's contents never do."""
    text = text_of(live.traversal)

    assert live.traversal.isError is False  # a refusal is an answer, not a crash
    assert text.startswith("Cannot read that note: ")
    assert "outside the notes folder" in text
    assert "# Test fixtures" not in text


# --------------------------------------------------------------------------- #
# resources/read
# --------------------------------------------------------------------------- #


def test_every_listed_resource_reads_back_its_own_text(live):
    assert set(live.resource_reads) == set(FIXTURE_URIS)

    for relpath, uri in zip(FIXTURE_RELPATHS, FIXTURE_URIS):
        result = live.resource_reads[uri]
        assert len(result.contents) == 1
        block = result.contents[0]
        assert str(block.uri) == uri
        assert block.mimeType == "text/markdown"
        assert block.text == (FIXTURE_NOTES / relpath).read_text(encoding="utf-8")


def test_resource_read_handles_the_percent_encoded_space(live):
    """``notes:///Spaced%20Note.md`` is the case that a two-slash URI scheme
    cannot express at all (SPEC section 5) -- here it survives a real round trip."""
    result = live.resource_reads["notes:///Spaced%20Note.md"]

    assert result.contents[0].text.startswith("# Spaced Note")


def test_nested_resource_uri_keeps_its_slash(live):
    result = live.resource_reads["notes:///nested/deep.md"]

    assert result.contents[0].text.startswith("# Deep")
    assert "quantum ferret" in result.contents[0].text
