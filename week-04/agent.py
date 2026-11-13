"""Hartwell Foods HR agent: drafts replies to employee emails using Claude's tool use.

Two ways to run it (pick one):

    --email PATH   Handle one .eml file. save_reply writes a draft to week-04/drafts/.
    --inbox        Sign in to the Gmail sandbox with IMAP (login from Agent-Email.txt in
                   the folder above the repository) and handle each unread inbox email,
                   one at a time, as its own separate agent run. Each email is marked as
                   read before work starts, so no email is handled twice. save_reply
                   creates a Gmail draft replying to the sender in the same thread.

Nothing is ever sent. This program only reads mail and creates drafts.

For each email, the agent:

    1. Reads the sender's address from the email's From header.
    2. Starts hr_mcp_server.py in employee mode (--as-employee <sender>), so the
       leave-balance tool can only ever return the sender's own balance.
    3. Offers Claude the server's tools plus one local tool, save_reply.
    4. Loops until Claude replies without a tool request, or 10 tool calls are used.

Add --save FILE to also write everything printed to FILE (UTF-8).

Run from the top of the repository:

    .venv\\Scripts\\python.exe week-04\\agent.py --email week-04\\hartwell-hr\\sample-emails\\03-megan-time-off.eml
    .venv\\Scripts\\python.exe week-04\\agent.py --inbox --save week-04\\inbox-run.txt

The API key comes from api-key.txt in the folder above the repository. Neither it
nor the mailbox password is ever printed or written to a file.
"""

import argparse
import asyncio
import imaplib
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from pathlib import Path

import anthropic
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from load_inbox import LoadError, read_login

WEEK_DIR = Path(__file__).resolve().parent
KEY_PATH = WEEK_DIR.parents[1] / "api-key.txt"
SYSTEM_PROMPT_PATH = WEEK_DIR / "hartwell-hr" / "system_prompt.txt"
SERVER_PATH = WEEK_DIR / "hr_mcp_server.py"
DRAFTS_DIR = WEEK_DIR / "drafts"

MODEL = "claude-sonnet-5"
MAX_TOKENS = 16000
MAX_TOOL_CALLS = 10
PREVIEW_CHARS = 300
REVIEW_PREFIX = "[NEEDS HR REVIEW]"
REVIEW_LABEL = "Needs HR Review"  # Gmail label put on threads whose draft needs review
INBOX = "INBOX"
FALLBACK_DRAFTS_MAILBOX = "[Gmail]/Drafts"

SAVE_REPLY_TOOL = {
    "name": "save_reply",
    "description": (
        "Save your reply to the employee as a draft for the HR team to review. This only "
        "saves the draft; it never sends anything. Call it exactly once, when the reply is final."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reply_text": {
                "type": "string",
                "description": "The full text of the reply to the employee.",
            },
            "needs_human_review": {
                "type": "boolean",
                "description": "true if a person from HR must handle or check this before anything is sent.",
            },
        },
        "required": ["reply_text", "needs_human_review"],
        "additionalProperties": False,
    },
    "strict": True,
}

STOP_REASONS = {
    "end_turn": "Claude finished its reply without asking for another tool.",
    "max_tokens": f"Claude's reply hit the {MAX_TOKENS}-token output limit.",
    "stop_sequence": "Claude's reply hit a stop sequence.",
    "refusal": "Claude declined to answer this email.",
    "pause_turn": "The API paused the turn.",
}


class AgentError(Exception):
    """A problem that stops the agent, shown without a traceback."""


@dataclass
class IncomingEmail:
    label: str  # file name or "inbox message N", for display and draft file names
    sender: str  # bare lowercase address; decides whose balance the server can see
    reply_to: str  # "Name <address>" to put in the draft's To line
    subject: str
    body: str
    message_id: str
    references: str


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


def print_step(number, name, inputs, result):
    print(f"\n--- Step {number}: {name}")
    print(f"Inputs: {json.dumps(inputs, ensure_ascii=False)}")
    print(f"Result: {preview(result)}")


def reply_subject(subject, needs_review):
    base = subject if subject.lower().startswith("re:") else f"Re: {subject}".rstrip()
    return f"{REVIEW_PREFIX} {base}" if needs_review else base


class ServerLog:
    """A pipe for the MCP server's stderr, so its messages go through print (and --save)."""

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
        self.writer.close()  # the reader sees end-of-file once the server has exited too
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


