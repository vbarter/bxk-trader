"""Hard timeout for baostock's blocking TCP client.

baostock talks to public-api.baostock.com:10030 and never sets a socket
timeout. A peer that finishes the handshake and then stops sending leaves
the caller sleeping in recv (2026-10-13 09:35 settle_am: export_watch_calendar
hung twice, 0 CPU, one ESTAB socket). `install()` arms a timeout on new
sockets and on the live baostock socket before every send/recv. The first
recv failure trips a circuit breaker so later calls in this process return
immediately and the settle path can use local bars.

Successful replies are unchanged: the timeout only fires when a recv does
not complete.
"""

from __future__ import annotations

import os
import socket
import sys

# One stalled recv must not stall the cron. Normal K-line replies are well
# under a second; override with BAOSTOCK_TIMEOUT_S.
DEFAULT_TIMEOUT_S = 15.0

# baostock.common.contants — client-side recv failures.
_RECV_FAIL_CODES = {"10002004", "10002007", "10002008"}

_state: dict[str, object] = {
    "timeout": DEFAULT_TIMEOUT_S,
    "circuit": True,
    "dead": False,
    "reason": "",
    "wrapped": False,
    "noted": False,
}


def dead() -> bool:
    return bool(_state["dead"])


def timeout_s() -> float:
    return float(_state["timeout"])


def reset() -> None:
    """Clear the circuit. Used by tests; does not unwrap send_msg."""
    _state["dead"] = False
    _state["reason"] = ""
    _state["noted"] = False
    close_socket()


def close_socket() -> None:
    try:
        import baostock.common.context as ctx
    except Exception:
        return
    sock = getattr(ctx, "default_socket", None)
    if sock is None:
        return
    try:
        sock.close()
    except OSError:
        pass
    try:
        setattr(ctx, "default_socket", None)
    except Exception:
        pass


def _warn(msg: str) -> None:
    print(f"[warn] baostock timeout: {msg}", file=sys.stderr, flush=True)


def _arm(timeout: float) -> None:
    try:
        import baostock.common.context as ctx
    except Exception:
        return
    sock = getattr(ctx, "default_socket", None)
    if sock is None:
        return
    try:
        sock.settimeout(timeout)
    except OSError:
        pass


def install(timeout: float | None = None, *, circuit: bool | None = None) -> float:
    """Arm the baostock socket timeout. Returns the timeout in seconds.

    A later `install()` without arguments keeps an explicit timeout already
    set in this process (tests pass a short one). `BAOSTOCK_TIMEOUT_S`
    always wins when set.
    """
    env = os.environ.get("BAOSTOCK_TIMEOUT_S", "").strip()
    if env:
        timeout = float(env)
    elif timeout is None and _state["wrapped"]:
        timeout = float(_state["timeout"])
    elif timeout is None:
        timeout = DEFAULT_TIMEOUT_S
    timeout = float(timeout)
    if timeout <= 0:
        raise ValueError("baostock timeout must be > 0")
    _state["timeout"] = timeout
    if circuit is not None:
        _state["circuit"] = bool(circuit)
    # Cover connect(), which runs before send_msg. Never raise a tighter
    # default that a caller already set (main.py uses 10s).
    current = socket.getdefaulttimeout()
    if current is None or current > timeout:
        socket.setdefaulttimeout(timeout)
    _wrap_send()
    return timeout


def _wrap_send() -> None:
    if _state["wrapped"]:
        return
    import baostock.util.socketutil as sockutil

    orig = sockutil.send_msg

    def send_msg(msg: str):
        if _state["dead"] and _state["circuit"]:
            close_socket()
            return None
        _arm(float(_state["timeout"]))
        try:
            result = orig(msg)
        except Exception as exc:  # noqa: BLE001 — baostock usually swallows this
            _trip(f"{type(exc).__name__}: {exc}")
            return None
        if result is None:
            _trip("recv failed or timed out")
        return result

    sockutil.send_msg = send_msg
    _state["wrapped"] = True


def _trip(reason: str) -> None:
    if not _state["circuit"]:
        if not _state["noted"]:
            _state["noted"] = True
            _warn(f"{reason}; continuing without the circuit breaker")
        return
    if not _state["dead"]:
        _state["dead"] = True
        _state["reason"] = reason
        _warn(f"{reason}; skipping further baostock calls this process")
    close_socket()


def safe_logout(bs_module: object) -> None:
    """Logout when the session is healthy. A wedged socket is closed locally.

    baostock's logout() does another blocking recv; calling it after a timeout
    would stall the pipeline a second time.
    """
    if _state["dead"]:
        close_socket()
        return
    try:
        bs_module.logout()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        _warn(f"logout: {exc}")
        close_socket()


def transport_failed(result: object) -> bool:
    """True when this result is a recv failure (or the circuit is already open)."""
    if _state["dead"]:
        return True
    if result is None:
        return True
    code = str(getattr(result, "error_code", "") or "")
    if code in _RECV_FAIL_CODES:
        return True
    msg = str(getattr(result, "error_msg", "") or "")
    return "网络接收" in msg
