#!/usr/bin/env python3
"""Authenticate IBKR Client Portal Gateway via the web UI.

This is intentionally NOT IBeam and does not depend on it.
It implements the same high-level idea: open the Gateway login page, submit credentials,
(optionally) handle 2FA prompt, then confirm authentication using `/v1/api/tickle`.

Typical usage (manual login):
    python scripts/ibkr/authenticate_gateway.py --gateway-url https://localhost:15000 --manual

Typical usage (autofill):
  IBKR_USERNAME=... IBKR_PASSWORD=... python scripts/ibkr/authenticate_gateway.py --paper

Dependencies:
  pip install 'noetl[ibkr]'
  playwright install chromium
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    authenticated: bool
    connected: bool
    competing: bool
    session: Optional[str]
    sso_expires: Optional[int]
    raw: dict


def _tickle(gateway_url: str, timeout_seconds: int) -> AuthResult:
    url = gateway_url.rstrip("/") + "/v1/api/tickle"
    resp = requests.post(url, timeout=timeout_seconds, verify=False)

    try:
        data = resp.json() if resp.content else {}
    except Exception:
        data = {"_non_json": resp.text}

    iserver = (data or {}).get("iserver") or {}
    auth_status = (iserver.get("authStatus") or {}) if isinstance(iserver, dict) else {}

    authenticated = bool(auth_status.get("authenticated", False))
    connected = bool(auth_status.get("connected", False))
    competing = bool(auth_status.get("competing", False))

    session = data.get("session") if isinstance(data, dict) else None
    sso_expires = data.get("ssoExpires") if isinstance(data, dict) else None

    return AuthResult(
        ok=resp.status_code == 200,
        authenticated=authenticated,
        connected=connected,
        competing=competing,
        session=session,
        sso_expires=sso_expires if isinstance(sso_expires, int) else None,
        raw={"status_code": resp.status_code, "data": data},
    )


def _print_status(prefix: str, status: AuthResult) -> None:
    details = {
        "ok": status.ok,
        "authenticated": status.authenticated,
        "connected": status.connected,
        "competing": status.competing,
        "session": status.session,
        "sso_expires": status.sso_expires,
    }
    print(prefix + json.dumps(details, indent=2, sort_keys=True))


def _run_browser_flow(
    *,
    gateway_url: str,
    username: Optional[str],
    password: Optional[str],
    paper: bool,
    manual: bool,
    headless: bool,
    timeout_seconds: int,
    two_fa_code: Optional[str],
) -> None:
    try:
        playwright_sync_api = importlib.import_module("playwright.sync_api")
        PlaywrightTimeoutError = getattr(playwright_sync_api, "TimeoutError")
        sync_playwright = getattr(playwright_sync_api, "sync_playwright")
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Playwright is not installed. Install with: uv pip install 'noetl[ibkr]' and then run: playwright install chromium"
        ) from e

    login_url = gateway_url.rstrip("/") + "/sso/Login?forwardTo=22&RL=1&ip2loc=on"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)

        if manual:
            print("Browser opened for manual login:")
            print("  " + login_url)
            print("Complete login in the opened window. This process will exit when the Gateway becomes authenticated.")

            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                try:
                    status = _tickle(gateway_url, timeout_seconds=15)
                    if status.ok and status.authenticated and status.connected and not status.competing:
                        return
                except Exception:
                    pass
                page.wait_for_timeout(500)

            raise RuntimeError("Timed out waiting for manual login to complete.")

        if not username or not password:
            raise RuntimeError(
                "Missing username/password. Provide via --username/--password or IBKR_USERNAME/IBKR_PASSWORD. "
                "Or run with --manual."
            )

        # IBKR has multiple login page variants; try common selectors.
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
            # Matches IBeam default selector.
            toggle = page.locator("label[for='toggle1']")
            try:
                if toggle.is_visible():
                    toggle.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass

        # Submit: button class from IBeam defaults; fallback to Enter.
        submit = page.locator(".btn.btn-lg.btn-primary")
        try:
            if submit.is_visible():
                submit.click()
            else:
                password_locator.press("Enter")
        except Exception:
            password_locator.press("Enter")

        # Success indicator text used by IBeam.
        success_text = page.get_by_text("Client login succeeds")

        # Possible 2FA triggers.
        two_fa_container = page.locator("#twofactbase")
        two_fa_input = page.locator("#xyz-field-bronze-response")

        # Error messages from IBeam defaults.
        err_v1 = page.locator(".alert.alert-danger.margin-top-10")
        err_v2 = page.locator(".xyz-errormessage")

        # Wait for one of: success, 2FA prompt, error.
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if success_text.count() > 0 and success_text.first.is_visible():
                return

            # Some flows show 2FA container; some show only the input.
            if two_fa_container.is_visible() or two_fa_input.is_visible():
                if not two_fa_code:
                    raise RuntimeError(
                        "2FA prompt detected but no code provided. Re-run with --two-fa-code or use --manual."
                    )
                two_fa_input.wait_for(state="visible", timeout=10_000)
                two_fa_input.fill(two_fa_code)
                two_fa_input.press("Enter")

                # After submitting 2FA, wait briefly for success.
                try:
                    success_text.wait_for(timeout=20_000)
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


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Authenticate IBKR Client Portal Gateway via web UI")
    parser.add_argument(
        "--gateway-url",
        default=os.environ.get("IBKR_GATEWAY_URL", "https://localhost:15000"),
        help="Gateway base URL, e.g. https://localhost:15000",
    )
    parser.add_argument("--username", default=os.environ.get("IBKR_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("IBKR_PASSWORD"))
    parser.add_argument("--paper", action="store_true", default=os.environ.get("IBKR_PAPER", "").lower() == "true")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Open the login page and let the user complete login manually.",
    )
    parser.add_argument("--headless", action="store_true", help="Run browser headless (default: headed)")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--poll-seconds", type=int, default=2)
    parser.add_argument("--two-fa-code", default=os.environ.get("IBKR_2FA_CODE"))

    args = parser.parse_args(argv)

    # Initial status probe.
    try:
        before = _tickle(args.gateway_url, timeout_seconds=15)
    except Exception as e:
        print(f"Initial tickle failed: {e}")
        before = AuthResult(
            ok=False,
            authenticated=False,
            connected=False,
            competing=False,
            session=None,
            sso_expires=None,
            raw={"error": str(e)},
        )

    _print_status("Before: ", before)
    if before.ok and before.authenticated and before.connected and not before.competing:
        print("Gateway already authenticated.")
        return 0

    _run_browser_flow(
        gateway_url=args.gateway_url,
        username=args.username,
        password=args.password,
        paper=args.paper,
        manual=args.manual,
        headless=args.headless,
        timeout_seconds=args.timeout_seconds,
        two_fa_code=args.two_fa_code,
    )

    # Poll tickle until authenticated.
    deadline = time.time() + args.timeout_seconds
    last: Optional[AuthResult] = None
    while time.time() < deadline:
        try:
            status = _tickle(args.gateway_url, timeout_seconds=15)
            last = status
            if status.ok and status.authenticated and status.connected and not status.competing:
                _print_status("After: ", status)
                print("Gateway authenticated.")
                return 0
        except Exception as e:
            last = AuthResult(
                ok=False,
                authenticated=False,
                connected=False,
                competing=False,
                session=None,
                sso_expires=None,
                raw={"error": str(e)},
            )

        time.sleep(args.poll_seconds)

    if last is not None:
        _print_status("After(timeout): ", last)
    print("Timed out waiting for gateway authentication.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
