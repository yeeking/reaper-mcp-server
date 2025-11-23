"""REAPER MCP server implemented with the MCP Python SDK.

Expose REAPER actions as MCP tools so LM Studio (or any MCP client)
can list capabilities and call them over the MCP HTTP transport.
"""
import re
import pprint
from typing import Any, Dict, List, Optional
import os

from plugin_helpers import PluginScanner
import threading

# HTTP exposure (for clients that probe GET /)
try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - FastAPI optional
    FastAPI = None  # type: ignore
    BaseModel = None  # type: ignore

import reapy
from mcp.server.fastmcp import FastMCP
from reapy import reascript_api as RPR

# MCP server instance (note: FastMCP init in this SDK does not accept description kw)
server = FastMCP("reaper-mcp")
_plugin_scanner = PluginScanner()


def _kickoff_plugin_scan_async():
    """Start an async scan on server startup and log the result."""
    def _scan():
        try:
            plugins = _plugin_scanner.force_scan()
            print(f"[plugin_scan] Initial scan complete: found {len(plugins)} plugins")
        except Exception as exc:  # pragma: no cover
            print(f"[plugin_scan] Initial scan failed: {exc}")

    threading.Thread(target=_scan, daemon=True).start()


def get_track_pointer(track_index: int):
    """Helper: resolve a track index to a REAPER MediaTrack pointer."""
    project = reapy.Project()  # current project
    track_id = RPR.GetTrack(project.id, track_index)
    return track_id


@server.tool(description="Insert a new track at the specified index.")
def create_track(index: int, want_defaults: bool = True) -> dict:
    """Create a new track and return its index and name."""
    RPR.InsertTrackAtIndex(index, want_defaults)
    RPR.TrackList_AdjustWindows(False)
    track_ptr = get_track_pointer(index)
    name_ret = RPR.GetSetMediaTrackInfo_String(track_ptr, "P_NAME", "", False)
    track_name = name_ret[3] if name_ret[0] else ""
    return {
        "result": f"Track {index + 1} created",
        "track_index": index,
        "track_name": track_name,
    }


@server.tool(description="Name/rename a track.")
def name_track(track_index: int, new_name: str) -> dict:
    """Set a track's name (title)."""
    track_ptr = get_track_pointer(track_index)
    RPR.GetSetMediaTrackInfo_String(track_ptr, "P_NAME", new_name, True)
    return {"result": f"Track {track_index + 1} renamed to '{new_name}'"}


@server.tool(description="Create a routing send from one track to another.")
def create_send(src_track_index: int, dest_track_index: int) -> dict:
    """Create a send between two tracks and return the send index."""
    src_ptr = get_track_pointer(src_track_index)
    dest_ptr = get_track_pointer(dest_track_index)
    send_index = RPR.CreateTrackSend(src_ptr, dest_ptr)
    if send_index >= 0:
        return {
            "result": "Send created",
            "send_index": send_index,
            "src_track": src_track_index,
            "dest_track": dest_track_index,
        }
    return {
        "error": "Send creation failed",
        "src_track": src_track_index,
        "dest_track": dest_track_index,
    }


@server.tool(description="Configure an existing send (volume/pan/mode/channels).")
def config_send(
    src_track_index: int,
    send_index: int,
    volume: Optional[float] = None,
    pan: Optional[float] = None,
    dest_channel: Optional[int] = None,
    send_mode: Optional[int] = None,
) -> dict:
    """Update parameters on an existing send."""
    track_ptr = get_track_pointer(src_track_index)
    if volume is not None:
        RPR.SetTrackSendInfo_Value(track_ptr, 0, send_index, "D_VOL", volume)
    if pan is not None:
        RPR.SetTrackSendInfo_Value(track_ptr, 0, send_index, "D_PAN", pan)
    if dest_channel is not None:
        RPR.SetTrackSendInfo_Value(track_ptr, 0, send_index, "I_DSTCHAN", float(dest_channel))
    if send_mode is not None:
        RPR.SetTrackSendInfo_Value(track_ptr, 0, send_index, "I_SENDMODE", float(send_mode))
    return {"result": "Send updated", "send_index": send_index, "src_track": src_track_index}


