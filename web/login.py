"""The web UI's login cookie and the throttle for failed logins (the routes themselves are in server.py).

The cookie holds the user name and a signed, timestamped token. Each user's token is signed with a key derived from
that user's own password hash in the login file (authfile.py), so no secret has to be configured or stored anywhere,
and changing a user's password or removing the user ends exactly that user's logins -- the cookies of everyone else
stay valid. Nothing is kept on the server: the cookie is all there is to a login.
"""
import base64
import hashlib
import time

from itsdangerous import BadData, URLSafeTimedSerializer

COOKIE_NAME = "media-control-login"
COOKIE_MAX_AGE = 30 * 24 * 3600  # seconds a login lasts, counted from signing in


def _serializer(passwordHash):
    key = hashlib.sha256(("media-control login cookie\0" + passwordHash).encode("utf-8")).digest()
    return URLSafeTimedSerializer(key, salt="media-control-login")


def makeCookie(username, passwordHash):
    """The cookie value that logs username in: the name (url-safe base64) and a token signed for that user."""
    encodedName = base64.urlsafe_b64encode(username.encode("utf-8")).decode("ascii").rstrip("=")
    return encodedName + "." + _serializer(passwordHash).dumps(username)


def userOfCookie(value, users):
    """The user a cookie value logs in, or None if it is damaged, forged, expired, or of a user that no longer exists
    or has a different password now. users is {username: password hash} as authfile.read gives it."""
    encodedName, _, token = (value or "").partition(".")
    try:
        username = base64.urlsafe_b64decode(encodedName + "=" * (-len(encodedName) % 4)).decode("utf-8")
    except ValueError: # includes a UnicodeDecodeError and a malformed base64 string
        return None
    passwordHash = users.get(username)
    if passwordHash is None:
        return None
    try:
        signed = _serializer(passwordHash).loads(token, max_age=COOKIE_MAX_AGE)
    except BadData:
        return None
    return username if signed == username else None


class FailureThrottle:
    """Failed logins per client address: after `limit` within `window` seconds, that address is refused until the
    oldest of them is `window` old. Kept in memory, so each server process counts for itself (gunicorn runs two)."""

    def __init__(self, limit=5, window=600):
        self.limit, self.window = limit, window
        self._failures = {}  # address -> times of its recent failures

    def _recent(self, address, now):
        recent = [t for t in self._failures.get(address, ()) if now - t < self.window]
        if recent:
            self._failures[address] = recent
        else:
            self._failures.pop(address, None)
        return recent

    def blocked(self, address, now=None):
        return len(self._recent(address, time.time() if now is None else now)) >= self.limit

    def failed(self, address, now=None):
        now = time.time() if now is None else now
        if len(self._failures) > 1000: # addresses that never came back would pile up otherwise
            for other in list(self._failures):
                self._recent(other, now)
        self._failures.setdefault(address, []).append(now)

    def succeeded(self, address):
        self._failures.pop(address, None)
