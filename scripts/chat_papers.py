#!/usr/bin/env python3
"""
chat_papers.py

Interactive terminal chatbot for filtering and exploring conference papers
using a local Qwen model via LM Studio at http://127.0.0.1:1234.

Run:
    python scripts/chat_papers.py

Commands you can type at any time:
    /scan UIST 2025      — scan a conference + year
    /topic <text>        — update your research topic
    /results             — re-show papers found in this scan
    /save                — save results to results/ folder
    /list                — list all available conferences
    /clear               — clear chat history
    /quit                — exit
"""

import glob
import json
import os
import re
import sys
import time

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LM_STUDIO_URL  = "http://127.0.0.1:1234/v1/chat/completions"
MODEL_NAME     = "qwen/qwen3.5-9b"
BATCH_SIZE     = 10
REQUEST_TIMEOUT = 120

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(SCRIPT_DIR)

THEMES = {}

DEFAULT_RESEARCH = "AI image generation interfaces."

# Per-paper prompt — one paper, one line answer
FILTER_SYSTEM_PROMPT = (
    "You screen academic papers. Is this paper related to AI image generation interfaces "
    "(e.g. text-to-image tools, diffusion model UIs, image synthesis interfaces, "
    "generative image editing tools)?\n"
    "Reply with EXACTLY one line: YES, MAYBE, or NO — then a pipe — then a reason in 5-10 words.\n"
    "Example: YES|Presents a text-to-image generation UI\n"
    "Example: NO|About robotics, unrelated to image generation\n"
    "Output ONLY that one line. Nothing else."
)

CHAT_SYSTEM_PROMPT = (
    "You are a helpful research assistant. The user is an HCI/AI researcher working on "
    "a modular node-based interface for AI image generation. You have just helped them "
    "filter a set of conference papers that are related to this topic. "
    "Answer questions about the papers, compare papers, "
    "or help the user think about their related work narrative. Be concise and helpful."
)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

state = {
    "research":      DEFAULT_RESEARCH,
    "conf_tag":      None,
    "conf_name":     None,
    "all_papers":    [],
    "results":       [],
    "chat_history":  [],
    "debug":         False,
    "no_think":      True,
}

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

SEP  = "─" * 70
SEP2 = "═" * 70

def pr(text=""):
    print(text)

def header(text):
    print(f"\n{SEP2}\n  {text}\n{SEP2}")

def section(text):
    print(f"\n{SEP}\n  {text}\n{SEP}")

def bot(text):
    print(f"\n🤖  {text}\n")


def discover_conferences():
    """Return a sorted list of (conf_tag, filepath) tuples for all program JSON files."""
    files = sorted(glob.glob(os.path.join(REPO_ROOT, "*_program.json")))
    result = []
    for f in files:
        tag = os.path.basename(f).replace("_program.json", "")
        result.append((tag, f))
    return result


def parse_conf_input(text):
    """
    Try to match user input like 'UIST 2025', 'uist2025', 'CHI_2024', etc.
    Returns conf_tag string or None.
    """
    text = text.strip().upper().replace("-", "_").replace(" ", "_")
    # Try direct match e.g. UIST_2025
    available = {tag: fp for tag, fp in discover_conferences()}
    if text in available:
        return text
    # Try matching without underscore e.g. UIST2025 → UIST_2025
    for tag in available:
        if tag.replace("_", "") == text.replace("_", ""):
            return tag
    return None


def load_papers(conf_tag):
    """Load all papers from a conference JSON file."""
    filepath = os.path.join(REPO_ROOT, f"{conf_tag}_program.json")
    if not os.path.exists(filepath):
        return None, None
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    conf_name = data.get("conference", {}).get("name", conf_tag)
    papers = []
    for item in data.get("contents", []):
        title = item.get("title", "").strip()
        if not title:
            continue
        papers.append({
            "id":         item.get("id"),
            "title":      title,
            "abstract":   item.get("abstract", "").strip(),
            "keywords":   item.get("keywords", []),
            "url":        item.get("url", ""),
            "conference": conf_name,
            "conf_tag":   conf_tag,
        })
    return conf_name, papers


def strip_think(content):
    """Remove Qwen's think block. Handles both <think> tags and plain 'Thinking Process:' text."""
    # Standard <think>...</think> tags
    end = content.find("</think>")
    if end != -1:
        return content[end + 8:].strip()
    return content.strip()


IMPORT_RE = re.compile(r'^\s*(\d+)[\s\.\)]?\|\s*(YES|MAYBE|NO)\s*\|(.*)$', re.IGNORECASE)


