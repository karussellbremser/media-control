"""The web UI's login file (config.ini's [server] auth_file): one "username:password-hash" line per user, with
blank lines and "#" comments ignored. web/server.py reads it at start (read()); this module is also the command
line tool that adds, changes and removes users -- run from the project root:

    python -m web.authfile add NAME        asks for the password; an existing NAME gets the new password
    python -m web.authfile remove NAME
    python -m web.authfile list

`--file PATH` names another file than auth.txt. The server reads the file only at start, so after changing the one
on a server, restart the container (see README.md, "Hosting the web UI with Docker").

Deliberately independent of serverconfig/config.ini and of Flask, so the tool needs nothing but werkzeug.
"""
import argparse
import codecs
import getpass
import os
import sys

from werkzeug.security import generate_password_hash


class AuthFileError(Exception):
    """The file is unusable -- its message says what's wrong and is shown as it is."""


def _decode(raw, path):
    # Windows tools easily produce a file with a byte order mark or in UTF-16 (PowerShell's ">" does exactly that),
    # so those are accepted too rather than failing on a file that looks fine in an editor
    encoding = "utf-16" if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig"
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        raise AuthFileError(path + " isn't a readable text file (expected UTF-8) -- recreate it with python -m web.authfile")


def _entry(line):
    """(username, hash) of a "username:hash" line, or None for a blank line or a comment. The hash itself contains
    colons, so only the first one separates the name. Raises ValueError for anything else."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    username, separator, passwordHash = line.partition(":")
    if not separator or not username or not passwordHash:
        raise ValueError(line)
    return username, passwordHash


def _entryOrNone(line):
    """_entry, except that a malformed line counts as no entry (the edit commands leave such a line alone)."""
    try:
        return _entry(line)
    except ValueError:
        return None


def parse(text, path="auth file"):
    """{username: hash} from the text of a login file. Raises AuthFileError for a malformed line, a user listed
    twice, or no user at all -- the server must not start without a login it can check."""
    users = {}
    for number, line in enumerate(text.splitlines(), 1):
        try:
            entry = _entry(line)
        except ValueError:
            raise AuthFileError(path + ", line " + str(number) + " isn't of the form username:password-hash")
        if entry is None:
            continue
        if entry[0] in users:
            raise AuthFileError(path + " lists the user " + entry[0] + " twice (line " + str(number) + ")")
        users[entry[0]] = entry[1]
    if not users:
        raise AuthFileError(path + " has no user in it -- add one with python -m web.authfile add NAME")
    return users


def read(path):
    """{username: hash} from the file at path. OSError if it can't be read, AuthFileError if it's unusable."""
    with open(path, "rb") as f:
        raw = f.read()
    return parse(_decode(raw, path), path)


def _lines(path):
    """The file's lines as they are (comments and blank lines included), [] if the file doesn't exist yet."""
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        return _decode(f.read(), path).splitlines()


def _write(path, lines):
    # whole file at once and renamed into place, so an interrupted run can't leave a half-written login file behind
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(line + "\n" for line in lines))
    os.replace(temporary, path)


def _checkName(username):
    if not username or ":" in username or any(ord(c) < 32 or ord(c) == 127 for c in username) or username != username.strip():
        raise AuthFileError("a user name can't be empty, start or end with a space, or contain ':' or control characters")


def addUser(path, username, password):
    """Adds username with that password, or sets the new password of an existing one. Returns True if the user
    was new. The other lines of the file stay as they are."""
    _checkName(username)
    if not password:
        raise AuthFileError("the password can't be empty")
    entry = username + ":" + generate_password_hash(password)
    lines = _lines(path)
    for i, line in enumerate(lines):
        existing = _entryOrNone(line)
        if existing is not None and existing[0] == username:
            lines[i] = entry
            _write(path, lines)
            return False
    lines.append(entry)
    _write(path, lines)
    return True


def removeUser(path, username):
    """Removes username. Raises AuthFileError if there's no such user, or if it is the last one (a login file
    without a user would keep the server from starting)."""
    lines = _lines(path)
    kept, found, remaining = [], False, 0
    for line in lines:
        entry = _entryOrNone(line)
        if entry is not None and entry[0] == username:
            found = True
            continue
        if entry is not None:
            remaining += 1
        kept.append(line)
    if not found:
        raise AuthFileError("there is no user " + username + " in " + path)
    if remaining == 0:
        raise AuthFileError(username + " is the last user: without one the server would refuse to start")
    _write(path, kept)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m web.authfile", description="Add, change and remove the users of the web UI's login file.")
    parser.add_argument("--file", default="auth.txt", help="the login file (default: auth.txt in the current directory)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("add", help="add a user, or change the password of an existing one").add_argument("name")
    commands.add_parser("remove", help="remove a user").add_argument("name")
    commands.add_parser("list", help="list the users")
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            for name in read(args.file):
                print(name)
        elif args.command == "remove":
            removeUser(args.file, args.name)
            print("Removed " + args.name + " from " + args.file)
        else:
            _checkName(args.name)
            password = getpass.getpass("password for " + args.name + ": ")
            if password != getpass.getpass("again: "):
                raise AuthFileError("the two passwords differ -- nothing changed")
            created = addUser(args.file, args.name, password)
            print(("Added " if created else "Changed the password of ") + args.name + " in " + args.file)
    except (AuthFileError, OSError) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
