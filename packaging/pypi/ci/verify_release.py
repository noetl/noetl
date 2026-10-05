#!/usr/bin/env python3
"""Refuse a PyPI release that would publish nothing, or publish the wrong version.

`twine upload --skip-existing` turns an already-published version into a no-op and
exits 0.  Nothing else in `pypi.yml` compares the git tag against the version that
was actually built, so two different mistakes both end in a green release that
shipped nothing:

  1. a `pypi-v5.1.2` tag cut while `packaging/pypi/` still says 5.1.1
     -> builds 5.1.1, uploads 5.1.1 if it is new, and the tag is a lie
  2. a `pypi-v5.1.1` tag cut again (a re-tag, or a retried release)
     -> builds 5.1.1, every file is skipped, zero bytes reach PyPI, job green

Case 2 is the one a tag/version equality check alone does NOT catch, because the
tag and the artifact agree.  It needs PyPI's own state.

Exit 0 only when every check passes.  Exit 1, loudly, otherwise.

Usage
-----
    verify_release.py --dist DIR [--tag REF] [--require-new]
                      [--pyproject P] [--cargo P] [--pypi-json P]
    verify_release.py --self-test

`--tag` accepts `refs/tags/pypi-v1.2.3`, `pypi-v1.2.3` or `1.2.3`.
`--require-new` fetches PyPI (or reads `--pypi-json`) and fails when every file
this release would upload is already published.
`--self-test` runs the guard against synthetic inputs and fails if any check does
not fire.  It runs on every PR so the guard cannot quietly stop working.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

PYPI_JSON = "https://pypi.org/pypi/{project}/json"
WHEEL_RE = re.compile(r"^(?P<name>[A-Za-z0-9_.]+)-(?P<ver>[^-]+)-.*\.whl$")
SDIST_RE = re.compile(r"^(?P<name>[A-Za-z0-9_.]+)-(?P<ver>.+)\.tar\.gz$")


class Failure(Exception):
    pass


def out(line: str = "") -> None:
    print(line, flush=True)


def read_toml_version(path: Path, table: str | None) -> str:
    """Read `version` from a TOML file.

    `table` None  -> the first top-level `version` (pyproject's [project]).
    `table` given -> `version` inside that table (Cargo's [package]).

    Deliberately not `tomllib`: this must run on the 3.9 floor the wheel targets,
    and the shape being read is two literal lines.
    """
    if not path.is_file():
        raise Failure(f"{path} does not exist")
    text = path.read_text(encoding="utf-8")
    if table:
        m = re.search(r"^\[" + re.escape(table) + r"\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
        if not m:
            raise Failure(f"{path} has no [{table}] table")
        text = m.group(1)
    m = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.M)
    if not m:
        where = f"[{table}] of " if table else ""
        raise Failure(f"no version found in {where}{path}")
    return m.group(1)


def normalise_tag(raw: str) -> str:
    v = raw.strip()
    for prefix in ("refs/tags/", "pypi-v", "v"):
        if v.startswith(prefix):
            v = v[len(prefix):]
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)*([a-zA-Z0-9.+-]*)", v):
        raise Failure(f"tag {raw!r} does not carry a version (parsed {v!r})")
    return v


def collect_dist(dist: Path) -> tuple[list[str], list[str], str]:
    """Return (wheels, sdists, the single version they all carry)."""
    if not dist.is_dir():
        raise Failure(f"--dist {dist} is not a directory")
    files = sorted(p.name for p in dist.iterdir() if p.is_file())
    wheels = [f for f in files if f.endswith(".whl")]
    sdists = [f for f in files if f.endswith(".tar.gz")]
    other = [f for f in files if f not in wheels and f not in sdists]

    out(f"  dist files            : {len(files)}   <- the denominator")
    for f in files:
        out(f"      {f}")
    if other:
        out(f"  ⚠ {len(other)} file(s) are neither a wheel nor an sdist: {other}")

    # Floors.  "0 problems" is also what a check over an empty directory prints,
    # and an empty dist/ is exactly what a broken download-artifact step leaves.
    if not wheels:
        raise Failure("no wheel in dist/ — refusing to reason about an empty build")
    if not sdists:
        raise Failure("no sdist in dist/ — refusing to reason about a partial build")

    versions: dict[str, list[str]] = {}
    for f in files:
        m = WHEEL_RE.match(f) or SDIST_RE.match(f)
        if not m:
            raise Failure(f"cannot parse a version out of {f!r}")
        versions.setdefault(m.group("ver"), []).append(f)
    if len(versions) != 1:
        detail = "; ".join(f"{v}: {sorted(fs)}" for v, fs in sorted(versions.items()))
        raise Failure(f"dist/ carries {len(versions)} different versions — {detail}")
    return wheels, sdists, next(iter(versions))


def fetch_pypi(project: str, pypi_json: Path | None) -> dict | None:
    if pypi_json is not None:
        if pypi_json.name == "-":
            return json.load(sys.stdin)
        return json.loads(pypi_json.read_text(encoding="utf-8"))
    url = PYPI_JSON.format(project=project)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # project has never been published; everything is new
        raise Failure(f"GET {url} failed: HTTP {e.code}")
    except Exception as e:  # noqa: BLE001 — a failed lookup must not read as "new"
        raise Failure(f"GET {url} failed: {e!r}")


def check_published(meta: dict | None, version: str, files: list[str]) -> None:
    """Fail when every file this release would upload is already on PyPI."""
    if meta is None:
        out("  PyPI                  : project not published yet — every file is new")
        return
    releases = meta.get("releases", {})
    out(f"  PyPI versions known   : {len(releases)}   latest {meta.get('info', {}).get('version')!r}")
    already = {f["filename"] for f in releases.get(version, [])}
    overlap = [f for f in files if f in already]
    out(f"  already on PyPI for {version}: {len(overlap)} of {len(files)}")
    for f in overlap:
        out(f"      {f}")
    if len(overlap) == len(files):
        raise Failure(
            f"every one of the {len(files)} file(s) for {version} is already on PyPI.\n"
            f"       `twine upload --skip-existing` would skip all of them and exit 0,\n"
            f"       so this release would publish NOTHING and report success.\n"
            f"       Bump packaging/pypi/pyproject.toml and packaging/pypi/Cargo.toml,\n"
            f"       then tag the new version."
        )
    if overlap:
        out(
            f"  ⚠ {len(overlap)} file(s) already published; {len(files) - len(overlap)} are new.\n"
            f"    Treating this as a retried release — --skip-existing covers the rest."
        )


def verify(args: argparse.Namespace) -> None:
    dist = Path(args.dist)
    out("── artifact")
    wheels, sdists, dist_ver = collect_dist(dist)
    out(f"  version in dist/      : {dist_ver}   ({len(wheels)} wheel(s), {len(sdists)} sdist(s))")

    out("── declared versions")
    py_ver = read_toml_version(Path(args.pyproject), None)
    cargo_ver = read_toml_version(Path(args.cargo), "package")
    out(f"  {args.pyproject:<34} {py_ver}")
    out(f"  {args.cargo:<34} {cargo_ver}")
    if py_ver != cargo_ver:
        raise Failure(
            f"pyproject.toml says {py_ver} and Cargo.toml says {cargo_ver}.\n"
            f"       These are bumped by hand and must move together."
        )
    if py_ver != dist_ver:
        raise Failure(
            f"the declared version is {py_ver} but dist/ built {dist_ver}.\n"
            f"       The artifact does not match the source tree it came from."
        )

    if args.tag:
        out("── tag")
        tag_ver = normalise_tag(args.tag)
        out(f"  {args.tag}  ->  {tag_ver}")
        if tag_ver != dist_ver:
            raise Failure(
                f"the tag says {tag_ver} but the build produced {dist_ver}.\n"
                f"       Nothing in pypi.yml derives the built version from the tag:\n"
                f"       it comes from packaging/pypi/pyproject.toml, which was not bumped.\n"
                f"       Tagging alone does not change what gets built."
            )
    elif args.require_new:
        raise Failure("--require-new needs --tag")

    if args.require_new:
        out("── PyPI state (would this upload anything?)")
        meta = fetch_pypi(args.project, Path(args.pypi_json) if args.pypi_json else None)
        check_published(meta, dist_ver, wheels + sdists)


# ---------------------------------------------------------------- self-test


def _touch(d: Path, names: list[str]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_bytes(b"x")


def _files(ver: str) -> list[str]:
    return [
        f"noetl-{ver}-cp39-abi3-macosx_11_0_arm64.whl",
        f"noetl-{ver}-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
        f"noetl-{ver}.tar.gz",
    ]


def _pypi(ver: str, filenames: list[str]) -> dict:
    return {
        "info": {"version": ver},
        "releases": {ver: [{"filename": f} for f in filenames]},
    }


def _case(root: Path, name: str, *, dist: list[str], py: str, cargo: str,
          tag: str | None, pypi: dict | None, require_new: bool) -> argparse.Namespace:
    d = root / name
    _touch(d / "dist", dist)
    (d / "pyproject.toml").write_text(f'[project]\nname = "noetl"\nversion = "{py}"\n')
    (d / "Cargo.toml").write_text(f'[package]\nname = "noetl-python"\nversion = "{cargo}"\n')
    pj = None
    if pypi is not None:
        pj = d / "pypi.json"
        pj.write_text(json.dumps(pypi))
    return argparse.Namespace(
        dist=str(d / "dist"), pyproject=str(d / "pyproject.toml"),
        cargo=str(d / "Cargo.toml"), tag=tag, require_new=require_new,
        project="noetl", pypi_json=str(pj) if pj else None,
    )


def self_test() -> int:
    """Every control must fire.  A guard never shown to fail is a comment."""
    out("=" * 72)
    out("SELF-TEST — each control must produce the outcome named")
    out("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="verify-release-selftest-"))
    cases: list[tuple[str, argparse.Namespace, bool]] = []

    # the shape this guard exists for: a re-tag of an already-published version
    cases.append((
        "same-version re-tag: all 3 files already on PyPI  (THE #400 SCENARIO)",
        _case(root, "retag", dist=_files("5.1.1"), py="5.1.1", cargo="5.1.1",
              tag="refs/tags/pypi-v5.1.1", pypi=_pypi("5.1.1", _files("5.1.1")),
              require_new=True),
        False,
    ))
    cases.append((
        "tag ahead of the source tree (tag 5.1.2, dist 5.1.1)",
        _case(root, "tagahead", dist=_files("5.1.1"), py="5.1.1", cargo="5.1.1",
              tag="refs/tags/pypi-v5.1.2", pypi=None, require_new=False),
        False,
    ))
    cases.append((
        "half-bump: pyproject 5.1.2, Cargo 5.1.1",
        _case(root, "halfbump", dist=_files("5.1.2"), py="5.1.2", cargo="5.1.1",
              tag="refs/tags/pypi-v5.1.2", pypi=None, require_new=False),
        False,
    ))
    cases.append((
        "dist carries a version neither file declares",
        _case(root, "distdrift", dist=_files("5.0.9"), py="5.1.2", cargo="5.1.2",
              tag="refs/tags/pypi-v5.1.2", pypi=None, require_new=False),
        False,
    ))
    cases.append((
        "two versions in one dist/",
        _case(root, "mixed", dist=_files("5.1.1") + _files("5.1.2"), py="5.1.2",
              cargo="5.1.2", tag="refs/tags/pypi-v5.1.2", pypi=None, require_new=False),
        False,
    ))
    cases.append((
        "empty dist/ (a broken download-artifact step)",
        _case(root, "empty", dist=[], py="5.1.2", cargo="5.1.2",
              tag="refs/tags/pypi-v5.1.2", pypi=None, require_new=False),
        False,
    ))
    cases.append((
        "wheels but no sdist (a partial build)",
        _case(root, "nosdist", dist=[f for f in _files("5.1.2") if f.endswith(".whl")],
              py="5.1.2", cargo="5.1.2", tag="refs/tags/pypi-v5.1.2", pypi=None,
              require_new=False),
        False,
    ))

    # and the cases that MUST pass, or the guard would block real releases
    cases.append((
        "genuine new version, nothing on PyPI yet",
        _case(root, "good", dist=_files("5.1.2"), py="5.1.2", cargo="5.1.2",
              tag="refs/tags/pypi-v5.1.2", pypi=_pypi("5.1.1", _files("5.1.1")),
              require_new=True),
        True,
    ))
    cases.append((
        "retried release: 1 of 3 already up, 2 still new",
        _case(root, "partial", dist=_files("5.1.2"), py="5.1.2", cargo="5.1.2",
              tag="refs/tags/pypi-v5.1.2",
              pypi=_pypi("5.1.2", [_files("5.1.2")[0]]), require_new=True),
        True,
    ))
    cases.append((
        "pull request: no tag, versions agree",
        _case(root, "pr", dist=_files("5.1.1"), py="5.1.1", cargo="5.1.1",
              tag=None, pypi=None, require_new=False),
        True,
    ))

    width = max(len(n) for n, _, _ in cases)
    results = []
    for name, ns, want_pass in cases:
        try:
            verify(ns)
            got_pass, why = True, ""
        except Failure as e:
            got_pass, why = False, str(e).splitlines()[0]
        ok = got_pass == want_pass
        results.append((ok, name, want_pass, got_pass, why))

    out()
    out("-" * 72)
    out(f"{'case':<{width}}  want  got   verdict")
    out("-" * 72)
    for ok, name, want_pass, got_pass, why in results:
        w = "pass" if want_pass else "FAIL"
        g = "pass" if got_pass else "FAIL"
        out(f"{name:<{width}}  {w:<4}  {g:<4}  {'ok' if ok else '*** WRONG'}")
        if why and not want_pass:
            out(f"{'':<{width}}        reason: {why}")
    bad = [r for r in results if not r[0]]
    out("-" * 72)
    out(f"  controls: {len(results)}   firing as specified: {len(results) - len(bad)}   wrong: {len(bad)}")
    if bad:
        out("  *** the guard does not behave as documented — do not trust it")
        return 1
    out("  every control fires as specified")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dist", help="directory holding the built wheels + sdist")
    p.add_argument("--tag", help="refs/tags/pypi-vX.Y.Z, pypi-vX.Y.Z or X.Y.Z")
    p.add_argument("--require-new", action="store_true",
                   help="fail if every file is already published (needs --tag)")
    p.add_argument("--project", default="noetl", help="PyPI project name")
    p.add_argument("--pyproject", default="packaging/pypi/pyproject.toml")
    p.add_argument("--cargo", default="packaging/pypi/Cargo.toml")
    p.add_argument("--pypi-json", help="read PyPI metadata from a file instead of the network")
    p.add_argument("--self-test", action="store_true",
                   help="run the guard against synthetic inputs and check every control fires")
    p.add_argument("--print-version", action="store_true",
                   help="print the single version dist/ carries, and nothing else")
    args = p.parse_args()

    if args.self_test:
        return self_test()
    if not args.dist:
        p.error("--dist is required (or pass --self-test)")

    if args.print_version:
        # Quiet mode for shell use: the same parse the checks rely on, so a caller
        # cannot disagree with the guard about which version is in dist/.
        import io
        import contextlib
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                _, _, ver = collect_dist(Path(args.dist))
        except Failure as e:
            print(f"verify_release: {e}", file=sys.stderr)
            return 1
        print(ver)
        return 0

    out("── verifying this release can actually publish something")
    try:
        verify(args)
    except Failure as e:
        out()
        out("#" * 72)
        out("RELEASE REFUSED")
        out("#" * 72)
        out(f"  {e}")
        out()
        out("  Context: noetl/ai-meta#400.  pypi.yml uploads with")
        out("  `twine upload --skip-existing`, which exits 0 when it skips, so without")
        out("  this check a release in that state would report success and ship nothing.")
        return 1
    out()
    # Say only what was actually checked.  A success line that claims more than it
    # verified is the defect this whole guard exists to prevent, one level up.
    checked = ["pyproject.toml == Cargo.toml == the built filenames"]
    if args.tag:
        checked.append("the tag matches the built version")
    if args.require_new:
        checked.append("PyPI does not already have every file")
    out("  OK — verified: " + "; ".join(checked) + ".")
    if not args.require_new:
        out("  NOT checked: whether PyPI already has this version. That needs --tag")
        out("  --require-new, which only a tag build can supply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
