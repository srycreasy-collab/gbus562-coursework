"""Shared plumbing for the week-05 agent team (adapted from week-04/agent.py).

API key loading, the Claude call with error handling, a generic tool-use loop,
MCP helpers, .eml parsing, printed output (with --save), and token totals.
pipeline.py and orchestrator.py both use run_cli() from here.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from email.utils import formataddr, parseaddr
from pathlib import Path

import anthropic

WEEK_DIR = Path(__file__).resolve().parent
KEY_PATH = WEEK_DIR.parents[1] / "api-key.txt"
DEFAULT_COMPANY_DIR = WEEK_DIR / "brookfield-bikes"
DRAFTS_DIR = WEEK_DIR / "drafts"

MODEL = "claude-opus-5-5"  # default only; the orchestrator and the specialists set their own model
MAX_TOKENS = 16000
PREVIEW_CHARS = 300
# On a safety decline, the API re-runs the request on a fallback model it picks.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5-2"}

STOP_REASONS = {
    "end_turn": "Claude finished without asking for another tool.",
    "max_tokens": f"Claude's reply hit the {MAX_TOKENS}-token output limit.",
    "stop_sequence": "Claude's reply hit a stop sequence.",
    "refusal": "Claude declined this request.",
    "pause_turn": "The API paused the turn.",
}


class AgentError(Exception):
    """A problem that stops the run, shown without a traceback."""


@dataclass
class IncomingEmail:
    label: str  # file name, for display and file names
    sender: str  # bare lowercase address
    reply_to: str  # "Name <address>"
    subject: str
    body: str

    def as_block(self):
        return f"<email>\nFrom: {self.reply_to}\nSubject: {self.subject}\n\n{self.body}\n</email>"


@dataclass
class Usage:
    """Token totals across every Claude call in one run, per role."""

    by_role: dict = field(default_factory=dict)
    reported: bool = False  # a coordinator already printed report()

    def add(self, role, response):
        tokens = self.by_role.setdefault(role, [0, 0, 0])
        tokens[0] += response.usage.input_tokens
        tokens[1] += response.usage.output_tokens
        tokens[2] += 1

    def totals(self, role):
        """(input, output, calls) so far for one role."""
        return tuple(self.by_role.get(role, [0, 0, 0]))

    def report(self):
        lines = ["Tokens by role (input / output, calls):"]
        total_in = total_out = 0
        for role, (used_in, used_out, calls) in self.by_role.items():
            lines.append(f"  {role:<16} {used_in:>8,} / {used_out:>7,}  ({calls} call{'s' if calls != 1 else ''})")
            total_in += used_in
            total_out += used_out
        lines.append(f"  {'total':<16} {total_in:>8,} / {total_out:>7,}")
        return "\n".join(lines)


# ------------------------------------------------------------------ Output


class Tee:
    """Writes to the console and to the --save file at the same time."""

    def __init__(self, stream, file):
        self.stream = stream
        self.file = file
        self.lock = threading.Lock()

    def write(self, text):
        with self.lock:
            self.stream.write(text)
            self.file.write(text)
        return len(text)

    def flush(self):
        with self.lock:
            self.stream.flush()
            self.file.flush()


def preview(text):
    text = str(text)
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + "..."


def print_step(role, number, name, inputs, result):
    print(f"\n--- [{role}] Step {number}: {name}")
    print(f"Inputs: {json.dumps(inputs, ensure_ascii=False)}")
    print(f"Result: {preview(result)}")


def banner(text):
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


class ServerLog:
    """A pipe for an MCP server's stderr, so its messages go through print (and --save)."""

    def __enter__(self):
        read_fd, write_fd = os.pipe()
        self.writer = os.fdopen(write_fd, "w", encoding="utf-8")
        self.reader = os.fdopen(read_fd, "r", encoding="utf-8", errors="replace")
        self.thread = threading.Thread(target=self._copy, daemon=True)
        self.thread.start()
        return self.writer

    def _copy(self):
        for line in self.reader:
            print(f"[server] {line.rstrip()}", file=sys.stderr, flush=True)

    def __exit__(self, *exc):
        self.writer.close()
        self.thread.join(timeout=5)
        self.reader.close()


# ------------------------------------------------------------------ Inputs