@server.tool(description="Insert an FX plugin on a track by name.")
def add_fx(track_index: int, fx_name: str, record_fx: bool = False) -> dict:
    """Add an FX to a track."""
    track_ptr = get_track_pointer(track_index)
    fx_index = RPR.TrackFX_AddByName(track_ptr, fx_name, record_fx, -1)
    if fx_index == -1:
        return {"error": f"FX '{fx_name}' not found or could not be added"}
    return {
        "result": f"FX added on track {track_index + 1}",
        "fx_name": fx_name,
        "fx_index": fx_index,
    }


@server.tool(description="Call any ReaScript function by name with args (advanced).")
def call_api(function: str, args: Optional[List] = None) -> dict:
    """Invoke an arbitrary REAPER API function by name."""
    func = getattr(RPR, function, None)
    if not func:
        return {"error": f"Function {function} not found in ReaScript API"}

    converted_args = []
    for arg in args or []:
        if (
            isinstance(arg, int)
            and function not in ["InsertTrackAtIndex", "InsertTrackInProject"]
            and "Track" in function
            and arg >= 0
        ):
            try:
                track_ptr = get_track_pointer(arg)
                converted_args.append(track_ptr)
                continue
            except Exception:
                pass
        converted_args.append(arg)

    try:
        result = func(*converted_args)
        return {"result": str(result)}
    except Exception as exc:
        return {"error": str(exc)}


def _parse_fx_metadata(name: str, ident: str) -> Dict[str, Any]:
    """Lightweight parsing of FX ident string into format/vendor/category hints."""
    ident = ident or ""
    plugin_type = ident.split(":", 1)[0].strip() if ":" in ident else ident.strip()
    rest = ident.split(":", 1)[1].strip() if ":" in ident else ""

    # Vendor is usually the trailing (...) group
    vendor = None
    vendor_match = re.search(r"\(([^()]+)\)\s*$", rest)
    if vendor_match:
        vendor = vendor_match.group(1).strip()

    category = None
    if plugin_type.upper() == "JS" and "/" in rest:
        category = rest.split("/", 1)[0].strip()
    elif "/" in rest:
        # Take leading path component as a best-effort category
        category = rest.split("/", 1)[0].strip()

    lower_ident = ident.lower()
    is_instrument = (
        plugin_type.upper() in {"VSTI", "AUI"}
        or lower_ident.startswith("vsti")
        or "instrument" in lower_ident
        or "synth" in lower_ident
    )

    return {
        "name": name,
        "ident": ident,
        "plugin_type": plugin_type,
        "vendor": vendor,
        "category": category,
        "is_instrument": is_instrument,
    }


@server.tool(description="List installed FX/plugins with basic metadata.")
def list_installed_fx(refresh_js: bool = False, limit: Optional[int] = None) -> dict:
    """Enumerate installed FX using PluginScanner; cache results after first scan."""

    def type_from_path(path: str) -> str:
        lower = path.lower()
        if lower.endswith(".vst3"):
            return "VST3"
        if lower.endswith(".vst"):
            return "VST"
        if lower.endswith(".component") or lower.endswith(".au"):
            return "AU"
        if lower.endswith(".dll"):
            return "VST"
        if lower.endswith(".so") or lower.endswith(".dylib"):
            return "VST/Other"
        return ""

    def category_from_path(path: str) -> Optional[str]:
        parts = os.path.normpath(path).split(os.sep)
        # Take parent folder under Plug-Ins as a loose category
        for i, part in enumerate(parts):
            if part.lower() in {"plug-ins", "plugins", "vst3", "vst", "components"} and i + 1 < len(parts):
                return parts[i + 1]
        return None

    # On first call or when refresh_js is True, force a scan; otherwise use cached.
    if refresh_js:
        plugins_raw = _plugin_scanner.force_scan()
    else:
        plugins_raw = _plugin_scanner.get_installed_plugins()

    plugins: List[Dict[str, Any]] = []
    for entry in plugins_raw:
        name = entry.get("name", "") or ""
        path = entry.get("path", "") or ""
        plugin_type = type_from_path(path)
        category = category_from_path(path)
        meta = {
            "name": name,
            "ident": path,
            "plugin_type": plugin_type,
            "vendor": None,
            "category": category,
            "is_instrument": False,  # pedalboard doesn't expose instrument flag
        }
        plugins.append(meta)
        if limit is not None and len(plugins) >= limit:
            break

    # Log summary for debugging
    sample = plugins[:3]
    print("[list_installed_fx] collected", len(plugins), "plugins; sample:", pprint.pformat(sample, compact=True))

    return {"count": len(plugins), "plugins": plugins}

