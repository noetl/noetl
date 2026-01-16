#!/usr/bin/env python3
"""IBKR Gateway login automation for NoETL script tool.

Expected input: JSON string in sys.argv[1].
Credentials are read from environment variables:
- IBKR_USERNAME
- IBKR_PASSWORD
- IBKR_TOTP_SECRET (base32)
- IBKR_2FA_CODE (optional explicit code)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import ssl
import struct
import sys
import time
from typing import Optional
from urllib.request import Request, urlopen


def _parse_args() -> dict:
    if len(sys.argv) < 2:
        return {}
    try:
        return json.loads(sys.argv[1])
    except Exception:
        return {}


def _totp_now(secret: str, interval: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret.strip().replace(" ", ""), casefold=True)
    counter = int(time.time() // interval)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    code %= 10 ** digits
    return str(code).zfill(digits)


def _request_json(
    method: str,
    url: str,
    timeout: int,
    data: Optional[bytes] = None,
    headers: Optional[dict] = None,
) -> dict:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = Request(url, data=data, method=method)
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)
    with urlopen(req, timeout=timeout, context=ctx) as resp:
        body = resp.read().decode("utf-8")
    try:
        return json.loads(body) if body else {}
    except Exception:
        return {"_raw": body}


def _tickle(gateway_url: str, timeout_seconds: int) -> dict:
    url = gateway_url.rstrip("/") + "/v1/api/tickle"
    return _request_json("POST", url, timeout_seconds)


def _auth_status(gateway_url: str, timeout_seconds: int) -> dict:
    url = gateway_url.rstrip("/") + "/v1/api/iserver/auth/status"
    return _request_json("GET", url, timeout_seconds)


def _ssodh_init(gateway_url: str, timeout_seconds: int, publish: bool = True, compete: bool = True) -> dict:
    url = gateway_url.rstrip("/") + "/v1/api/iserver/auth/ssodh/init"
    payload = json.dumps({"publish": publish, "compete": compete}).encode("utf-8")
    return _request_json(
        "POST",
        url,
        timeout_seconds,
        data=payload,
        headers={"Content-Type": "application/json"},
    )


def _get_auth_flags(tickle_data: dict) -> tuple[bool, bool, bool]:
    iserver = (tickle_data or {}).get("iserver") or {}
    auth_status = (iserver.get("authStatus") or {}) if isinstance(iserver, dict) else {}
    authenticated = bool(auth_status.get("authenticated", False))
    connected = bool(auth_status.get("connected", False))
    competing = bool(auth_status.get("competing", False))
    return authenticated, connected, competing


def _run_browser_flow(
    *,
    gateway_url: str,
    username: Optional[str],
    password: Optional[str],
    paper: bool,
    manual: bool,
    headless: bool,
    timeout_seconds: int,
    totp_secret: Optional[str],
    two_fa_code: Optional[str],
) -> None:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright is not available in the job image. Use the Playwright Python image."
        ) from exc

    login_url = gateway_url.rstrip("/") + "/sso/Login?forwardTo=22&RL=1&ip2loc=on"
    print(f"Opening login URL: {login_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)

        if manual:
            print("Manual login requested; waiting for gateway authentication...")
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                try:
                    tickle = _tickle(gateway_url, timeout_seconds=15)
                    authenticated, connected, competing = _get_auth_flags(tickle)
                    if authenticated and connected and not competing:
                        return
                except Exception:
                    pass
                page.wait_for_timeout(500)
            raise RuntimeError("Timed out waiting for manual login to complete.")

        if not username or not password:
            raise RuntimeError("Missing IBKR username or password.")

        print("Submitting login form...")

        user_locators = [
            page.locator("input[name='user_name']"),
            page.locator("input[name='username']"),
        ]
        password_locator = page.locator("input[name='password']")

        user_box = None
        for loc in user_locators:
            try:
                loc.wait_for(state="visible", timeout=5_000)
                user_box = loc
                break
            except PlaywrightTimeoutError:
                continue

        if user_box is None:
            raise RuntimeError("Could not find username input field on the login page.")

        user_box.fill(username)
        password_locator.wait_for(state="visible", timeout=10_000)
        password_locator.fill(password)

        if paper:
            toggle = page.locator("label[for='toggle1']")
            try:
                if toggle.is_visible():
                    toggle.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass

        submit = page.locator(".btn.btn-lg.btn-primary")
        try:
            if submit.is_visible():
                submit.click()
            else:
                password_locator.press("Enter")
        except Exception:
            password_locator.press("Enter")

        success_text = page.get_by_text("Client login succeeds")
        two_fa_container = page.locator("#twofactbase")
        two_fa_input = page.locator("#xyz-field-bronze-response")
        err_v1 = page.locator(".alert.alert-danger.margin-top-10")
        err_v2 = page.locator(".xyz-errormessage")

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                tickle = _tickle(gateway_url, timeout_seconds=15)
                authenticated, connected, competing = _get_auth_flags(tickle)
                if authenticated and connected and not competing:
                    print("Gateway authenticated via tickle.")
                    return
            except Exception:
                pass

            if success_text.count() > 0 and success_text.first.is_visible():
                print("Login success banner detected.")
                return

            if two_fa_container.is_visible() or two_fa_input.is_visible():
                print("2FA prompt detected.")
                if not two_fa_code and totp_secret:
                    two_fa_code = _totp_now(totp_secret)
                    print("Generated TOTP code.")
                if not two_fa_code:
                    raise RuntimeError("2FA prompt detected but no code provided.")
                two_fa_input.wait_for(state="visible", timeout=10_000)
                two_fa_input.fill(two_fa_code)
                two_fa_input.press("Enter")

                try:
                    success_text.wait_for(timeout=20_000)
                    print("Login success banner detected after 2FA.")
                    return
                except PlaywrightTimeoutError:
                    pass

            if err_v1.is_visible() or err_v2.is_visible():
                err_text = ""
                try:
                    err_text = (err_v1.text_content() or "").strip() or (err_v2.text_content() or "").strip()
                except Exception:
                    pass
                raise RuntimeError(f"Login error displayed by page: {err_text or 'unknown error'}")

            page.wait_for_timeout(500)

        raise RuntimeError("Timed out waiting for login success/2FA/error.")


def main() -> int:
    args = _parse_args()

    gateway_url = (args.get("gateway_url") or "https://localhost:15000").strip()
    timeout_seconds = int(args.get("timeout_seconds") or 240)
    paper = bool(args.get("paper", True))
    manual = bool(args.get("manual", False))
    headless = bool(args.get("headless", True))

    username = os.environ.get("IBKR_USERNAME")
    password = os.environ.get("IBKR_PASSWORD")
    totp_secret = os.environ.get("IBKR_TOTP_SECRET")
    two_fa_code = os.environ.get("IBKR_2FA_CODE")

    print("IBKR login script starting.")
    print(f"Gateway URL: {gateway_url}")
    print(f"Headless: {headless}, Manual: {manual}, Paper: {paper}")
    print(f"Username set: {bool(username)}, Password set: {bool(password)}, TOTP set: {bool(totp_secret)}")

    before = {}
    try:
        before = _tickle(gateway_url, timeout_seconds=15)
    except Exception as exc:
        before = {"error": str(exc)}

    try:
        authenticated, connected, competing = _get_auth_flags(before)
    except Exception:
        authenticated = connected = competing = False

    if authenticated and connected and not competing:
        print("Gateway already authenticated; skipping login.")
        print(json.dumps({"status": "ok", "message": "already_authenticated"}))
        return 0

    _run_browser_flow(
        gateway_url=gateway_url,
        username=username,
        password=password,
        paper=paper,
        manual=manual,
        headless=headless,
        timeout_seconds=timeout_seconds,
        totp_secret=totp_secret,
        two_fa_code=two_fa_code,
    )

    try:
        init_resp = _ssodh_init(gateway_url, timeout_seconds=15, publish=True, compete=True)
        print(json.dumps({"ssodh_init": init_resp}))
    except Exception as exc:
        print(json.dumps({"ssodh_init_error": str(exc)}))

    deadline = time.time() + timeout_seconds
    last = None
    while time.time() < deadline:
        try:
            tickle = _tickle(gateway_url, timeout_seconds=15)
            last = tickle
            authenticated, connected, competing = _get_auth_flags(tickle)
            if authenticated and connected and not competing:
                print(json.dumps({"status": "ok", "tickle": tickle}))
                return 0
        except Exception as exc:
            last = {"error": str(exc)}

        time.sleep(2)

    print(json.dumps({"status": "error", "tickle": last}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
