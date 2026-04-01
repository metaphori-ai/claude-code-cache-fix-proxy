"""
Analyze Claude Code session cache hit/miss rates from transcript JSONL files.

Usage:
    python3 cache_summary.py <session-id>       # search all projects for session
    python3 cache_summary.py <path-to-jsonl>     # analyze a specific file
    python3 cache_summary.py --list              # list recent sessions

Session transcripts live at:
    ~/.claude/projects/-{encoded-project-path}/{session-id}.jsonl
"""
import json
import sys
import os
import glob

PROJECTS_DIR = os.path.expanduser('~/.claude/projects')


def find_session_path(session_id):
    """Find the JSONL file for a session ID across all project directories."""
    # Check if it's a direct file path
    if os.path.isfile(session_id):
        return session_id

    # Search all project directories
    for project_dir in glob.glob(os.path.join(PROJECTS_DIR, '*')):
        if not os.path.isdir(project_dir):
            continue
        path = os.path.join(project_dir, f'{session_id}.jsonl')
        if os.path.exists(path):
            return path
        # Try partial match
        pattern = os.path.join(project_dir, f'{session_id}*.jsonl')
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None


def list_recent_sessions(limit=15):
    """List recent sessions across all projects."""
    all_sessions = []
    for project_dir in glob.glob(os.path.join(PROJECTS_DIR, '*')):
        if not os.path.isdir(project_dir):
            continue
        for jsonl in glob.glob(os.path.join(project_dir, '*.jsonl')):
            all_sessions.append((jsonl, os.path.getmtime(jsonl)))

    all_sessions.sort(key=lambda x: x[1], reverse=True)
    print(f"Recent sessions (showing {min(limit, len(all_sessions))} of {len(all_sessions)}):\n")
    for path, mtime in all_sessions[:limit]:
        project = os.path.basename(os.path.dirname(path))
        session_id = os.path.basename(path).replace('.jsonl', '')
        print(f"  {session_id}  ({project})")


def analyze_session(path):
    """Analyze cache behavior for a session transcript."""
    with open(path) as f:
        entries = [json.loads(line.strip()) for line in f if line.strip()]

    session_file = os.path.basename(path)
    project = os.path.basename(os.path.dirname(path))
    print(f"Session: {session_file}")
    print(f"Project: {project}")
    print(f"Entries: {len(entries)}")
    print()
    print("Entry | Type         | cache_create | cache_read | input | output | total_in  | read%  | NOTES")
    print("-" * 120)

    turn = 0
    total_create = 0
    total_read = 0
    total_input = 0
    total_output = 0
    invalidation_count = 0

    for i, entry in enumerate(entries):
        if entry.get('type') != 'assistant':
            continue
        msg = entry.get('message', {})
        usage = msg.get('usage')
        if not usage:
            continue

        cc = usage.get('cache_creation_input_tokens', 0)
        cr = usage.get('cache_read_input_tokens', 0)
        inp = usage.get('input_tokens', 0)
        out = usage.get('output_tokens', 0)
        total = cc + cr + inp

        if total == 0:
            continue

        read_pct = (cr / total) * 100 if total else 0

        notes = []
        if cr == 0 and cc > 0:
            notes.append("FULL CACHE MISS - creating from scratch")
            invalidation_count += 1
        elif cr > 0 and cc > 20000:
            notes.append(f"PARTIAL HIT - {cc} tokens re-created!")
            invalidation_count += 1
        elif cr > 0 and cc < 5000:
            notes.append("good cache hit")

        turn += 1
        total_create += cc
        total_read += cr
        total_input += inp
        total_output += out

        print(f"[{i:3d}]  turn {turn:2d}  | {cc:>8,} create | {cr:>8,} read | {inp:>5,} in | {out:>5,} out | {total:>8,} tot | {read_pct:5.1f}% | {' | '.join(notes)}")

    # Summary
    print()
    print("=" * 80)
    print("SESSION SUMMARY")
    print("=" * 80)
    print(f"Total turns:             {turn}")
    if turn > 0:
        print(f"Cache invalidations:     {invalidation_count} ({invalidation_count/turn*100:.0f}% of turns)")
    print(f"Total cache_create:      {total_create:>10,} tokens (charged at 2x = {total_create*2:>10,} effective)")
    print(f"Total cache_read:        {total_read:>10,} tokens (charged at 0.1x = {int(total_read*0.1):>10,} effective)")
    print(f"Total uncached input:    {total_input:>10,} tokens (charged at 1x)")
    print(f"Total output:            {total_output:>10,} tokens")
    effective_input_cost = total_create * 2 + int(total_read * 0.1) + total_input
    naive_cost = total_create + total_read + total_input  # if everything were 1x
    print(f"Effective input cost:    {effective_input_cost:>10,} token-equivalents")
    print(f"If all were 1x:          {naive_cost:>10,} token-equivalents")
    if naive_cost > 0:
        overhead = ((effective_input_cost - naive_cost) / naive_cost) * 100
        print(f"Cache overhead:          {overhead:>+9.1f}%")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 cache_summary.py <session-id>    # analyze a session")
        print("  python3 cache_summary.py <path.jsonl>    # analyze a file")
        print("  python3 cache_summary.py --list          # list recent sessions")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == '--list':
        list_recent_sessions()
        sys.exit(0)

    path = find_session_path(arg)
    if not path:
        print(f"Session not found: {arg}")
        print(f"Looking in: {PROJECTS_DIR}")
        print("\nTry: python3 cache_summary.py --list")
        sys.exit(1)

    analyze_session(path)


if __name__ == '__main__':
    main()