def read_system_prompt():
    try:
        prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise AgentError(f"Couldn't read the system prompt {SYSTEM_PROMPT_PATH}: {error.strerror}")
    if not prompt:
        raise AgentError(f"The system prompt {SYSTEM_PROMPT_PATH} is empty.")
    return prompt


def parse_email(data, label):
    """Build an IncomingEmail from raw message bytes."""
    message = BytesParser(policy=policy.default).parsebytes(data)

    name, sender = parseaddr(str(message.get("From", "")))
    sender = sender.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", sender):
        raise AgentError(f"No valid sender address in the From line of {label}.")

    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        raise AgentError(f"{label} has no readable text body.")
    body = part.get_content()
    if part.get_content_type() == "text/html":
        body = re.sub(r"<(script|style)\b.*?</\1>", " ", body, flags=re.S | re.I)
        body = re.sub(r"<br\s*/?>|</p>", "\n", body, flags=re.I)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"[ \t]+", " ", body)

    return IncomingEmail(
        label=label,
        sender=sender,
        reply_to=formataddr((name, sender)) if name else sender,
        subject=str(message.get("Subject", "")).strip(),
        body=body.strip(),
        message_id=str(message.get("Message-ID", "")).strip(),
        references=" ".join(str(message.get("References", "")).split()),
    )


def read_email_file(path):
    try:
        data = path.read_bytes()
    except OSError as error:
        raise AgentError(f"Couldn't read the email file {path}: {error.strerror}")
    return parse_email(data, path.name)


# ------------------------------------------------------------ Draft savers


class FileDraftSaver:
    """--email mode: save_reply writes a text file to week-04/drafts/."""

    def __init__(self, email, source_path):
        self.email = email
        self.source_path = source_path

    def save(self, reply_text, needs_review):
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        draft_path = DRAFTS_DIR / f"{self.source_path.stem}-{stamp}.txt"
        draft = (
            "DRAFT - NOT SENT\n"
            f"To: {self.email.sender}\n"
            f"Subject: {reply_subject(self.email.subject, needs_review)}\n"
            f"Needs human review: {'yes' if needs_review else 'no'}\n"
            f"Source email: {self.source_path.name}\n"
            "\n"
            f"{reply_text.strip()}\n"
        )
        draft_path.write_text(draft, encoding="utf-8")
        return f"Draft saved to {draft_path.name}. It was not sent.", f"Draft saved to {draft_path} (not sent)", draft


class GmailDraftSaver:
    """--inbox mode: save_reply creates a Gmail draft in the same thread as the email."""

    def __init__(self, mailbox, email, thread_id, uid):
        self.mailbox = mailbox
        self.email = email
        self.thread_id = thread_id
        self.uid = uid  # the original email in INBOX, which gets the review label

    def save(self, reply_text, needs_review):
        draft = EmailMessage()
        draft["From"] = self.mailbox.address
        draft["To"] = self.email.reply_to
        draft["Subject"] = reply_subject(self.email.subject, needs_review)
        draft["Date"] = formatdate(localtime=True)
        draft["Message-ID"] = make_msgid(domain=self.mailbox.address.rsplit("@", 1)[1])
        # These two headers are what put the reply in the original email's thread.
        if self.email.message_id:
            draft["In-Reply-To"] = self.email.message_id
            draft["References"] = f"{self.email.references} {self.email.message_id}".strip()
        draft.set_content(reply_text.strip() + "\n")

        same_thread = self.mailbox.add_draft(draft.as_bytes(policy=policy.SMTP), self.thread_id)
        thread_note = {
            True: "It is in the same Gmail thread as the original email.",
            False: "WARNING: Gmail put it in a different thread from the original email.",
            None: "The thread couldn't be checked.",
        }[same_thread]

        # Gmail shows the thread's first subject, so the prefix alone is easy to miss.
        # A label on the original email shows on the thread in the Inbox and Drafts lists.
        label_note = ""
        if needs_review:
            if self.mailbox.add_label(self.uid, REVIEW_LABEL):
                label_note = f" (Gmail label '{REVIEW_LABEL}' added to the thread)"
            else:
                label_note = f" (WARNING: couldn't add the Gmail label '{REVIEW_LABEL}')"
        display = (
            f"To: {draft['To']}\n"
            f"Subject: {draft['Subject']}\n"
            f"Needs human review: {'yes' if needs_review else 'no'}{label_note}\n"
            f"Thread: {thread_note}\n"
            "\n"
            f"{reply_text.strip()}\n"
        )
        return (
            f"Gmail draft created (not sent). {thread_note}",
            f"Gmail draft created in {self.mailbox.drafts} (not sent)",
            display,
        )