def extract_verdicts(content, batch_size):
    """
    Pull out verdict lines from anywhere in the response — handles models that
    write reasoning as plain text before the final answer.
    Returns list of (0-based-index, verdict, reason).
    """
    matches = []
    seen = set()
    for line in content.splitlines():
        m = IMPORT_RE.match(line)
        if m:
            idx = int(m.group(1)) - 1
            verdict = m.group(2).strip().upper()
            reason  = m.group(3).strip()
            if 0 <= idx < batch_size and idx not in seen:
                seen.add(idx)
                matches.append((idx, verdict, reason))
    return matches


def call_llm(messages, max_tokens=2048, temperature=0.1, show_raw=False):
    """Call LM Studio API. Returns (thinking, content) tuple."""
    # Inject /no_think token into system prompt when thinking is disabled
    patched = []
    for m in messages:
        if m["role"] == "system" and state.get("no_think"):
            # /no_think is already in FILTER_SYSTEM_PROMPT; only add for chat messages
            if "/no_think" not in m["content"]:
                patched.append({**m, "content": "/no_think\n" + m["content"]})
            else:
                patched.append(m)
        else:
            patched.append(m)

    payload = {
        "model":       MODEL_NAME,
        "messages":    patched,
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "stream":      False,
    }
    try:
        resp = requests.post(LM_STUDIO_URL, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]

        # Split think block from answer — handle both <think> tags and plain text reasoning
        think_end = raw.find("</think>")
        if think_end != -1:
            thinking = raw[:think_end].replace("<think>", "").strip()
            content  = raw[think_end + 8:].strip()
        else:
            # No tags — return full content; extract_verdicts will find the answer lines
            thinking = ""
            content  = raw.strip()

        return thinking, content
    except requests.RequestException as e:
        return "", f"[API error: {e}]"


VERDICT_RE = re.compile(r'(YES|MAYBE|NO)\s*[|:]\s*(.+)', re.IGNORECASE)


def filter_one(paper):
    """Evaluate a single paper. Returns (verdict, reason)."""
    snippet = paper["abstract"][:400] + ("…" if len(paper["abstract"]) > 400 else "")
    user_msg = f"Title: {paper['title']}\nAbstract: {snippet}"
    messages = [
        {"role": "system", "content": FILTER_SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]
    _, content = call_llm(messages, max_tokens=60)

    if state["debug"]:
        print(f"     RAW: {repr(content[:200])}")

    # Search entire response for a YES/MAYBE/NO verdict
    for line in content.splitlines():
        m = VERDICT_RE.search(line)
        if m:
            verdict = m.group(1).strip().upper()
            reason  = m.group(2).strip()
            return verdict, reason
    return "NO", "Could not parse response."


def filter_batch(batch):
    """Evaluate each paper in the batch one at a time."""
    results = []
    for paper in batch:
        verdict, reason = filter_one(paper)
        results.append({"paper": paper, "verdict": verdict, "theme": "", "reason": reason})
        if state["debug"]:
            icon = "✅" if verdict == "YES" else ("🔶" if verdict == "MAYBE" else "❌")
            print(f"     {icon} {verdict} | {paper['title'][:50]} | {reason[:50]}")
    return results


def print_result(r, index):
    """Print a single found paper nicely."""
    p = r["paper"]
    verdict = r["verdict"]
    icon = "✅" if verdict == "YES" else "🔶"
    theme_label = THEMES.get(r.get("theme", ""), "")
    print(f"\n  {icon} [{index}] {p['title']}")
    print(f"       {p['conference']}")
    if theme_label:
        print(f"       Theme: {theme_label}")
    print(f"       {r['reason']}")


def run_scan(conf_tag):
    """Run the filtering scan for the given conference tag."""
    conf_name, papers = load_papers(conf_tag)
    if papers is None:
        bot(f"Could not find file for '{conf_tag}'. Type /list to see available conferences.")
        return

    state["conf_tag"]   = conf_tag
    state["conf_name"]  = conf_name
    state["all_papers"] = papers
    state["results"]    = []
    state["chat_history"] = []

    section(f"Scanning {conf_name} — {len(papers)} papers")
    think_mode = "OFF (fast)" if state["no_think"] else "ON (slower)"
    debug_mode = "ON" if state["debug"] else "OFF"
    print(f"  Research topic: {state['research'].splitlines()[0][:80]}…")
    print(f"  Batch size: {BATCH_SIZE} | Model: {MODEL_NAME}")
    print(f"  Thinking: {think_mode} | Debug: {debug_mode}  (toggle with /think, /debug)\n")

    total = len(papers)
    found_count = 0

    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{total}] {paper['title'][:65]}...", end=" ", flush=True)
        t0 = time.time()
        verdict, reason = filter_one(paper)
        elapsed = time.time() - t0

        if verdict in ("YES", "MAYBE"):
            result = {"paper": paper, "verdict": verdict, "theme": "", "reason": reason}
            found_count += 1
            state["results"].append(result)
            print(f"{'✅ YES' if verdict == 'YES' else '🔶 MAYBE'}  ({elapsed:.1f}s)")
            print_result(result, found_count)
        else:
            print(f"no  ({elapsed:.1f}s)")

    section(f"Scan complete: {found_count} related papers found in {conf_name}")
    print("  You can now ask me anything about these papers.")
    print("  Type /save to save results, or /scan CONF YEAR to scan another conference.\n")