def read_api_key():
    try:
        key = KEY_PATH.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise AgentError(f"Couldn't read the API key file {KEY_PATH}: {error.strerror}")
    if not key:
        raise AgentError(f"The API key file {KEY_PATH} is empty.")
    return key


def resolve_company(value):
    """The company folder: the path as given, or else a folder of that name in week-05."""
    path = Path(value).expanduser()
    if not path.is_dir() and not path.is_absolute() and (WEEK_DIR / path).is_dir():
        path = WEEK_DIR / path
    path = path.resolve()
    if not path.is_dir():
        raise AgentError(f"--org: folder not found: {value}")
    return path


def company_name(company_dir):
    """A short name for the company, from its folder: brookfield-bikes -> Brookfield."""
    return re.split(r"[-_\s]+", company_dir.name)[0].capitalize() or company_dir.name


def read_prompt(company_dir, name):
    """One specialist's system prompt, from <company>/prompts/<name>.txt."""
    path = company_dir / "prompts" / f"{name}.txt"
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise AgentError(f"Couldn't read the prompt {path}: {error.strerror}")
    if not prompt:
        raise AgentError(f"The prompt {path} is empty.")
    return prompt


def read_email_file(path):
    try:
        data = path.read_bytes()
    except OSError as error:
        raise AgentError(f"Couldn't read the email file {path}: {error.strerror}")
    message = BytesParser(policy=policy.default).parsebytes(data)

    name, sender = parseaddr(str(message.get("From", "")))
    sender = sender.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", sender):
        raise AgentError(f"No valid sender address in the From line of {path.name}.")

    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        raise AgentError(f"{path.name} has no readable text body.")
    body = part.get_content()
    if part.get_content_type() == "text/html":
        body = re.sub(r"<(script|style)\b.*?</\1>", " ", body, flags=re.S | re.I)
        body = re.sub(r"<br\s*/?>|</p>", "\n", body, flags=re.I)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"[ \t]+", " ", body)

    return IncomingEmail(
        label=path.name,
        sender=sender,
        reply_to=formataddr((name, sender)) if name else sender,
        subject=str(message.get("Subject", "")).strip(),
        body=body.strip(),
    )


# ------------------------------------------------------------------ Claude


async def ask_claude(client, usage, role, *, system, messages, effort, tools=None, model=MODEL, tool_choice=None):
    """One Messages API call. Returns the response; counts its tokens under role."""
    kwargs = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": messages,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
    }
    if model in FALLBACK_MODELS:
        kwargs["betas"] = [FALLBACK_BETA]
        kwargs["fallbacks"] = "default"
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    try:
        response = await client.beta.messages.create(**kwargs)
    except anthropic.AuthenticationError:
        raise AgentError(f"The API key in {KEY_PATH} was rejected.")
    except anthropic.NotFoundError as error:
        raise AgentError(f"The API couldn't find the model {model}: {error.message}")
    except anthropic.RateLimitError:
        raise AgentError("The API rate limit was reached. Wait a minute and try again.")
    except anthropic.BadRequestError as error:
        raise AgentError(f"The API rejected the request: {error.message}")
    except anthropic.APIStatusError as error:
        raise AgentError(f"The API returned an error ({error.status_code}): {error.message}")
    except anthropic.APIConnectionError:
        raise AgentError("Couldn't connect to the Anthropic API. Check your internet connection.")

    usage.add(role, response)
    print(f"[{role}] tokens for this call ({model}): {response.usage.input_tokens:,} in / {response.usage.output_tokens:,} out")
    for block in response.content:
        if block.type == "fallback":
            print(f"[{role}] Note: {block.from_.model} declined; {block.to.model} answered instead.")
    return response


def text_of(response):
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


async def ask_for_text(client, usage, role, *, system, messages, effort, model=MODEL):
    """A single call with no tools that must end with text. Returns (text, response)."""
    response = await ask_claude(client, usage, role, system=system, messages=messages, effort=effort, model=model)
    if response.stop_reason in ("refusal", "max_tokens"):
        raise AgentError(f"The {role}: {STOP_REASONS[response.stop_reason]}")
    text = text_of(response)
    if not text:
        raise AgentError(f"The {role} returned no text.")
    return text, response


@dataclass
class LoopResult:
    final_text: str
    stop_text: str
    tool_calls: int
    stopped_by_tool: bool  # a tool handler asked the loop to end (e.g. finish)
    hit_limit: bool = False  # max_tool_calls was reached; the last message is the tool results


