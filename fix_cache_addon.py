"""
mitmproxy addon: Fix Claude Code cache behavior + dump requests/responses.

Fixes:
1. Moves skills system-reminder out of msg[0] to prevent block shuffling
2. Adds cache_control breakpoint to msg[0] so CLAUDE.md is cached separately

Then dumps the FIXED request + response to claude-logs/.

Usage: mitmweb --mode reverse:https://api.anthropic.com --listen-port 8000 -s fix_cache_addon.py
       (no need for separate dumper.py)
"""
import json
import os
import time
from mitmproxy import http

DUMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude-logs")
os.makedirs(DUMP_DIR, exist_ok=True)


def request(flow: http.HTTPFlow) -> None:
    if "anthropic" not in (flow.request.pretty_host or ""):
        return
    if "/v1/messages" not in flow.request.path:
        return
    if flow.request.method != "POST":
        return

    try:
        data = json.loads(flow.request.get_text())
    except (json.JSONDecodeError, ValueError):
        return

    messages = data.get("messages", [])
    if not messages:
        return

    msg0 = messages[0]
    if msg0.get("role") != "user":
        return

    content = msg0.get("content", [])
    if not isinstance(content, list):
        return

    modified = False

    # --- Fix 1: Move skills SR out of msg[0] if present ---
    if len(content) >= 3:
        blk0 = content[0]
        if (isinstance(blk0, dict)
                and not blk0.get("cache_control")
                and "<system-reminder>" in blk0.get("text", "")
                and ("skills are available" in blk0.get("text", "")
                     or "Skill tool" in blk0.get("text", ""))):

            skills_block = content.pop(0)

            last_user_idx = None
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    last_user_idx = i
                    break

            if last_user_idx is not None and last_user_idx > 0:
                last_content = messages[last_user_idx].get("content", [])
                if isinstance(last_content, list):
                    last_content.insert(0, skills_block)
                elif isinstance(last_content, str):
                    messages[last_user_idx]["content"] = [
                        skills_block,
                        {"type": "text", "text": last_content},
                    ]
                modified = True
                print(f"[fix-cache] Moved skills SR from msg[0] to msg[{last_user_idx}]")

    # --- Fix 2: Ensure msg[0] last block has cache_control ---
    content = msg0.get("content", [])  # Re-read after potential pop
    if isinstance(content, list) and len(content) > 0:
        last_block = content[-1]
        if isinstance(last_block, dict) and not last_block.get("cache_control"):
            last_block["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
            modified = True
            print(f"[fix-cache] Added cache_control to msg[0] block[{len(content)-1}]")

    if modified:
        flow.request.set_text(json.dumps(data))

    # Store timestamp for the dump
    flow.metadata["dump_timestamp"] = int(time.time())


def response(flow: http.HTTPFlow) -> None:
    if "/v1/messages" not in flow.request.path:
        return

    timestamp = flow.metadata.get("dump_timestamp", int(time.time()))

    # Dump the FIXED request (flow.request.content has the modified body)
    req_filename = os.path.join(DUMP_DIR, f"{timestamp}_request.json")
    with open(req_filename, "wb") as f:
        f.write(flow.request.content)

    # Dump the response
    res_filename = os.path.join(DUMP_DIR, f"{timestamp}_response.txt")
    with open(res_filename, "wb") as f:
        f.write(flow.response.content)
