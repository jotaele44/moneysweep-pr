#!/usr/bin/env python3
"""Fail when a change makes a document that describes this repo untrue.

Rendered from thehub-pr/federation-templates/baseline/check_docs_sync.py.
Do not hand-edit - template-drift.yml fails the build if you do. Change the
template and re-render.

ADR 0004 already says documentation must agree with the machine-readable state
of the federation; this is the general form of that rule. No tool can prove that
prose still matches code, so this enforces the three things that *can* be
checked mechanically and turns everything else into an explicit, reviewable
decision instead of a silent omission:

* **R1 co-change.** ``.federation/docs-sync.json`` declares which docs describe
  which paths. Change a covered path and the doc must change in the same diff, or
  a commit-message / PR line ``Docs-Impact: none - <reason>`` must say why not.
* **R2 references (a ratchet).** A change may not leave a doc pointing at a path
  that no longer exists. Only references *this change* broke count, so the
  legacy backlog never blocks anyone: the rule is "clean what you touch".
* **R3 manifest hygiene.** The manifest may not rot: unknown keys, missing docs
  and globs that stopped matching anything are reported.

One script, one verdict, several entry points:

  --base REV [--head REV]  CI and review: the diff REV...head, waivers read from
                           the commit messages in that range plus $PR_BODY.
  --staged                 pre-commit: the index against HEAD. R1 only warns here
                           because the commit message does not exist yet.
  --agent-hook             Claude Code Stop hook: JSON on stdin, block decision
                           on stdout. Sees committed, staged, unstaged and
                           untracked changes since the branch left its base.
  --list / --validate      print the coupling table / check the manifest alone.

Stdlib only and Python >= 3.9 on purpose: the same file runs in every federation
repo, whose interpreters range from 3.9 to 3.13, and it must run from a bare
checkout with nothing installed. Annotations use the modern spellings, which is
safe on 3.9 only because of ``from __future__ import annotations``; keep every
type that is evaluated at runtime free of ``X | Y``.

Exit status: 0 clean (or ``"mode": "report"``), 1 violations, 2 usage or
configuration error.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import json
import os
import posixpath
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

SCHEMA_VERSION = "prii_docs_sync_v1"
MANIFEST_PATH = ".federation/docs-sync.json"
EVENTS = ("add", "delete", "rename", "modify")
# Structure changes are what "lists of things" go stale on. Edits inside a
# covered file are opt-in (`"on": [..., "modify"]`): far more frequent and far
# less often relevant to prose, so defaulting to them would train people to
# waive without reading.
DEFAULT_ON = ("add", "delete", "rename")
DEFAULT_EXEMPT_AUTHORS = (
    "dependabot[bot]",
    "github-actions[bot]",
    "prii-federation-bot",
)
MIN_REASON_CHARS = 10
MAX_HOOK_BLOCKS = 3
HOOK_STATE_FILE = "prii-docs-sync-hook.json"
WAIVE_HINT = "Docs-Impact: none - <why no doc change is needed>"

# `Optional[str]` spelled as a forward reference so this alias is valid at
# runtime on 3.9 without tripping pyupgrade in repos that target 3.10+.
Reader = Callable[[str], "str | None"]


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #


class ManifestError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class GitError(Exception):
    pass


@dataclass(frozen=True)
class Coupling:
    doc: str
    covers: tuple[str, ...]
    exclude: tuple[str, ...]
    on: tuple[str, ...]
    why: str


@dataclass(frozen=True)
class Manifest:
    mode: str
    base_branch: str
    exempt_docs: tuple[str, ...]
    ignore_refs: tuple[str, ...]
    exempt_authors: tuple[str, ...]
    couplings: tuple[Coupling, ...]


_TOP_KEYS = {
    "_comment",
    "schema_version",
    "mode",
    "base_branch",
    "exempt_docs",
    "ignore_refs",
    "exempt_authors",
    "couplings",
}
_COUPLING_KEYS = {"doc", "covers", "exclude", "on", "why"}


def _norm(path: str) -> str:
    path = path.strip()
    path = path[2:] if path.startswith("./") else path
    return posixpath.normpath(path) if path else path


def _str_list(
    value: object, where: str, problems: list[str], *, required: bool = False
) -> tuple[str, ...]:
    if value is None:
        if required:
            problems.append(f"{where}: required")
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        problems.append(f"{where}: must be a list of non-empty strings")
        return ()
    if required and not value:
        problems.append(f"{where}: must not be empty")
    return tuple(v.strip() for v in value)


def parse_manifest(text: str) -> Manifest:
    """Parse and validate the manifest, reporting every problem at once.

    Unknown keys are errors, not ignored: a typo such as ``cover`` would
    otherwise yield a coupling that silently covers nothing, which is the
    failure this whole tool exists to prevent.
    """
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise ManifestError([f"not valid JSON: {exc}"]) from exc
    if not isinstance(raw, dict):
        raise ManifestError(["top level must be a JSON object"])
    problems = [f"unknown key {key!r}" for key in sorted(set(raw) - _TOP_KEYS)]
    if raw.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION!r}")
    mode = raw.get("mode", "enforce")
    if mode not in ("enforce", "report"):
        problems.append("mode must be 'enforce' or 'report'")
    base_branch = raw.get("base_branch", "main")
    if not isinstance(base_branch, str) or not base_branch:
        problems.append("base_branch must be a non-empty string")
        base_branch = "main"
    exempt_docs = _str_list(raw.get("exempt_docs"), "exempt_docs", problems)
    ignore_refs = _str_list(raw.get("ignore_refs"), "ignore_refs", problems)
    exempt_authors = _str_list(raw.get("exempt_authors"), "exempt_authors", problems)

    couplings: list[Coupling] = []
    entries = raw.get("couplings", [])
    if not isinstance(entries, list):
        problems.append("couplings must be a list")
        entries = []
    for i, entry in enumerate(entries):
        where = f"couplings[{i}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: must be an object")
            continue
        problems += [f"{where}: unknown key {key!r}" for key in sorted(set(entry) - _COUPLING_KEYS)]
        doc = entry.get("doc")
        if not isinstance(doc, str) or not doc.strip():
            problems.append(f"{where}.doc: required")
            doc = ""
        covers = _str_list(entry.get("covers"), f"{where}.covers", problems, required=True)
        exclude = _str_list(entry.get("exclude"), f"{where}.exclude", problems)
        on = _str_list(entry.get("on"), f"{where}.on", problems) or DEFAULT_ON
        problems += [
            f"{where}.on: {event!r} is not one of {', '.join(EVENTS)}"
            for event in on
            if event not in EVENTS
        ]
        why = entry.get("why")
        if not isinstance(why, str) or not why.strip():
            problems.append(f"{where}.why: required (say what the doc claims about these paths)")
            why = ""
        couplings.append(Coupling(_norm(doc), covers, exclude, on, why.strip()))
    if problems:
        raise ManifestError(problems)
    return Manifest(mode, base_branch, exempt_docs, ignore_refs, exempt_authors, tuple(couplings))


def merge_manifests(head: Manifest, base: Manifest | None) -> Manifest:
    """Judge a change by the rules it arrived with *and* the rules it edits.

    Otherwise a PR could pass by deleting the coupling it violates, or by
    flipping ``mode`` to ``report``. Legitimately removing a coupling still
    works: touch the doc, or waive it with a reason a reviewer can read.
    """
    if base is None:
        return head
    extra = tuple(c for c in base.couplings if c not in head.couplings)
    mode = "enforce" if "enforce" in (head.mode, base.mode) else "report"
    return Manifest(
        mode,
        head.base_branch,
        head.exempt_docs,
        head.ignore_refs,
        head.exempt_authors,
        head.couplings + extra,
    )


# --------------------------------------------------------------------------- #
# Paths and globs
# --------------------------------------------------------------------------- #


@functools.cache
def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """``**`` spans directories, ``*`` and ``?`` do not; a trailing ``/`` means the tree."""
    if pattern.endswith("/"):
        pattern += "**"
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            j = i
            while j < n and pattern[j] == "*":
                j += 1
            if j - i < 2:
                out.append("[^/]*")
            elif pattern[j : j + 1] == "/":
                out.append("(?:.*/)?")
                j += 1
            else:
                out.append(".*")
            i = j
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[" and pattern.find("]", i + 1) != -1:
            j = pattern.find("]", i + 1)
            body = pattern[i + 1 : j]
            body = "^" + body[1:] if body.startswith("!") else body
            out.append("[" + body.replace("\\", "\\\\") + "]")
            i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(path: str, patterns: Iterable[str]) -> bool:
    return any(glob_to_regex(p).match(path) for p in patterns)


class Tree:
    """The set of paths present at one point in time, with directory lookups."""

    def __init__(self, paths: Iterable[str]) -> None:
        self.files: set[str] = set(paths)
        self.dirs: set[str] = set()
        for path in self.files:
            d = posixpath.dirname(path)
            while d and d not in self.dirs:
                self.dirs.add(d)
                d = posixpath.dirname(d)

    def has(self, ref: str) -> bool:
        ref = ref.rstrip("/")
        return ref in self.files or ref in self.dirs


# --------------------------------------------------------------------------- #
# Changes and waivers
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Change:
    event: str  # add | delete | rename | modify
    path: str
    old_path: str | None = None  # set for renames


def parse_name_status(raw: str) -> list[Change]:
    """Parse ``git diff --name-status -z -M`` output."""
    tokens = raw.split("\0")
    changes: list[Change] = []
    i = 0
    while i < len(tokens) and tokens[i]:
        status = tokens[i]
        width = 3 if status[0] in "RC" else 2
        entry = tokens[i : i + width]
        if len(entry) < width or not all(entry):
            break  # truncated output: keep what parsed rather than invent paths
        i += width
        if status[0] == "R":
            changes.append(Change("rename", entry[2], entry[1]))
            if status != "R100":
                changes.append(Change("modify", entry[2]))
        elif status[0] == "C":
            changes.append(Change("add", entry[2]))
        else:
            event = {"A": "add", "D": "delete"}.get(status[0], "modify")
            changes.append(Change(event, entry[1]))
    return changes


def events_by_path(changes: Iterable[Change]) -> dict[str, set[str]]:
    events: dict[str, set[str]] = {}
    for change in changes:
        events.setdefault(change.path, set()).add(change.event)
        if change.old_path is not None:
            events.setdefault(change.old_path, set()).add("rename")
    return events


@dataclass(frozen=True)
class Waiver:
    target: str  # "none" or a doc path
    reason: str
    source: str


_WAIVER_LINE = re.compile(r"^[ \t>*-]*docs-impact:(?P<rest>.*)$", re.I | re.M)
_WAIVER_BODY = re.compile(
    r"^\s*(?P<target>\S+?)(?:\s+(?:—|–|--|-)\s+|\s*:\s+)(?P<reason>\S.*?)\s*$"
)


def parse_waivers(text: str, source: str) -> tuple[list[Waiver], list[str]]:
    """Return (valid waivers, malformed ``Docs-Impact`` lines).

    A waiver with no reason is worse than none: it reads as diligence and tells
    the reviewer nothing, so it is reported rather than honoured.
    """
    good: list[Waiver] = []
    bad: list[str] = []
    for match in _WAIVER_LINE.finditer(text):
        body = _WAIVER_BODY.match(match.group("rest").strip())
        if body and len(body.group("reason").strip()) >= MIN_REASON_CHARS:
            target = body.group("target").strip()
            target = "none" if target.lower() == "none" else _norm(target)
            good.append(Waiver(target, body.group("reason").strip(), source))
        else:
            bad.append(f"{source}: 'Docs-Impact:{match.group('rest').rstrip()}'")
    return good, bad


def _waiver_for(waivers: Sequence[Waiver], doc: str, *, allow_none: bool) -> Waiver | None:
    for waiver in waivers:
        if waiver.target == doc or (allow_none and waiver.target == "none"):
            return waiver
    return None


# --------------------------------------------------------------------------- #
# Reference extraction (R2)
# --------------------------------------------------------------------------- #

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_TICKS = re.compile(r"`+([^`\n]+)`+")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# Anything that is a glob, placeholder, shell syntax, URL fragment or scoped
# package name rather than a plain repo path.
_NOT_A_PATH = re.compile(r"[*<>{}$|;=,()\[\]\"'\\!?^~@]")
_LOCATOR = re.compile(r"(::[\w.\[\]-]+|:\d+(?:-\d+)?)$")  # pytest node id / file:line


def _strip_markup(text: str) -> str:
    """Drop what is not a claim about the repo: HTML comments and code fences.

    Fenced blocks are sample output and example commands full of illustrative
    paths; treating them as claims would make every tutorial a false positive.
    """
    kept: list[str] = []
    fence: str | None = None
    for line in _HTML_COMMENT.sub("", text).splitlines():
        match = _FENCE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
            else:
                kept.append(line)
        elif (
            match
            and match.group(1)[0] == fence[0]
            and len(match.group(1)) >= len(fence)
            and line.strip() == match.group(1)
        ):
            fence = None
    return "\n".join(kept)


def _link_ref(doc: str, target: str) -> str | None:
    if not target or target.startswith(("#", "/")) or _SCHEME.match(target):
        return None
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(doc), target))
    return None if resolved == "." or resolved.startswith("..") else resolved


def _tick_refs(span: str, top: set[str]) -> list[str]:
    """Anchored paths inside one inline-code span.

    Anchored means the first segment is a real top-level entry of this repo.
    Bare file names are ambiguous (`ci.yml` could be anywhere) and paths into
    sibling repos cannot be resolved here, so both are skipped rather than
    guessed at: a false positive costs trust in the whole gate.
    """
    refs: list[str] = []
    for token in span.split():
        token = _LOCATOR.sub("", token.rstrip(".,:;"))
        token = token[2:] if token.startswith("./") else token
        if "/" not in token or token.startswith(("-", "/")):
            continue
        if _NOT_A_PATH.search(token) or _SCHEME.match(token):
            continue
        if token.split("/", 1)[0] in top:
            refs.append(posixpath.normpath(token))
    return refs


def extract_refs(doc: str, text: str, top: set[str]) -> set[str]:
    clean = _strip_markup(text)
    refs = {r for m in _LINK.finditer(clean) if (r := _link_ref(doc, m.group(1)))}
    for match in _TICKS.finditer(clean):
        refs.update(_tick_refs(match.group(1), top))
    return refs


def _is_doc(path: str) -> bool:
    return path.endswith(".md") and ("/" not in path or path.startswith("docs/"))


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #


@dataclass
class Finding:
    rule: str  # coupling | reference | manifest | waiver
    doc: str
    message: str
    fix: str


@dataclass
class Report:
    violations: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    waived: list[str] = field(default_factory=list)


def evaluate(
    manifest: Manifest,
    changes: Sequence[Change],
    base: Tree,
    head: Tree,
    read_base: Reader,
    read_head: Reader,
    waivers: Sequence[Waiver] = (),
    malformed_waivers: Sequence[str] = (),
    *,
    staged: bool = False,
) -> Report:
    """Pure verdict for one change. All git I/O lives in the collectors below."""
    report = Report()
    for line in malformed_waivers:
        report.violations.append(
            Finding(
                "waiver",
                "-",
                f"unusable waiver: {line}",
                f"write it as '{WAIVE_HINT}' with a reason of at least "
                f"{MIN_REASON_CHARS} characters",
            )
        )
    _check_manifest(manifest, base, head, report)

    events = events_by_path(changes)
    touched = {
        p for p, ev in events.items() if ev & {"add", "modify", "rename"} and p in head.files
    }

    # R1 co-change ---------------------------------------------------------
    for coupling in manifest.couplings:
        wanted = set(coupling.on)
        hits = sorted(
            p
            for p, ev in events.items()
            if ev & wanted and matches(p, coupling.covers) and not matches(p, coupling.exclude)
        )
        if not hits or coupling.doc in touched:
            continue
        waiver = _waiver_for(waivers, coupling.doc, allow_none=True)
        if waiver is not None:
            report.waived.append(f"{coupling.doc}: {waiver.reason} [{waiver.source}]")
            continue
        shown = ", ".join(f"{p} ({'/'.join(sorted(events[p] & wanted))})" for p in hits[:4])
        shown += f" and {len(hits) - 4} more" if len(hits) > 4 else ""
        finding = Finding(
            "coupling",
            coupling.doc,
            f"{coupling.doc} was not updated, but this change touches paths it "
            f"covers: {shown}. Why it covers them: {coupling.why}",
            f"update {coupling.doc} in this change, or add the line '{WAIVE_HINT}'",
        )
        # At pre-commit time the message that could carry a waiver is not
        # written yet, so a hard failure would be unanswerable. CI decides.
        (report.warnings if staged else report.violations).append(finding)

    # R2 references (ratchet) ------------------------------------------------
    top = {p.split("/", 1)[0] for p in head.files | base.files}
    scope = {p for p in head.files if _is_doc(p)}
    scope |= {c.doc for c in manifest.couplings if c.doc in head.files}
    for doc in sorted(d for d in scope if not matches(d, manifest.exempt_docs)):
        text = read_head(doc)
        if text is None:
            continue
        broken = [
            ref
            for ref in sorted(extract_refs(doc, text, top))
            if not head.has(ref)
            and not matches(ref, manifest.ignore_refs)
            and not matches(ref + "/", manifest.ignore_refs)
        ]
        if not broken:
            continue
        old_text = read_base(doc)
        old_refs = extract_refs(doc, old_text, top) if old_text is not None else set()
        for ref in broken:
            if ref in old_refs and not base.has(ref):
                continue  # already dangling before this change: not ours to fix here
            waiver = _waiver_for(waivers, doc, allow_none=False)
            if waiver is not None:
                report.waived.append(f"{doc} -> {ref}: {waiver.reason} [{waiver.source}]")
                continue
            cause = "was removed or renamed by this change" if base.has(ref) else "does not exist"
            report.violations.append(
                Finding(
                    "reference",
                    doc,
                    f"{doc} points at '{ref}', which {cause}",
                    f"fix the reference in {doc}; if it is intentional (for example a "
                    f"generated file), add it to ignore_refs in {MANIFEST_PATH} or add "
                    f"'Docs-Impact: {doc} - <reason>'",
                )
            )
    return report


def _check_manifest(manifest: Manifest, base: Tree, head: Tree, report: Report) -> None:
    for coupling in manifest.couplings:
        if coupling.doc not in head.files:
            report.violations.append(
                Finding(
                    "manifest",
                    coupling.doc,
                    f"coupling doc '{coupling.doc}' does not exist",
                    f"restore the doc or update {MANIFEST_PATH}",
                )
            )
        for pattern in coupling.covers:
            if any(matches(p, [pattern]) for p in head.files):
                continue
            if any(matches(p, [pattern]) for p in base.files):
                report.violations.append(
                    Finding(
                        "manifest",
                        coupling.doc,
                        f"this change removed the last file matching '{pattern}' "
                        f"(covered by {coupling.doc})",
                        f"update the coupling in {MANIFEST_PATH}, and {coupling.doc} "
                        "if it lists those files",
                    )
                )
            else:
                report.warnings.append(
                    Finding(
                        "manifest",
                        coupling.doc,
                        f"'{pattern}' (covered by {coupling.doc}) matches no files",
                        f"remove or correct it in {MANIFEST_PATH}",
                    )
                )


# --------------------------------------------------------------------------- #
# Git plumbing
# --------------------------------------------------------------------------- #


def _git(root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        if check:
            detail = proc.stderr.strip() or proc.returncode
            raise GitError(f"git {' '.join(args)}: {detail}")
        return ""
    return proc.stdout


def _resolves(root: Path, rev: str) -> bool:
    return (
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "rev-parse",
                "--verify",
                "--quiet",
                rev + "^{commit}",
            ],
            capture_output=True,
        ).returncode
        == 0
    )


def _blob_reader(root: Path, prefix: str) -> Reader:
    """Read ``<prefix><path>`` from git (``rev:`` for a commit, ``:`` for the index)."""

    @functools.cache
    def read(path: str) -> str | None:
        proc = subprocess.run(
            ["git", "-C", str(root), "show", f"{prefix}{path}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.stdout if proc.returncode == 0 else None

    return read


def _worktree_reader(root: Path) -> Reader:
    def read(path: str) -> str | None:
        try:
            return (root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    return read


def _paths(raw: str) -> list[str]:
    return [p for p in raw.split("\0") if p]


def _tree_at(root: Path, rev: str) -> Tree:
    return Tree(_paths(_git(root, "ls-tree", "-r", "--name-only", "-z", rev)))


def _messages(root: Path, base: str, head: str) -> list[tuple[str, str]]:
    raw = _git(root, "log", "--format=%h%x1f%B%x00", f"{base}..{head}", check=False)
    out: list[tuple[str, str]] = []
    for chunk in raw.split("\0"):
        sha, _, body = chunk.strip("\n").partition("\x1f")
        if body.strip():
            out.append((f"commit {sha.strip()}", body))
    return out


@dataclass
class Context:
    changes: list[Change]
    base: Tree
    head: Tree
    read_base: Reader
    read_head: Reader
    messages: list[tuple[str, str]]


def collect_range(root: Path, base: str, head: str) -> Context:
    for rev in (base, head):
        if not _resolves(root, rev):
            raise GitError(
                f"cannot resolve revision '{rev}' (shallow checkout? use fetch-depth: 0)"
            )
    fork = _git(root, "merge-base", base, head, check=False).strip() or base
    return Context(
        parse_name_status(_git(root, "diff", "--name-status", "-z", "-M", fork, head)),
        _tree_at(root, fork),
        _tree_at(root, head),
        _blob_reader(root, f"{fork}:"),
        _blob_reader(root, f"{head}:"),
        _messages(root, fork, head),
    )


def collect_staged(root: Path) -> Context | None:
    if not _resolves(root, "HEAD"):
        return None  # first commit: nothing to compare against
    return Context(
        parse_name_status(_git(root, "diff", "--cached", "--name-status", "-z", "-M")),
        _tree_at(root, "HEAD"),
        Tree(_paths(_git(root, "ls-files", "-z"))),
        _blob_reader(root, "HEAD:"),
        _blob_reader(root, ":"),
        [],
    )


def collect_agent(root: Path, base_branch: str) -> Context | None:
    """Everything since this branch left its base, whether or not it is committed.

    The base is the local ``origin/<base_branch>``. After a long time without a
    ``git fetch`` that ref can be older than the branch's real base, and other
    people's already-merged commits then look like part of this change. CI reads
    the pull request's own base SHA and has no such problem, so it stays the
    authority; the hook only stops trying after a few rounds.
    """
    candidates = (f"origin/{base_branch}", base_branch, "origin/HEAD")
    base_ref = next((r for r in candidates if _resolves(root, r)), None)
    if base_ref is None or not _resolves(root, "HEAD"):
        return None
    fork = _git(root, "merge-base", base_ref, "HEAD", check=False).strip() or base_ref
    changes = parse_name_status(_git(root, "diff", "--name-status", "-z", "-M", fork))
    untracked = _paths(_git(root, "ls-files", "-z", "--others", "--exclude-standard"))
    changes += [Change("add", p) for p in untracked]
    present = set(_paths(_git(root, "ls-files", "-z"))) | set(untracked)
    present -= set(_paths(_git(root, "ls-files", "-z", "--deleted")))
    return Context(
        changes,
        _tree_at(root, fork),
        Tree(present),
        _blob_reader(root, f"{fork}:"),
        _worktree_reader(root),
        _messages(root, fork, "HEAD"),
    )


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def _annotation(level: str, finding: Finding) -> str:
    text = f"{finding.message} -> {finding.fix}"
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    where = f"file={finding.doc}," if finding.doc not in ("", "-") else ""
    return f"::{level} {where}title=docs-sync ({finding.rule})::{text}"


def render_text(report: Report, mode: str) -> str:
    label = "violation(s)" if mode == "enforce" else "finding(s) [report-only]"
    lines = [
        f"docs-sync: {len(report.violations)} {label}, "
        f"{len(report.warnings)} warning(s), {len(report.waived)} waived"
    ]
    tag = "ERROR" if mode == "enforce" else "REPORT"
    for name, findings in ((tag, report.violations), ("WARN", report.warnings)):
        for f in findings:
            lines += [f"  {name} [{f.rule}] {f.message}", f"       fix: {f.fix}"]
    lines += [f"  WAIVED {item}" for item in report.waived]
    if report.violations or report.warnings:
        lines.append(
            f"  policy: CONTRIBUTING.md 'Documentation stays true'; config: {MANIFEST_PATH}"
        )
    if os.environ.get("GITHUB_ACTIONS") == "true":
        level = "error" if mode == "enforce" else "warning"
        lines += [_annotation(level, f) for f in report.violations]
        lines += [_annotation("warning", f) for f in report.warnings]
    return "\n".join(lines)


def hook_reason(report: Report) -> str:
    items = [f"{n}. {f.message}\n   -> {f.fix}" for n, f in enumerate(report.violations, 1)]
    return (
        "docs-sync: this change leaves documentation that describes the repo out "
        "of date. Update the docs now, then finish.\n\n"
        + "\n".join(items)
        + "\n\nIf a doc genuinely needs no change, say so in a commit message line: "
        + WAIVE_HINT
        + f"\nPolicy: CONTRIBUTING.md 'Documentation stays true'. Config: {MANIFEST_PATH}"
    )


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def _load_manifest(root: Path, rel: str) -> Manifest:
    try:
        text = (root / rel).read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError([f"cannot read {rel}: {exc.strerror or exc}"]) from exc
    return parse_manifest(text)


def _judge(
    manifest_rel: str,
    ctx: Context,
    head_manifest: Manifest,
    *,
    pr_body: str,
    staged: bool,
) -> tuple[Report, Manifest]:
    base_manifest: Manifest | None = None
    old = ctx.read_base(manifest_rel)
    if old is not None:
        # A broken old manifest must not block fixing it.
        with contextlib.suppress(ManifestError):
            base_manifest = parse_manifest(old)
    manifest = merge_manifests(head_manifest, base_manifest)
    waivers: list[Waiver] = []
    malformed: list[str] = []
    sources = list(ctx.messages)
    if pr_body:
        sources.append(("PR description", pr_body))
    for source, body in sources:
        good, bad = parse_waivers(body, source)
        waivers += good
        malformed += bad
    report = evaluate(
        manifest,
        ctx.changes,
        ctx.base,
        ctx.head,
        ctx.read_base,
        ctx.read_head,
        waivers,
        malformed,
        staged=staged,
    )
    return report, manifest


def _hook_blocks_so_far(state_path: Path | None, session: str, key: str) -> int:
    if state_path is None:
        return 0
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        same_round = state.get("session") == session and state.get("key") == key
        return int(state.get("blocks", 0)) if same_round else 0
    except (OSError, ValueError, TypeError, AttributeError):
        # No state yet, or a file that is not ours: this is the first block of a
        # round. Starting over is safe because CI, not this hook, is the authority.
        return 0


def run_agent_hook(root_arg: str | None, manifest_rel: str, stdin_text: str) -> int:
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    start = Path(str(payload.get("cwd") or root_arg or os.getcwd()))
    try:
        root = Path(_git(start, "rev-parse", "--show-toplevel").strip())
        manifest = _load_manifest(root, manifest_rel)
    except (GitError, ManifestError, OSError):
        return 0  # not a repo we govern, or not configured yet: never trap a session
    ctx = collect_agent(root, manifest.base_branch)
    if ctx is None:
        return 0
    report, manifest = _judge(manifest_rel, ctx, manifest, pr_body="", staged=False)
    if not report.violations or manifest.mode != "enforce":
        return 0

    # Each block costs the agent a turn, and CI stays the authority, so a
    # violation that survives a few rounds is handed over rather than looped on.
    key = "|".join(sorted(f"{f.rule}:{f.doc}:{f.message}" for f in report.violations))
    session = str(payload.get("session_id") or "")
    try:
        git_dir = _git(root, "rev-parse", "--absolute-git-dir").strip()
        state_path: Path | None = Path(git_dir) / HOOK_STATE_FILE
    except GitError:
        state_path = None
    blocks = _hook_blocks_so_far(state_path, session, key)
    if blocks >= MAX_HOOK_BLOCKS or (state_path is None and payload.get("stop_hook_active")):
        print(
            "docs-sync: unresolved after repeated prompts; leaving it to CI.",
            file=sys.stderr,
        )
        return 0
    if state_path is not None:
        state = {"session": session, "key": key, "blocks": blocks + 1}
        try:
            state_path.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            if payload.get("stop_hook_active"):
                return 0  # cannot count, so cannot bound the loop: stand down
    print(json.dumps({"decision": "block", "reason": hook_reason(report)}))
    return 0


def _parser() -> argparse.ArgumentParser:
    summary = (__doc__ or "").split("\n\n", 1)[0]
    parser = argparse.ArgumentParser(description=summary)
    parser.add_argument("--root", help="repository root (default: repo of the cwd)")
    parser.add_argument("--manifest", default=MANIFEST_PATH, help="manifest path")
    parser.add_argument("--base", help="base revision for the diff (CI / review)")
    parser.add_argument("--head", default="HEAD", help="head revision (default HEAD)")
    parser.add_argument("--pr-body-file", help="file holding the PR description")
    parser.add_argument("--author", help="PR author login (default: $PR_AUTHOR)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--staged", action="store_true", help="check the index")
    modes.add_argument("--agent-hook", action="store_true", help="Claude Code Stop hook")
    modes.add_argument("--list", action="store_true", help="print the coupling table")
    modes.add_argument("--validate", action="store_true", help="check the manifest only")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.agent_hook:
        return run_agent_hook(args.root, args.manifest, sys.stdin.read())

    try:
        root = Path(_git(Path(args.root or os.getcwd()), "rev-parse", "--show-toplevel").strip())
        manifest = _load_manifest(root, args.manifest)
    except GitError as exc:
        print(f"docs-sync: {exc}", file=sys.stderr)
        return 2
    except ManifestError as exc:
        for problem in exc.problems:
            print(f"docs-sync: {args.manifest}: {problem}", file=sys.stderr)
        return 2

    if args.list:
        for c in manifest.couplings:
            print(f"{c.doc}  <-  {', '.join(c.covers)}  [{'/'.join(c.on)}]\n    {c.why}")
        return 0

    author = args.author or os.environ.get("PR_AUTHOR", "")
    if author and author in DEFAULT_EXEMPT_AUTHORS + manifest.exempt_authors:
        print(f"docs-sync: skipped (automated author {author})")
        return 0
    if not (args.validate or args.staged or args.base):
        parser.error("give --base REV, or one of --staged / --agent-hook / --list / --validate")

    try:
        if args.validate:
            report = Report()
            tree = Tree(_paths(_git(root, "ls-files", "-z")))
            _check_manifest(manifest, tree, tree, report)
            print(render_text(report, "enforce"))  # a broken manifest is never report-only
            return 1 if report.violations else 0
        pr_body = ""
        if args.staged:
            ctx = collect_staged(root)
            if ctx is None:
                return 0
        else:
            ctx = collect_range(root, args.base, args.head)
            if args.pr_body_file:
                pr_body = Path(args.pr_body_file).read_text(encoding="utf-8", errors="replace")
            else:
                pr_body = os.environ.get("PR_BODY", "")
        report, manifest = _judge(args.manifest, ctx, manifest, pr_body=pr_body, staged=args.staged)
    except (GitError, OSError) as exc:
        print(f"docs-sync: {exc}", file=sys.stderr)
        return 2

    print(render_text(report, manifest.mode))
    # "report" mode prints the same findings but never fails the job.
    return 1 if report.violations and manifest.mode == "enforce" else 0


if __name__ == "__main__":
    raise SystemExit(main())