def build_chat_context():
    """Build a context string of found papers for the chat LLM."""
    if not state["results"]:
        return "No papers have been found yet in the current scan."
    lines = [f"Conference scanned: {state['conf_name']}", "",
             "Related papers found:"]
    for i, r in enumerate(state["results"], 1):
        p = r["paper"]
        theme_label = THEMES.get(r.get("theme", ""), "")
        lines.append(
            f"\n[{i}] {p['title']}\n"
            f"    Verdict: {r['verdict']} | Theme: {theme_label}\n"
            f"    Reason: {r['reason']}\n"
            f"    Abstract: {p['abstract'][:300]}{'…' if len(p['abstract']) > 300 else ''}"
        )
    return "\n".join(lines)


def chat(user_input):
    """Send a chat message to the LLM with full paper context."""
    context = build_chat_context()
    messages = [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT + "\n\nContext:\n" + context},
    ]
    # Include recent chat history (last 6 turns)
    for turn in state["chat_history"][-6:]:
        messages.append(turn)
    messages.append({"role": "user", "content": user_input})

    print("\n🤖  ", end="", flush=True)
    _, response = call_llm(messages, max_tokens=1024, temperature=0.3)
    print(response)
    print()

    state["chat_history"].append({"role": "user",      "content": user_input})
    state["chat_history"].append({"role": "assistant", "content": response})


def save_results():
    """Save current results to files."""
    if not state["results"]:
        bot("No results to save yet. Run a scan first with /scan CONF YEAR.")
        return

    results_dir = os.path.join(REPO_ROOT, "results")
    os.makedirs(results_dir, exist_ok=True)
    tag = state["conf_tag"] or "unknown"
    base = os.path.join(results_dir, f"related_{tag}")

    # JSON
    json_path = base + ".json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "verdict":   r["verdict"],
                    "theme_id":  r.get("theme", ""),
                    "theme":     THEMES.get(r.get("theme", ""), ""),
                    "reason":    r["reason"],
                    **r["paper"],
                }
                for r in state["results"]
            ],
            f, ensure_ascii=False, indent=2,
        )

    # Markdown
    md_path = base + ".md"
    yes_papers   = [r for r in state["results"] if r["verdict"] == "YES"]
    maybe_papers = [r for r in state["results"] if r["verdict"] == "MAYBE"]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Related Papers — {state['conf_name']}\n\n")
        f.write(f"**Research topic:** {state['research'].splitlines()[0]}\n\n")
        for heading, group in [("Strongly Related (YES)", yes_papers),
                                ("Possibly Related (MAYBE)", maybe_papers)]:
            if not group:
                continue
            f.write(f"## {heading}\n\n")
            for i, r in enumerate(group, 1):
                p = r["paper"]
                theme_label = THEMES.get(r.get("theme", ""), "")
                f.write(f"### {i}. {p['title']}\n")
                f.write(f"**Conference:** {p['conference']}  \n")
                if p.get("url"):
                    f.write(f"**URL:** {p['url']}  \n")
                if theme_label:
                    f.write(f"**Relevant theme:** {theme_label}  \n")
                f.write(f"**Reason:** {r['reason']}  \n\n")
                if p["abstract"]:
                    snippet = p["abstract"][:400]
                    if len(p["abstract"]) > 400:
                        snippet += "…"
                    f.write(f"> {snippet}\n\n")

    bot(
        f"Saved!\n"
        f"  JSON     → results/related_{tag}.json\n"
        f"  Markdown → results/related_{tag}.md\n"
        f"  ({len(yes_papers)} YES, {len(maybe_papers)} MAYBE)"
    )


