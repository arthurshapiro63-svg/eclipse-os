"""Keep secrets out of Arclight's logs.

Every log that records what was asked of the system (arclightd's and the session's actions.jsonl, the
installer log, Eclipse AI's command log) passes through here before anything is written:

  * parameters whose NAME says they are secret (password, token, api_key, ...) become "[redacted]";
  * free text that is often a secret by nature (typed text, clipboard, file contents written, a
    command's stdin) is replaced by its length, so the log still shows that something happened;
  * secret-looking VALUES inside commands and error messages (`password X`, `--token=X`,
    `echo user:pw | chpasswd`, `Authorization: Bearer X`, `https://user:pw@host`, well-known API key
    formats) are masked, and any secret value seen in the parameters is masked wherever else it appears.

Log files are created 0600 and tightened to 0600 if they already exist.

    python3 -m arclight.redact --scrub FILE...   rewrite existing JSON-lines / text logs in place
"""
import json
import os
import re
import sys

MASK = "[redacted]"

SECRET_KEY = re.compile(r"(?i)(^|[_\-.])(pass(word|wd|phrase)?|pwd|secret|token|api[_\-]?key|private[_\-]?key|"
                        r"credentials?|psk|otp|pin|authorization|cookie|password_hash)($|[_\-.])")

# method -> parameter names that are free text worth hiding (their length is kept)
SENSITIVE_TEXT = {
    "input.type": ("text",), "input.paste": ("text",), "ui.set_text": ("text",), "ui.type": ("text",),
    "clip.set": ("text",), "file.write": ("content", "base64_content"), "file.edit": ("old", "new"),
    "exec": ("input",), "events.add": (),
}
ALWAYS_TEXT = ("input", "stdin")   # a command's standard input, in any method

_VALUE_PATTERNS = [
    # echo 'user:pw' | chpasswd   /   printf "user:pw\n" | sudo chpasswd
    (re.compile(r"""((?:echo|printf)\s+(?:-\w+\s+)*['"]?[^\s:'"|]+:)([^'"\s|]+)(['"]?\s*\|\s*(?:sudo\s+)?chpasswd)"""),
     lambda m: m.group(1) + MASK + m.group(3)),
    # password X, --password=X, PASSWORD: X, psk "X", token=X ...
    (re.compile(r"""(?i)(\b(?:pass(?:word|wd|phrase)?|pwd|psk|secret|token|api[_\-]?key|private[_\-]?key)\b"""
                r"""["']?(?:\s*[=:]\s*|\s+))("[^"]*"|'[^']*'|[^\s"',;}]+)"""),
     lambda m: m.group(1) + MASK),
    # Authorization: Bearer X / Basic X
    (re.compile(r"(?i)\b(authorization:\s*(?:bearer|basic|token)\s+|bearer\s+)[A-Za-z0-9._~+/=\-]{6,}"),
     lambda m: m.group(1) + MASK),
    # curl -u user:pw, --user user:pw
    (re.compile(r"((?:\s-u|--user)\s+[^\s:]+:)(\S+)"), lambda m: m.group(1) + MASK),
    # scheme://user:pw@host
    (re.compile(r"(\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:)([^\s@/]+)(@)"), lambda m: m.group(1) + MASK + m.group(3)),
    # usermod -p HASH, useradd -p HASH, openssl passwd ... X
    (re.compile(r"(\buser(?:mod|add)\b[^\n|;]*?\s-p\s+)(\S+)"), lambda m: m.group(1) + MASK),
    # well-known key formats
    (re.compile(r"\b(sk-ant-[A-Za-z0-9_\-]{10,}|sk-[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
                r"glpat-[A-Za-z0-9_\-]{16,}|xox[abpsr]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,}|"
                r"hf_[A-Za-z0-9]{20,})"), lambda m: MASK),
    # $6$salt$hash (crypt hashes)
    (re.compile(r"\$(?:1|2[aby]|5|6|y|gy|7)\$[^\s:'\"]{8,}"), lambda m: MASK),
]


def scrub_text(s, secrets=()):
    """Mask secret-looking values in a string, plus any of the given literal secret values."""
    if not isinstance(s, str) or not s:
        return s
    for v in sorted({x for x in secrets if isinstance(x, str) and len(x) >= 3}, key=len, reverse=True):
        s = s.replace(v, MASK)
    for rx, fn in _VALUE_PATTERNS:
        s = rx.sub(fn, s)
    return s