# --------------------------------------------------------------------- IMAP


def quote(mailbox):
    return '"' + mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Mailbox:
    """The Gmail sandbox over IMAP: read inbox mail, mark it read, add drafts. No sending."""

    def __init__(self):
        try:
            host, self.address, password = read_login()
        except LoadError as error:
            raise AgentError(str(error))
        try:
            self.imap = imaplib.IMAP4_SSL(host)
        except OSError as error:
            raise AgentError(f"Couldn't connect to the IMAP server: {type(error).__name__}")
        try:
            self.imap.login(self.address, password)
        except imaplib.IMAP4.error:
            raise AgentError(
                "Sign-in failed. Check the login in Agent-Email.txt. Gmail needs IMAP turned on "
                "and an app password."
            )
        finally:
            password = None  # don't keep it around longer than needed
        self.drafts = self._find_drafts_mailbox()

    def _find_drafts_mailbox(self):
        status, lines = self.imap.list()
        for line in lines if status == "OK" else []:
            text = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
            match = re.match(r'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$', text)
            if match and "\\drafts" in match.group("flags").lower():
                name = match.group("name").strip()
                return name[1:-1].replace('\\"', '"').replace("\\\\", "\\") if name.startswith('"') else name
        return FALLBACK_DRAFTS_MAILBOX

    def _check(self, status, data, what):
        if status != "OK":
            detail = data[0].decode(errors="replace") if data and isinstance(data[0], bytes) else status
            raise AgentError(f"IMAP couldn't {what}: {detail}")

    def select_inbox(self):
        self._check(*self.imap.select(INBOX), f"open {INBOX}")

    def unread_uids(self):
        self.select_inbox()
        status, data = self.imap.uid("SEARCH", None, "UNSEEN")
        self._check(status, data, "search for unread email")
        return data[0].split() if data and data[0] else []

    def claim(self, uid):
        """Mark the email read and return (raw bytes, Gmail thread id), or None if already read."""
        self.select_inbox()
        status, data = self.imap.uid("FETCH", uid, "(FLAGS X-GM-THRID)")
        self._check(status, data, "read the email's flags")
        info = b" ".join(part for part in data if isinstance(part, bytes))
        if not info or b"\\Seen" in info:
            return None  # handled already (or gone) since the search
        thread = re.search(rb"X-GM-THRID (\d+)", info)

        # Marked read before any work, so a second run never picks it up again.
        self._check(*self.imap.uid("STORE", uid, "+FLAGS", "(\\Seen)"), "mark the email as read")

        status, data = self.imap.uid("FETCH", uid, "(BODY.PEEK[])")
        self._check(status, data, "download the email")
        raw = next((part[1] for part in data if isinstance(part, tuple)), None)
        if raw is None:
            raise AgentError("IMAP returned no content for the email.")
        return raw, (thread.group(1) if thread else None)

    def add_draft(self, data, thread_id):
        """Append a draft; return True/False for "same thread as thread_id", or None if unknown."""
        status, response = self.imap.append(quote(self.drafts), "(\\Draft)", imaplib.Time2Internaldate(time.time()), data)
        self._check(status, response, "create the draft")
        if not thread_id:
            return None
        answer = b" ".join(part for part in response if isinstance(part, bytes))
        appended = re.search(rb"APPENDUID \d+ (\d+)", answer)
        if not appended:
            return None
        try:
            self._check(*self.imap.select(quote(self.drafts), readonly=True), "open the drafts folder")
            status, data = self.imap.uid("FETCH", appended.group(1), "(X-GM-THRID)")
            info = b" ".join(part for part in data if isinstance(part, bytes)) if status == "OK" else b""
            draft_thread = re.search(rb"X-GM-THRID (\d+)", info)
            return draft_thread.group(1).decode() == thread_id.decode() if draft_thread else None
        finally:
            self.select_inbox()

    def add_label(self, uid, label):
        """Put a Gmail label on an INBOX email, creating the label if needed. Return True if it worked."""
        try:
            self.imap.create(quote(label))  # returns NO harmlessly if the label already exists
            self.select_inbox()
            status, _ = self.imap.uid("STORE", uid, "+X-GM-LABELS", f"({quote(label)})")
            return status == "OK"
        except (imaplib.IMAP4.error, OSError):
            return False

    def close(self):
        try:
            self.imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


