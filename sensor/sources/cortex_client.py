"""Minimal Emotiv Cortex client for the free-tier streams.

JSON-RPC 2.0 over wss://localhost:6868 (served by the EMOTIV Launcher),
using websocket-client, as in Emotiv's own cortex-example. Only licence-free
streams are requested (pow, fac, com, dev, eq). Raw "eeg" needs a paid licence and
is never requested.

Flow: requestAccess -> authorize -> queryHeadsets (+ controlDevice) -> [setupProfile load] ->
createSession -> subscribe.
"""

from __future__ import annotations

import itertools
import json
import queue
import ssl
import threading
import time
from collections.abc import Callable

import websocket  # websocket-client

WARN_HEADSET_CONNECTED = 104
WARN_SCAN_FINISHED = 142


class CortexError(RuntimeError):
    pass


class CortexClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        url: str = "wss://localhost:6868",
        on_data: Callable[[dict], None] | None = None,
        log: Callable[[str], None] = print,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.url = url
        self.on_data = on_data or (lambda d: None)
        self.log = log
        self.cols: dict[str, list] = {}
        self.headset_id: str | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, queue.Queue] = {}
        self._opened = threading.Event()
        self._token: str | None = None
        self._session: str | None = None
        self.ws: websocket.WebSocketApp | None = None

    # -- transport ---------------------------------------------------------

    def connect(self, timeout: float = 10.0) -> None:
        self.ws = websocket.WebSocketApp(
            self.url,
            on_open=lambda ws: self._opened.set(),
            on_message=self._on_message,
            on_error=lambda ws, e: self.log(f"[cortex] websocket error: {e}"),
            on_close=lambda ws, *a: self.log("[cortex] websocket closed"),
        )
        # Cortex serves a certificate signed by Emotiv's own root CA on
        # localhost. Verification is skipped for this local-only socket.
        sslopt = {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}
        threading.Thread(
            target=self.ws.run_forever, kwargs={"sslopt": sslopt}, daemon=True, name="cortex-ws"
        ).start()
        if not self._opened.wait(timeout):
            raise CortexError(
                f"Could not reach Cortex at {self.url}. Is the EMOTIV Launcher running "
                "and are you logged in?"
            )

    def _on_message(self, ws, message: str) -> None:
        data = json.loads(message)
        if "id" in data and data["id"] in self._pending:
            self._pending.pop(data["id"]).put(data)
        elif "warning" in data:
            w = data["warning"]
            self.log(f"[cortex] warning {w.get('code')}: {w.get('message')}")
        elif "sid" in data and "time" in data:
            self.on_data(data)

    def call(self, method: str, params: dict | None = None, timeout: float = 15.0):
        req_id = next(self._ids)
        q: queue.Queue = queue.Queue(maxsize=1)
        self._pending[req_id] = q
        self.ws.send(
            json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})
        )
        try:
            resp = q.get(timeout=timeout)
        except queue.Empty as e:
            self._pending.pop(req_id, None)
            raise CortexError(f"{method}: no response in {timeout}s") from e
        if "error" in resp:
            raise CortexError(f"{method}: {resp['error']}")
        return resp.get("result")

    # -- setup -------------------------------------------------------------

    def start(
        self,
        streams: list[str],
        headset_id: str | None = None,
        access_wait_s: float = 90.0,
        profile: str | None = None,
    ) -> dict[str, list]:
        creds = {"clientId": self.client_id, "clientSecret": self.client_secret}

        deadline = time.time() + access_wait_s
        while True:
            r = self.call("requestAccess", creds)
            if r.get("accessGranted"):
                break
            if time.time() > deadline:
                raise CortexError(f"Access not granted: {r.get('message')}")
            self.log(f"[cortex] Approve this app in the EMOTIV Launcher... ({r.get('message')})")
            time.sleep(3)

        self._token = self.call("authorize", creds)["cortexToken"]
        self.headset_id = self._pick_headset(headset_id)
        self.log(f"[cortex] headset {self.headset_id}")
        self.profiles = self.list_profiles()
        self.log(f"[cortex] training profiles on this account: {self.profiles or 'none'}")
        self.profile_loaded = None
        if profile:
            self.load_profile(profile)

        sess = self.call(
            "createSession",
            {"cortexToken": self._token, "headset": self.headset_id, "status": "open"},
        )
        self._session = sess["id"]

        r = self.call(
            "subscribe", {"cortexToken": self._token, "session": self._session, "streams": streams}
        )
        failed = [f["streamName"] for f in r.get("failure", [])]
        if failed:
            self.log(
                f"[cortex] subscribe failed for {failed} on an open session; "
                "activating the session and retrying"
            )
            self.call(
                "updateSession",
                {"cortexToken": self._token, "session": self._session, "status": "active"},
            )
            r2 = self.call(
                "subscribe",
                {"cortexToken": self._token, "session": self._session, "streams": failed},
            )
            r["success"] = r.get("success", []) + r2.get("success", [])
            still = r2.get("failure", [])
            if still:
                raise CortexError(f"subscribe failed: {still}")
        self.cols = {s["streamName"]: s["cols"] for s in r["success"]}
        self.log(f"[cortex] streaming {sorted(self.cols)}")
        return self.cols

    def list_profiles(self) -> list[str]:
        try:
            return [
                p.get("name")
                for p in (self.call("queryProfile", {"cortexToken": self._token}) or [])
            ]
        except CortexError as e:
            self.log(f"[cortex] queryProfile: {e}")
            return []

    def load_profile(self, name: str) -> None:
        """Load a mental-command training profile (needed for a meaningful com stream)."""
        params = {
            "cortexToken": self._token,
            "headset": self.headset_id,
            "profile": name,
            "status": "load",
        }
        try:
            self.call("setupProfile", params)
        except CortexError as e:
            # A profile may already be loaded on this headset: unload, then retry once.
            self.log(f"[cortex] load failed ({e}); unloading the current profile and retrying")
            self.call(
                "setupProfile",
                {
                    "cortexToken": self._token,
                    "headset": self.headset_id,
                    "profile": "",
                    "status": "unload",
                },
            )
            self.call("setupProfile", params)
        self.profile_loaded = name
        self.log(f"[cortex] profile loaded: {name}")

    def profile_info(self) -> dict:
        """What the loaded mental-command profile contains. Each call is optional:
        failures are logged and skipped."""
        info: dict = {}
        prof = self.profile_loaded
        calls = {
            "trained": (
                "getTrainedSignatureActions",
                {"cortexToken": self._token, "detection": "mentalCommand", "profile": prof},
            ),
            "active_actions": (
                "mentalCommandActiveAction",
                {"cortexToken": self._token, "status": "get", "profile": prof},
            ),
            "sensitivity": (
                "mentalCommandActionSensitivity",
                {"cortexToken": self._token, "status": "get", "profile": prof},
            ),
            "training_threshold": (
                "mentalCommandTrainingThreshold",
                {"cortexToken": self._token, "profile": prof},
            ),
        }
        for key, (method, params) in calls.items():
            try:
                info[key] = self.call(method, params)
                self.log(f"[cortex] {key}: {info[key]}")
            except CortexError as e:
                self.log(f"[cortex] {key}: unavailable ({e})")
        return info

    def _query(self) -> list[dict]:
        return self.call("queryHeadsets", {}) or []

    def _pick_headset(self, wanted: str | None) -> str:
        hs = self._query()
        if not hs:
            self.log("[cortex] no headset listed; scanning (~20 s)...")
            self.call("controlDevice", {"command": "refresh"})
            deadline = time.time() + 25
            while not hs and time.time() < deadline:
                time.sleep(2)
                hs = self._query()
        if not hs:
            raise CortexError(
                "No headset found. Turn the EPOC X on and pair it in the EMOTIV Launcher."
            )
        pick = next((h for h in hs if h["id"] == wanted), None) if wanted else hs[0]
        if pick is None:
            raise CortexError(f"Headset {wanted} not found; seen {[h['id'] for h in hs]}")
        if pick.get("status") != "connected":
            self.log(f"[cortex] connecting to {pick['id']}...")
            self.call("controlDevice", {"command": "connect", "headset": pick["id"]})
            deadline = time.time() + 30
            while time.time() < deadline:
                time.sleep(1)
                cur = next((h for h in self._query() if h["id"] == pick["id"]), None)
                if cur and cur.get("status") == "connected":
                    break
            else:
                raise CortexError(f"Headset {pick['id']} did not connect in 30 s")
        return pick["id"]

    def close(self) -> None:
        try:
            if self._session:
                self.call(
                    "updateSession",
                    {"cortexToken": self._token, "session": self._session, "status": "close"},
                    timeout=5,
                )
        except Exception as e:  # closing is best-effort
            self.log(f"[cortex] close: {e}")
        if self.ws:
            self.ws.close()
