# Claude Code Cache Fix Proxy

A mitmproxy-based fix for Claude Code's prompt caching inefficiency that can burn through your 5-hour session usage in just a few prompts.

## The Problem

Claude Code uses Anthropic's [prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) to avoid re-processing the same tokens on every turn. The API supports 3 cache breakpoints (`cache_control` markers) that tell Anthropic "cache everything up to here." When cache hits work, previously-seen tokens are read at **0.1x cost** instead of 1x.

**But Claude Code has two bugs that cause constant cache invalidation:**

### Bug 1: Skills system-reminder block shuffling

Claude Code injects a `<system-reminder>` block containing available skills into the **first user message** (`messages[0]`). This block appears/disappears and changes content between turns. Since `messages[0]` sits right after the system prompt cache breakpoint, any change to it invalidates the cache for **everything after it** -- which is your entire conversation history.

This means ~25,000+ tokens get re-created (at **2x cost**) on every single turn instead of being read from cache at 0.1x.

### Bug 2: Missing cache breakpoint on messages[0]

Even without the skills block issue, `messages[0]` (which typically contains your CLAUDE.md content and project instructions) lacks a `cache_control` breakpoint. This means it can't be cached independently from the conversation that follows it.

### The Impact

With both bugs active:
- **Every turn** pays 2x to re-cache ~25-50K tokens that should have been read at 0.1x
- A session with heavy CLAUDE.md content (custom instructions, framework docs, etc.) burns through the 5-hour usage cap in **3-5 prompts**
- You end up waiting 4+ hours after barely getting any work done

## The Fix

This proxy intercepts Claude Code's API requests and applies two fixes before forwarding them to Anthropic:

1. **Moves the skills system-reminder** from `messages[0]` to the last user message, where it won't disrupt the cache chain
2. **Adds a `cache_control` breakpoint** to the last block of `messages[0]`, so your CLAUDE.md/project instructions get cached independently

### Results

Before fix:
```
Turn  1: 47.2% cache read  -- PARTIAL HIT, 25K tokens re-created
Turn  2: 47.2% cache read  -- PARTIAL HIT, 25K tokens re-created
Turn  3: 47.2% cache read  -- (every single turn)
```

After fix:
```
Turn  1: 30.4% cache read  -- first turn bootstraps cache (expected)
Turn  2: 99.9% cache read  -- good cache hit
Turn  3: 99.9% cache read  -- good cache hit
Turn  4: 99.7% cache read  -- good cache hit
Turn  5: 99.8% cache read  -- good cache hit
```

## Setup

### Prerequisites

- Python 3.10+
- [mitmproxy](https://github.com/mitmproxy/mitmproxy) installed

```bash
# Install mitmproxy
pip install mitmproxy
# or
brew install mitmproxy
```

### 1. Clone this repo

```bash
git clone https://github.com/jasdeepjaitla/claude-code-cache-fix-proxy.git
cd claude-code-cache-fix-proxy
```

### 2. Start the proxy

```bash
mitmweb --mode reverse:https://api.anthropic.com --listen-port 8000 -s fix_cache_addon.py
```

This starts a reverse proxy on `localhost:8000` that forwards to `api.anthropic.com`, applying the cache fixes to every request.

`mitmweb` also opens a browser UI where you can inspect the requests/responses in real-time. You can use `mitmdump` instead if you don't need the web UI.

### 3. Point Claude Code at the proxy

Set the environment variable before launching Claude Code:

```bash
export ANTHROPIC_BASE_URL=http://localhost:8000/
```

Or add it to your shell profile (`~/.zshrc`, `~/.bashrc`, etc.):

```bash
echo 'export ANTHROPIC_BASE_URL=http://localhost:8000/' >> ~/.zshrc
```

Then restart your terminal and launch Claude Code as normal.

### 4. Verify it's working

You should see log output from the proxy like:

```
[fix-cache] Moved skills SR from msg[0] to msg[3]
[fix-cache] Added cache_control to msg[0] block[1]
```

Use the included `cache_summary.py` to analyze your session's cache performance:

```bash
python3 cache_summary.py <session-id>
```

Session transcripts are stored at `~/.claude/projects/-{encoded-project-path}/{session-id}.jsonl`. Look for 95%+ cache read rates on turns after the first.

## Files

| File | Description |
|------|-------------|
| `fix_cache_addon.py` | The mitmproxy addon that fixes cache behavior |
| `cache_summary.py` | Analyzes cache hit/miss rates from session transcripts |

## How It Works (Technical Details)

Claude Code's API requests to `/v1/messages` include a `messages` array. The proxy intercepts POST requests and modifies the message structure:

**Fix 1 -- Skills block relocation:**
- Detects the skills `<system-reminder>` block in `messages[0].content[0]` (identified by containing "skills are available" or "Skill tool")
- Removes it from `messages[0]` and inserts it at the beginning of the last user message
- This prevents it from disrupting the cache chain between the system prompt and conversation history

**Fix 2 -- Cache breakpoint injection:**
- Adds `{"cache_control": {"type": "ephemeral", "ttl": "1h"}}` to the last content block of `messages[0]`
- This allows Anthropic to cache the CLAUDE.md/project instructions independently

The modified request is then forwarded to Anthropic's API normally. The response is passed back unmodified.

## Notes

- The proxy also dumps request/response pairs to a `claude-logs/` directory for debugging (you can remove this if you don't need it)
- The `DUMP_DIR` path in `fix_cache_addon.py` is hardcoded -- update it to your preferred location or remove the dump functionality
- This fix addresses the client-side request structure only. Anthropic could fix this in Claude Code directly by stabilizing the system-reminder injection and adding the missing cache breakpoint

## License

MIT