# -------------------------------------------------------------------- Agent


async def ask_claude(client, system_prompt, tools, messages):
    try:
        return await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=tools,
            thinking={"type": "adaptive"},
            messages=messages,
        )
    except anthropic.AuthenticationError:
        raise AgentError(f"The API key in {KEY_PATH} was rejected.")
    except anthropic.NotFoundError as error:
        raise AgentError(f"The API couldn't find the model {MODEL}: {error.message}")
    except anthropic.RateLimitError:
        raise AgentError("The API rate limit was reached. Wait a minute and try again.")
    except anthropic.APIStatusError as error:
        raise AgentError(f"The API returned an error ({error.status_code}): {error.message}")
    except anthropic.APIConnectionError:
        raise AgentError("Couldn't connect to the Anthropic API. Check your internet connection.")


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
    texts = [block.text for block in getattr(result, "content", None) or [] if getattr(block, "type", "") == "text"]
    text = "\n".join(texts) or "(the tool returned no text)"
    return text, bool(getattr(result, "is_error", False))


async def run_agent(client, email, saver):
    """One separate agent run for one email. Returns (draft_saved, input_tokens, output_tokens)."""
    system_prompt = read_system_prompt()  # re-read for every email

    print(f"Email: {email.label}")
    print(f"Sender: {email.sender}")
    print(f"Subject: {email.subject}")

    server = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH), "--as-employee", email.sender],
        cwd=str(WEEK_DIR.parent),
    )
    user_message = (
        "Here is the employee email to answer. Prepare a reply and save it with save_reply.\n\n"
        "<email>\n"
        f"From: {email.sender}\n"
        f"Subject: {email.subject}\n\n"
        f"{email.body}\n"
        "</email>"
    )
    messages = [{"role": "user", "content": user_message}]

    tool_calls = 0
    input_tokens = 0
    output_tokens = 0
    draft = None
    stop_reason_text = None

    try:
        with ServerLog() as server_log:
            async with stdio_client(server, errlog=server_log) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    mcp_tools = (await session.list_tools()).tools
                    tools = [
                        {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
                        for t in mcp_tools
                    ] + [SAVE_REPLY_TOOL]
                    mcp_names = {t.name for t in mcp_tools}
                    print(f"Tools offered: {', '.join(t['name'] for t in tools)}")

                    while True:
                        response = await ask_claude(client, system_prompt, tools, messages)
                        input_tokens += response.usage.input_tokens
                        output_tokens += response.usage.output_tokens

                        requests = [block for block in response.content if block.type == "tool_use"]
                        if response.stop_reason != "tool_use" or not requests:
                            stop_reason_text = STOP_REASONS.get(
                                response.stop_reason, f"Claude stopped (stop reason: {response.stop_reason})."
                            )
                            final_text = "\n".join(b.text for b in response.content if b.type == "text").strip()
                            if final_text:
                                print(f"\nClaude's final message: {final_text}")
                            break

                        # Keep Claude's whole reply (including thinking blocks) in the history.
                        messages.append({"role": "assistant", "content": response.content})

                        results = []
                        limit_hit = False
                        for request in requests:
                            if tool_calls >= MAX_TOOL_CALLS:
                                limit_hit = True
                                break
                            tool_calls += 1
                            inputs = request.input or {}

                            if request.name == "save_reply":
                                if draft is not None:
                                    text, is_error = "A draft was already saved. save_reply can be called only once.", True
                                else:
                                    reply_text = inputs.get("reply_text")
                                    review = inputs.get("needs_human_review")
                                    if not isinstance(reply_text, str) or not reply_text.strip() or not isinstance(review, bool):
                                        text = "save_reply needs reply_text (non-empty text) and needs_human_review (true or false)."
                                        is_error = True
                                    else:
                                        text, where, shown = saver.save(reply_text, review)
                                        draft = (where, shown)
                                        is_error = False
                            elif request.name in mcp_names:
                                text, is_error = await call_mcp_tool(session, request.name, inputs)
                            else:
                                text, is_error = f"There is no tool named {request.name}.", True

                            print_step(tool_calls, request.name, inputs, text)
                            results.append(
                                {"type": "tool_result", "tool_use_id": request.id, "content": text, "is_error": is_error}
                            )

                        if limit_hit or tool_calls >= MAX_TOOL_CALLS:
                            stop_reason_text = f"Stopped after reaching the limit of {MAX_TOOL_CALLS} tool calls."
                            break
                        messages.append({"role": "user", "content": results})
    except Exception as error:
        error = unwrap(error)
        if isinstance(error, AgentError):
            raise error
        # Most often the MCP server exiting at startup, e.g. when the sender has no employee record.
        raise AgentError(
            f"The HR MCP server couldn't be used ({type(error).__name__}: {error}). "
            "See its messages above; a common cause is a sender with no employee record."
        )

    print(f"\n=== Stopped: {stop_reason_text}")
    print(f"Tool calls used: {tool_calls} of {MAX_TOOL_CALLS}")
    if draft is None:
        print("\nNo draft was saved.")
    else:
        where, shown = draft
        print(f"\n=== {where}\n")
        print(shown)
    print(f"Tokens for this email: {input_tokens:,} input, {output_tokens:,} output")
    return draft is not None, input_tokens, output_tokens


async def run_file(client, path):
    email = read_email_file(path)
    saved, _, _ = await run_agent(client, email, FileDraftSaver(email, path))
    return 0 if saved else 2


async def run_inbox(client):
    mailbox = Mailbox()
    print("Signed in to the mailbox from Agent-Email.txt")
    handled = drafted = failed = 0
    total_in = total_out = 0
    try:
        uids = mailbox.unread_uids()
        print(f"Unread emails in {INBOX}: {len(uids)}")
        for number, uid in enumerate(uids, start=1):
            print(f"\n{'=' * 70}\nInbox email {number} of {len(uids)}\n{'=' * 70}")
            claimed = mailbox.claim(uid)
            if claimed is None:
                print("Skipped: it was already read or is gone.")
                continue
            raw, thread_id = claimed
            handled += 1
            try:
                email = parse_email(raw, f"inbox email {number}")
                saved, used_in, used_out = await run_agent(client, email, GmailDraftSaver(mailbox, email, thread_id, uid))
                drafted += saved
                total_in += used_in
                total_out += used_out
            except AgentError as error:
                failed += 1
                print(f"Error: {error}", file=sys.stderr)
                print("This email stays marked as read. Mark it unread in Gmail to try it again.", file=sys.stderr)
    finally:
        mailbox.close()

    print(f"\n{'=' * 70}")
    print(f"Inbox done: {handled} handled, {drafted} drafts created, {failed} failed. Nothing was sent.")
    print(f"Total tokens: {total_in:,} input, {total_out:,} output")
    return 0 if failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="Draft replies to Hartwell Foods HR emails with Claude. Never sends email.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--email", type=Path, help="path of one email file (.eml); the draft goes to week-04/drafts/")
    source.add_argument("--inbox", action="store_true", help="handle each unread email in the Gmail sandbox inbox")
    parser.add_argument("--save", type=Path, metavar="FILE", help="also write everything printed to FILE (UTF-8)")
    args = parser.parse_args()

    # The Windows console defaults to cp1252, which garbles characters like em dashes.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    log_file = None
    if args.save:
        try:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            log_file = args.save.open("w", encoding="utf-8")
        except OSError as error:
            print(f"Error: couldn't open {args.save} for --save: {error.strerror}", file=sys.stderr)
            return 1
        sys.stdout = Tee(sys.stdout, log_file)
        sys.stderr = Tee(sys.stderr, log_file)

    try:
        client = anthropic.AsyncAnthropic(api_key=read_api_key())
        if args.inbox:
            return asyncio.run(run_inbox(client))
        return asyncio.run(run_file(client, args.email))
    except AgentError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        if log_file:
            sys.stdout.flush()
            sys.stdout, sys.stderr = sys.stdout.stream, sys.stderr.stream
            log_file.close()
            print(f"Output saved to {args.save}")


if __name__ == "__main__":
    sys.exit(main())