def show_results():
    """Re-print all found papers."""
    if not state["results"]:
        bot("No results yet. Run /scan CONF YEAR first.")
        return
    section(f"Found papers in {state['conf_name']}")
    for i, r in enumerate(state["results"], 1):
        print_result(r, i)
    print()


def show_list():
    """Print all available conferences."""
    section("Available conferences")
    confs = discover_conferences()
    # Group by conference name
    groups = {}
    for tag, _ in confs:
        parts = tag.split("_")
        name, year = "_".join(parts[:-1]), parts[-1]
        groups.setdefault(name, []).append(year)
    for name, years in sorted(groups.items()):
        print(f"  {name:10}  {', '.join(sorted(years))}")
    print()
    print("  Type: /scan UIST 2025  (or just type  UIST 2025)")
    print()


def handle_command(text):
    """Handle slash commands."""
    parts = text.strip().split(None, 2)
    cmd = parts[0].lower()

    if cmd in ("/quit", "/exit", "/q"):
        bot("Goodbye!")
        sys.exit(0)

    elif cmd == "/list":
        show_list()

    elif cmd == "/results":
        show_results()

    elif cmd == "/save":
        save_results()

    elif cmd == "/clear":
        state["chat_history"] = []
        bot("Chat history cleared.")

    elif cmd == "/debug":
        if len(parts) > 1 and parts[1].lower() == "off":
            state["debug"] = False
            bot("Debug mode OFF — reasoning hidden.")
        else:
            state["debug"] = True
            bot("Debug mode ON — you'll see the model's reasoning and parsed lines for each batch.")

    elif cmd == "/think":
        if len(parts) > 1 and parts[1].lower() == "on":
            state["no_think"] = False
            bot("Thinking mode ON — model will reason before answering (slower, ~25s/batch).")
        else:
            state["no_think"] = True
            bot("Thinking mode OFF — model answers directly (faster, ~5s/batch).")

    elif cmd == "/topic":
        if len(parts) < 2:
            bot("Usage: /topic <your research description>")
        else:
            state["research"] = parts[1] if len(parts) == 2 else " ".join(parts[1:])
            bot(f"Research topic updated to:\n  {state['research'][:120]}")

    elif cmd == "/scan":

        if len(parts) < 2:
            bot("Usage: /scan CONF YEAR  (e.g. /scan UIST 2025)")
        else:
            raw = " ".join(parts[1:])
            tag = parse_conf_input(raw)
            if tag:
                run_scan(tag)
            else:
                bot(f"Conference '{raw}' not found. Type /list to see what's available.")
    else:
        bot(f"Unknown command '{cmd}'. Type /list, /scan, /results, /save, /topic, /debug, /think, /quit.")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    header("📚 ReadingRoom — Paper Filter Chatbot")
    print("  Model : " + MODEL_NAME)
    print("  Server: http://127.0.0.1:1234")

    # Check LM Studio is reachable
    try:
        ping = requests.get("http://127.0.0.1:1234/v1/models", timeout=8)
        ping.raise_for_status()
        models = [m["id"] for m in ping.json().get("data", [])]
        print(f"  Status: ✅ Connected  ({', '.join(models)})")
    except requests.RequestException as e:
        print(f"  Status: ❌ Cannot reach LM Studio — {e}")
        print("  Make sure LM Studio is running and a model is loaded.")
        sys.exit(1)

    print()
    print("  Type a conference to scan (e.g. UIST 2025, CHI 2024)")
    print("  Or type /list to see all available conferences")
    print("  /debug — show model reasoning | /think on/off — toggle thinking mode")
    print("  Type /quit to exit")
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            bot("Goodbye!")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            handle_command(user_input)
        elif user_input.lower() in ("list", "ls"):
            show_list()
        elif user_input.lower() in ("quit", "exit", "q"):
            bot("Goodbye!")
            break
        elif user_input.lower() in ("save",):
            save_results()
        elif user_input.lower() in ("results",):
            show_results()
        else:
            # Try to parse as a conference selection first
            tag = parse_conf_input(user_input)
            if tag:
                run_scan(tag)
            elif state["conf_name"]:
                # We have a loaded conference — treat as chat
                chat(user_input)
            else:
                bot(
                    "I didn't recognise that as a conference name.\n"
                    "  Try: UIST 2025, CHI 2024, DIS 2023, etc.\n"
                    "  Or type /list to see all available conferences."
                )


if __name__ == "__main__":
    main()