async def run_tool_loop(
    client, usage, role, *, system, messages, tools, handle_tool, effort, max_tool_calls, model=MODEL, describe_result=None
):
    """The agent loop: call Claude, run the tools it asks for, repeat.

    messages is extended in place, so a caller can add a user turn and continue.
    handle_tool(name, inputs) is async and returns (text, is_error, stop).
    describe_result(name, text), if given, returns what to print for a tool result
    (by default, its first PREVIEW_CHARS characters).
    Ends when Claude answers without a tool request, when a handler returns
    stop=True, or when max_tool_calls tool calls have been used.
    """
    tool_calls = 0
    while True:
        response = await ask_claude(client, usage, role, system=system, messages=messages, effort=effort, tools=tools, model=model)
        # Keep Claude's whole reply (including thinking blocks) in the history.
        messages.append({"role": "assistant", "content": response.content})

        requests = [block for block in response.content if block.type == "tool_use"]
        if response.stop_reason != "tool_use" or not requests:
            stop_text = STOP_REASONS.get(response.stop_reason, f"Claude stopped (stop reason: {response.stop_reason}).")
            return LoopResult(text_of(response), stop_text, tool_calls, False)

        results = []
        stop = False
        for request in requests:
            if tool_calls >= max_tool_calls:
                text, is_error = f"Tool call limit ({max_tool_calls}) reached; this call was not run.", True
            else:
                tool_calls += 1
                inputs = request.input or {}
                text, is_error, wants_stop = await handle_tool(request.name, inputs)
                stop = stop or wants_stop
                shown = describe_result(request.name, text) if describe_result else text
                print_step(role, tool_calls, request.name, inputs, shown)
            results.append({"type": "tool_result", "tool_use_id": request.id, "content": text, "is_error": is_error})
        messages.append({"role": "user", "content": results})

        if stop:
            return LoopResult(text_of(response), "A tool ended the run.", tool_calls, True)
        if tool_calls >= max_tool_calls:
            return LoopResult(text_of(response), f"Stopped after the limit of {max_tool_calls} tool calls.", tool_calls, False, True)


# --------------------------------------------------------------------- MCP


def unwrap(error):
    """The MCP client's task group can wrap an error in an ExceptionGroup; get the real one."""
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return error


async def call_mcp_tool(session, name, inputs):
    """Run one MCP tool and return (text, is_error)."""
    try:
        result = await session.call_tool(name, inputs)
    except Exception as error:  # a failed call goes back to Claude as an error result
        return f"The {name} tool failed: {error}", True
    texts = [b.text for b in getattr(result, "content", None) or [] if getattr(b, "type", "") == "text"]
    text = "\n".join(texts) or "(the tool returned no text)"
    return text, bool(getattr(result, "is_error", False))


# --------------------------------------------------------------------- CLI


def run_cli(description, coordinate):
    """Shared command line for pipeline.py and orchestrator.py.

    coordinate(client, usage, company_dir, email, email_path) is async and returns
    an exit code.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--email", required=True, metavar="PATH", help="the supplier email (.eml) to handle")
    parser.add_argument(
        "--org",
        "--company",
        dest="org",
        metavar="FOLDER",
        default=str(DEFAULT_COMPANY_DIR),
        help="company folder with the five CSV files, prompts/ and supplier-emails/ (default: week-05/brookfield-bikes)",
    )
    parser.add_argument("--save", metavar="FILE", help="also write everything printed to FILE (UTF-8)")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    save_file = None
    if args.save:
        save_path = Path(args.save)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_file = save_path.open("w", encoding="utf-8")
        sys.stdout = Tee(sys.stdout, save_file)
        sys.stderr = Tee(sys.stderr, save_file)

    async def run():
        company_dir = resolve_company(args.org)
        email_path = Path(args.email).resolve()
        email = read_email_file(email_path)
        usage = Usage()
        async with anthropic.AsyncAnthropic(api_key=read_api_key()) as client:
            try:
                return await coordinate(client, usage, company_dir, email, email_path)
            finally:
                if not usage.reported:
                    print()
                    print(usage.report())

    try:
        return asyncio.run(run())
    except AgentError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    finally:
        if save_file:
            sys.stdout.flush()
            sys.stdout = sys.stdout.stream
            sys.stderr = sys.stderr.stream
            save_file.close()