# --------------------------
# Optional HTTP info server
# --------------------------
# Some MCP bridges probe GET / to discover capabilities. We expose a lightweight
# HTTP layer that lists tools and allows invoking them via POST /call.
TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "create_track",
        "description": "Insert a new track at the specified index.",
        "args": [
            {"name": "index", "type": "int", "required": True},
            {"name": "want_defaults", "type": "bool", "required": False, "default": True},
        ],
    },
    {
        "name": "name_track",
        "description": "Name/rename a track.",
        "args": [
            {"name": "track_index", "type": "int", "required": True},
            {"name": "new_name", "type": "str", "required": True},
        ],
    },
    {
        "name": "create_send",
        "description": "Create a routing send from one track to another.",
        "args": [
            {"name": "src_track_index", "type": "int", "required": True},
            {"name": "dest_track_index", "type": "int", "required": True},
        ],
    },
    {
        "name": "config_send",
        "description": "Configure an existing send (volume/pan/mode/channels).",
        "args": [
            {"name": "src_track_index", "type": "int", "required": True},
            {"name": "send_index", "type": "int", "required": True},
            {"name": "volume", "type": "float", "required": False},
            {"name": "pan", "type": "float", "required": False},
            {"name": "dest_channel", "type": "int", "required": False},
            {"name": "send_mode", "type": "int", "required": False},
        ],
    },
    {
        "name": "add_fx",
        "description": "Insert an FX plugin on a track by name.",
        "args": [
            {"name": "track_index", "type": "int", "required": True},
            {"name": "fx_name", "type": "str", "required": True},
            {"name": "record_fx", "type": "bool", "required": False, "default": False},
        ],
    },
    {
        "name": "call_api",
        "description": "Call any ReaScript function by name with args (advanced).",
        "args": [
            {"name": "function", "type": "str", "required": True},
            {"name": "args", "type": "list", "required": False, "default": []},
        ],
    },
    {
        "name": "list_installed_fx",
        "description": "List installed FX/plugins with basic metadata.",
        "args": [
            {"name": "refresh_js", "type": "bool", "required": False, "default": False},
            {"name": "limit", "type": "int", "required": False, "default": None},
        ],
    },
]

TOOL_HANDLERS = {
    "create_track": create_track,
    "name_track": name_track,
    "create_send": create_send,
    "config_send": config_send,
    "add_fx": add_fx,
    "call_api": call_api,
    "list_installed_fx": list_installed_fx,
}

app: Optional["FastAPI"] = None
if FastAPI:
    class ToolCall(BaseModel):  # type: ignore
        tool: str
        args: Dict[str, Any] = {}

    app = FastAPI(
        title="REAPER MCP Server",
        description="Lightweight HTTP surface for tool discovery/invocation.",
        version="1.0.0",
    )

    @app.get("/")
    async def root():
        return {
            "name": "reaper-mcp",
            "description": "REAPER control via MCP tools.",
            "tools": TOOL_SPECS,
        }

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/call")
    async def call_tool(request: ToolCall):
        tool_fn = TOOL_HANDLERS.get(request.tool)
        if not tool_fn:
            return {"error": f"Unknown tool '{request.tool}'"}
        try:
            result = tool_fn(**request.args)
            return result
        except TypeError as exc:
            return {"error": f"Bad arguments for {request.tool}: {exc}"}
        except Exception as exc:  # pragma: no cover
            return {"error": str(exc)}


if __name__ == "__main__":
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description="Run the REAPER MCP server.")
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8000")))
    parser.add_argument(
        "--transport",
        default=os.environ.get("MCP_TRANSPORT", "streamable-http"),
        help="Transport to run (http|stdio|socket depending on SDK support).",
    )
    args = parser.parse_args()

    print(f"Starting MCP server with transport={args.transport} on {args.host}:{args.port}")
    _kickoff_plugin_scan_async()

    if args.transport == "http":
        if not FastAPI or not app:
            sys.exit("FastAPI not installed; cannot serve HTTP root. pip install fastapi uvicorn[standard]")
        import uvicorn  # type: ignore

        uvicorn.run(app, host=args.host, port=args.port)
    else:
        # Delegate to SDK-supported transports (e.g., stdio or socket).
        server.run(transport=args.transport)
