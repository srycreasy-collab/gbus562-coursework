"""Load the Hartwell HR sample emails into a Gmail sandbox inbox over IMAP.

Each .eml file in week-04/hartwell-hr/sample-emails is placed straight into the
INBOX with IMAP APPEND, as an unread message dated now. Nothing is sent: no SMTP
is used, and the messages never leave the mailbox.

The login comes from Agent-Email.txt in the folder above the repository. Any of
these layouts works:

    EMAIL_ADDRESS=sandbox@gmail.com      sandbox@gmail.com      email: sandbox@gmail.com
    APP_PASSWORD=abcdefghijklmnop        abcd efgh ijkl mnop    password: abcd efgh ijkl mnop

(labels can use ":" or "=", in any case; an optional "server:" or "host:" line
overrides imap.gmail.com). Gmail needs IMAP turned on and an app password.

The password is never printed or saved.

Run from the top of the repository:

    .venv\\Scripts\\python.exe week-04\\load_inbox.py
"""

import imaplib
import re
import sys
import time
from email import policy
from email.parser import BytesParser
from email.utils import formatdate, make_msgid
from pathlib import Path

WEEK_DIR = Path(__file__).resolve().parent
LOGIN_PATH = WEEK_DIR.parents[1] / "Agent-Email.txt"
EMAILS_DIR = WEEK_DIR / "hartwell-hr" / "sample-emails"
DEFAULT_HOST = "imap.gmail.com"
MAILBOX = "INBOX"

EMAIL_RE = re.compile(r"[^@\s:=]+@[^@\s:=]+\.[^@\s:=]+")
LABEL_RE = re.compile(r"^\s*([A-Za-z _-]+?)\s*[:=]\s*(.*?)\s*$")
APP_PASSWORD_RE = re.compile(r"^[a-z]{4}( [a-z]{4}){3}$")


class LoadError(Exception):
    """A problem that stops the script. Messages never include the password."""


def read_login():
    """Return (host, address, password) from Agent-Email.txt without echoing it."""
    try:
        text = LOGIN_PATH.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise LoadError(f"Couldn't read the login file {LOGIN_PATH}: {error.strerror}")
    return parse_login(text)


def parse_login(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    host, address, password = DEFAULT_HOST, None, None
    unlabeled = []

    for line in lines:
        match = LABEL_RE.match(line)
        label = match.group(1).strip().lower().replace("-", " ").replace("_", " ") if match else ""
        value = match.group(2) if match else ""
        if label in ("password", "app password", "pass", "pw"):
            password = value
        elif label in ("email", "e mail", "email address", "address", "user", "username", "login", "account"):
            address = value
        elif label in ("server", "host", "imap", "imap server", "imap host"):
            host = value or DEFAULT_HOST
        else:
            unlabeled.append(line)

    # Unlabeled layout: one line is the address, the other is the password.
    if address is None:
        address = next((line for line in unlabeled if EMAIL_RE.fullmatch(line)), None)
        if address:
            unlabeled.remove(address)
    if password is None and len(unlabeled) == 1:
        password = unlabeled[0]

    if not address or not EMAIL_RE.fullmatch(address):
        raise LoadError(
            f"Couldn't find an email address in {LOGIN_PATH}. Put the address on its own line "
            "or after 'email:'."
        )
    if not password:
        raise LoadError(
            f"Couldn't find a password in {LOGIN_PATH}. Put it on its own line after the address, "
            "or after 'password:'."
        )
    # Google shows app passwords in four groups of four letters; the spaces aren't part of it.
    if APP_PASSWORD_RE.fullmatch(password):
        password = password.replace(" ", "")
    return host, address, password


def prepare(path, now):
    """Return the message bytes with today's Date and a fresh Message-ID."""
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    del message["Date"]
    message["Date"] = formatdate(now, localtime=True)
    # A new Message-ID on each load, so Gmail doesn't treat a reload as a duplicate and hide it.
    del message["Message-ID"]
    message["Message-ID"] = make_msgid(domain="hartwellfoods.example")
    return message.as_bytes(policy=policy.SMTP)


def main():
    files = sorted(EMAILS_DIR.glob("*.eml"))
    if not files:
        print(f"No .eml files found in {EMAILS_DIR}.", file=sys.stderr)
        return 1

    try:
        host, address, password = read_login()
        print("Signing in to the mailbox from Agent-Email.txt")
        try:
            imap = imaplib.IMAP4_SSL(host)
        except OSError as error:
            raise LoadError(f"Couldn't connect to the IMAP server: {type(error).__name__}")

        try:
            try:
                imap.login(address, password)
            except imaplib.IMAP4.error:
                raise LoadError(
                    "Sign-in failed. Check the address and password in Agent-Email.txt. Gmail needs "
                    "IMAP turned on and an app password, not the normal account password."
                )
            finally:
                password = None  # don't keep it around longer than needed

            loaded = 0
            for path in files:
                now = time.time()
                data = prepare(path, now)
                # Empty flags (no \Seen) leave the message unread; the internal date is now.
                status, response = imap.append(MAILBOX, "", imaplib.Time2Internaldate(now), data)
                if status != "OK":
                    detail = response[0].decode(errors="replace") if response and response[0] else status
                    print(f"  FAILED  {path.name}: {detail}", file=sys.stderr)
                    continue
                loaded += 1
                print(f"  placed  {path.name}")
        finally:
            try:
                imap.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
    except LoadError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Done: {loaded} of {len(files)} emails placed in {MAILBOX} as unread. Nothing was sent.")
    return 0 if loaded == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