def _summary(v):
    if isinstance(v, (bytes, bytearray)):
        return f"[{len(v)} bytes]"
    if isinstance(v, str):
        return f"[{len(v)} chars]"
    if isinstance(v, list):
        return f"[{len(v)} items]"
    return "[set]" if v is not None else None


def _collect(v, out):
    if isinstance(v, str):
        out.append(v)
    elif isinstance(v, dict):
        for x in v.values():
            _collect(x, out)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _collect(x, out)


def find_secrets(params):
    """The literal values of every parameter whose name says it is secret (searched recursively)."""
    found = []

    def walk(v):
        if isinstance(v, dict):
            named = any(isinstance(v.get(n), str) and SECRET_KEY.search(v[n]) for n in ("key", "name", "setting"))
            for k, x in v.items():
                if (isinstance(k, str) and SECRET_KEY.search(k)) or (named and k in ("value", "values")):
                    _collect(x, found)
                else:
                    walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
    walk(params)
    return found


def redact_params(method, params, secrets=None):
    """A copy of an RPC call's parameters that is safe to log."""
    secrets = find_secrets(params) if secrets is None else secrets
    text_keys = set(SENSITIVE_TEXT.get(method, ())) | set(ALWAYS_TEXT)

    def walk(v, top=False):
        if isinstance(v, dict):
            out = {}
            named = any(isinstance(v.get(n), str) and SECRET_KEY.search(v[n]) for n in ("key", "name", "setting"))
            for k, x in v.items():
                if named and k in ("value", "values") and x not in (None, "", False):
                    out[k] = MASK
                elif isinstance(k, str) and SECRET_KEY.search(k):
                    out[k] = MASK if x not in (None, "", False) else x
                elif isinstance(k, str) and k in text_keys and x not in (None, ""):
                    out[k] = _summary(x)
                elif isinstance(k, str) and k == "text" and method in ("input.sequence",):
                    out[k] = _summary(x)
                else:
                    out[k] = walk(x)
            return out
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str):
            return scrub_text(v, secrets)
        return v
    return walk(params if isinstance(params, dict) else {"args": params}, True)


def redact_record(rec, params=None):
    """Mask secrets in a finished log record (error messages, results), given the raw params."""
    secrets = find_secrets(params or {})

    def walk(v):
        if isinstance(v, dict):
            return {k: (MASK if isinstance(k, str) and SECRET_KEY.search(k) and v[k] not in (None, "", False)
                        else walk(x)) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str):
            return scrub_text(v, secrets)
        return v
    return walk(rec)


def append_private(path, text):
    """Append to a log file that only its owner can read (0600), creating the folder if needed."""
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, text.encode())
    finally:
        os.close(fd)


def open_private(path):
    """An append-mode text file object for a private (0600) log."""
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, "a")


def scrub_file(path):
    """Rewrite an existing log with secrets masked (JSON lines are re-redacted record by record)."""
    try:
        with open(path, errors="replace") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return 0
    out, changed = [], 0
    for line in lines:
        new = line
        try:
            rec = json.loads(line)
            if isinstance(rec, dict):
                raw = rec.get("params")
                if isinstance(raw, dict):
                    rec = dict(rec, params=redact_params(rec.get("method", ""), raw))
                clean = redact_record(rec, raw if isinstance(raw, dict) else None)
                if clean != json.loads(line):
                    new = json.dumps(clean, ensure_ascii=False, default=str)
        except ValueError:
            new = scrub_text(line)
        changed += new != line
        out.append(new)
    tmp = f"{path}.redact-tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(out) + ("\n" if out else ""))
    st = os.stat(path)
    try:
        os.chown(tmp, st.st_uid, st.st_gid)
    except OSError:
        pass
    os.replace(tmp, path)
    return changed


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] != "--scrub":
        print(__doc__.strip().splitlines()[-1])
        return 2
    for p in a[1:]:
        n = scrub_file(p)
        print(f"{p}: {n} lines masked, mode 0600")
    return 0


if __name__ == "__main__":
    sys.exit(main())
