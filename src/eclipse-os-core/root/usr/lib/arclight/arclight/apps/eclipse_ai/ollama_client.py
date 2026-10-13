"""Tiny streaming client for the local Ollama HTTP API (no third-party deps). From Arch AI by Arthur;
Eclipse AI adds `pull` (the "Get the AI model" button)."""
import http.client
import json
import socket
import threading
import urllib.parse


class OllamaError(Exception):
    pass


class Ollama:
    def __init__(self, host: str = "http://127.0.0.1:11434"):
        u = urllib.parse.urlparse(host)
        self.host, self.port = u.hostname or "127.0.0.1", u.port or 11434
        self._conn: http.client.HTTPConnection | None = None
        self._lock = threading.Lock()

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float = 600):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        with self._lock:
            self._conn = conn
        data = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=data, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        if resp.status >= 400:
            raise OllamaError(f"HTTP {resp.status}: {resp.read().decode(errors='replace')[:500]}")
        return conn, resp

    def is_up(self) -> bool:
        try:
            conn, resp = self._request("GET", "/api/version", timeout=2)
            resp.read(); conn.close()
            return True
        except Exception:
            return False

    def version(self) -> str:
        conn, resp = self._request("GET", "/api/version", timeout=3)
        v = json.loads(resp.read()).get("version", "?"); conn.close()
        return v

    def models(self) -> list[str]:
        try:
            conn, resp = self._request("GET", "/api/tags", timeout=5)
            names = [m["name"] for m in json.loads(resp.read()).get("models", [])]
            conn.close()
            return sorted(names)
        except Exception:
            return []

    def cancel(self) -> None:
        """Abort the in-flight request so the streaming loop raises and stops at once.
        shutdown() is what wakes a thread blocked in recv (close() alone does not on Linux)."""
        with self._lock:
            conn = self._conn
        if not conn:
            return
        sock = getattr(conn, "sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            conn.close()
        except Exception:
            pass

    def chat_stream(self, model: str, messages: list[dict], tools: list[dict] | None, think, options: dict, keep_alive: str):
        """Yield parsed NDJSON chunks from /api/chat."""
        payload = {"model": model, "messages": messages, "stream": True, "options": options, "keep_alive": keep_alive}
        if tools:
            payload["tools"] = tools
        if think is not None:
            payload["think"] = think
        conn, resp = self._request("POST", "/api/chat", payload)
        try:
            for line in resp:
                line = line.strip()
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    raise OllamaError(chunk["error"])
                yield chunk
                if chunk.get("done"):
                    break
        finally:
            conn.close()
            with self._lock:
                if self._conn is conn:
                    self._conn = None

    def pull(self, model: str):
        """Download a model. Yields {"status", "completed", "total"} chunks; cancel() stops it
        (Ollama keeps the finished parts, so a second pull resumes)."""
        conn, resp = self._request("POST", "/api/pull", {"model": model, "stream": True}, timeout=120)
        try:
            for line in resp:
                line = line.strip()
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    raise OllamaError(chunk["error"])
                yield chunk
                if chunk.get("status") == "success":
                    break
        finally:
            conn.close()
            with self._lock:
                if self._conn is conn:
                    self._conn = None
