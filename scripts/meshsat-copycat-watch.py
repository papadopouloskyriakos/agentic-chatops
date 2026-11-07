#!/usr/bin/env python3
"""Watch the meshsat.info copycat and whatever endpoint it delivers from.

Why this exists (MESHSAT-984; enforcement record MESHSAT-689):
meshsat.info advertises, as its "recommended" install path,

    bash <(curl -fsSL https://raw.githubusercontent.com/IngeniiImperator/MeshSat/main/scripts/install.sh)

on a page whose tutorial uses sudo 19 times and targets a freshly imaged
Raspberry Pi. That endpoint returns 404 today, but the account is live and
active. The moment it serves anything, arbitrary code runs as root on machines
whose owners believe they are installing MeshSat.

A blackbox status probe covers the URLs we already know: that is the
ScrapeConfig in namespaces/monitoring/meshsat-copycat-alerts.tf on
nlcl01k8s. This script covers what a status probe cannot, because the
install URL can simply be changed. It re-reads the site, extracts EVERY
fetch-and-execute target it can find wherever it is hosted, resolves each one,
hashes each page, and checks GitHub, GitLab and Codeberg for repositories
carrying our mark under the same handle.

Nothing here assumes GitHub. The forge is not the constant; the handle and the
habit of publishing a one-line installer are.

The first time any extracted URL returns a body, that body is written to
EVIDENCE_DIR. That artifact is what unlocks Google Safe Browsing, the .info
registry (Identity Digital's AUP covers malware distribution) and a report to
whichever forge is hosting it. All of them need a live artifact and none will
act on a 404.

Output: Prometheus textfile-collector gauges, read by node_exporter on
nl-claude01 and scraped by the `chatops-node` job. Atomic write plus
chmod 644, because node_exporter runs as `nobody` and mktemp's 0600 default
silently blackholes the metric.

Read-only against third-party servers: plain GETs with a normal user agent, no
probing, no authentication, one pass per run.
"""

import hashlib
import json
import os
REDACTED_a7b84d63
import sys
import time
import urllib.error
import urllib.request

METRICS = "/var/lib/node_exporter/textfile_collector/meshsat_copycat.prom"
FALLBACK = "/tmp/meshsat_copycat.prom"
STATE = os.path.expanduser("~/.cache/meshsat-copycat-watch/state.json")
EVIDENCE_DIR = os.path.expanduser("~/.cache/meshsat-copycat-watch/evidence")

SITE_PAGES = [
    "https://www.meshsat.info/",
    "https://www.meshsat.info/tutorial",
    "https://www.meshsat.info/hardware",
    "https://www.meshsat.info/countdown",
    "https://www.meshsat.info/credits",
    "https://www.meshsat.info/chat",
]
MARK = "meshsat"
UA = "Mozilla/5.0 (X11; Linux x86_64) meshsat-copycat-watch/1.0"
TIMEOUT = 25

URL_RE = re.compile(r"""https?://[^\s"'<>()\\]+""")
# Fetch-and-execute shapes: curl/wget targets, git clone targets, and the
# process-substitution form the site actually uses today.
EXEC_CTX_RE = re.compile(
    r"""(?:curl|wget|git\s+clone|bash\s*<\(|sh\s*<\()[^\n]{0,400}""",
    re.IGNORECASE,
)

# Which extracted URLs could carry a payload they chose.
#
# This is an ALLOWLIST OF KNOWN-BENIGN UPSTREAMS, deliberately not a list of
# hosts we think they own. An earlier version had it the other way round and it
# was wrong: it hardcoded github.com/<their account>, so the day they moved the
# installer to GitLab, Codeberg, a paste site or their own domain, the new URL
# would still have been extracted but would no longer have counted as theirs,
# and the paging alert would have gone quiet at exactly the wrong moment.
#
# So the default is suspicion. Anything fetch-and-execute that is NOT a
# recognised third-party upstream counts as suspect, wherever it is hosted. The
# cost of that choice is the occasional false page when their tutorial adds a
# new legitimate dependency; the fix is to add it below. That is the right
# direction to fail in.
#
# The entries here are the legitimate upstreams their tutorial already cites.
BENIGN_PREFIXES = (
    "https://download.opensuse.org/",
    "https://github.com/la5nta/pat/",
    "https://github.com/meshtastic/",
    "https://get.docker.com",
    "https://download.docker.com/",
    "https://deb.debian.org/",
    "https://archive.raspberrypi.",
)

# Forges where the same handle would let them publish a replacement payload.
# Add to this rather than assuming GitHub: the handle is the constant, the forge
# is not. Confirmed 2026-09-08 that the handle exists on GitHub AND GitLab.
#
# GitLab needs two calls. /api/v4/users/<username>/projects answers 200 with an
# EMPTY LIST for a real account, so an earlier version of this check silently
# reported nothing for every GitLab user including our own. The username has to
# be resolved to a numeric id first. A quiet 200 [] is the worst possible
# failure for a watch like this, because it is indistinguishable from "nothing
# to see".
ACCOUNT = "IngeniiImperator"


def is_benign(url):
    """True only for recognised third-party upstreams. Everything else is suspect."""
    return url.lower().startswith(tuple(p.lower() for p in BENIGN_PREFIXES))


def get(url, want_body=True):
    """Return (status, body_bytes). Never raises on an HTTP error."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, (r.read() if want_body else b"")
    except urllib.error.HTTPError as e:
        try:
            body = e.read() if want_body else b""
        except Exception:
            body = b""
        return e.code, body
    except Exception:
        return 0, b""


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1, sort_keys=True)
    os.replace(tmp, STATE)


def keep_evidence(url, body):
    """Persist the first body ever seen at a URL that used to serve nothing."""
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    slug = re.sub(r"[^A-Za-z0-9]+", "-", url)[:120].strip("-")
    path = os.path.join(EVIDENCE_DIR, f"{stamp}_{slug}")
    with open(path, "wb") as f:
        f.write(body)
    return path


def main():
    st = load_state()
    now = int(time.time())
    prev_urls = set(st.get("exec_urls", []))
    prev_hashes = st.get("page_hashes", {})
    prev_repos = set(st.get("mark_repos", []))

    exec_urls, page_hashes = set(), {}
    pages_changed = pages_reachable = 0

    for page in SITE_PAGES:
        status, body = get(page)
        if status != 200 or not body:
            continue
        pages_reachable += 1
        text = body.decode("utf-8", "replace")
        digest = hashlib.sha256(body).hexdigest()
        page_hashes[page] = digest
        if page in prev_hashes and prev_hashes[page] != digest:
            pages_changed += 1
        for ctx in EXEC_CTX_RE.findall(text):
            for u in URL_RE.findall(ctx):
                exec_urls.add(u.rstrip(".,;:)\"'"))

    # Resolve every extracted target. A body served from anything that is not a
    # recognised third-party upstream is the event that matters, wherever it is
    # hosted.
    live = suspect_live = 0
    evidence = []
    seen_evidence = st.get("evidence", {})
    for u in sorted(exec_urls):
        status, body = get(u)
        if status == 200 and body:
            live += 1
            if not is_benign(u):
                suspect_live += 1
                if not seen_evidence.get(u):
                    evidence.append((u, keep_evidence(u, body)))

    # Repositories carrying our mark under the same handle on each forge they
    # could plausibly move to.
    mark_repos, forges_ok = set(), 0

    def listing(url):
        status, body = get(url)
        if status != 200 or not body:
            return None
        try:
            return json.loads(body)
        except Exception:
            return None

    # GitHub
    repos = listing(f"https://api.github.com/users/{ACCOUNT}/repos?per_page=100")
    if repos is not None:
        forges_ok += 1
        for r in repos:
            if MARK in (r.get("name") or "").lower():
                mark_repos.add("github:" + r.get("full_name", ""))

    # GitLab: resolve the username to an id first, see the note above.
    users = listing(f"https://gitlab.com/api/v4/users?username={ACCOUNT}")
    if users is not None:
        forges_ok += 1
        for u in users:
            projs = listing(
                f"https://gitlab.com/api/v4/users/{u['id']}/projects?per_page=100")
            for r in projs or []:
                if MARK in (r.get("path") or r.get("name") or "").lower():
                    mark_repos.add("gitlab:" + r.get("path_with_namespace", ""))

    # Codeberg (Gitea): 404 for an unknown handle, which is the normal case.
    repos = listing(f"https://codeberg.org/api/v1/users/{ACCOUNT}/repos?limit=50")
    if repos is not None:
        forges_ok += 1
        for r in repos:
            if MARK in (r.get("name") or "").lower():
                mark_repos.add("codeberg:" + r.get("full_name", ""))

    # First run, or state lost: there is no baseline, so everything looks new.
    # Reporting that would fire the "new exec URL" and "new repo" alerts on
    # deployment and on every state reset, which is noise indistinguishable from
    # a real change. Seed silently instead; the next run has a baseline.
    seeding = not st
    new_urls = set() if seeding else exec_urls - prev_urls
    new_repos = set() if seeding else mark_repos - prev_repos

    lines = [
        "# HELP meshsat_copycat_exec_urls Fetch-and-execute URLs advertised on the copycat site",
        "# TYPE meshsat_copycat_exec_urls gauge",
        f"meshsat_copycat_exec_urls {len(exec_urls)}",
        "# HELP meshsat_copycat_exec_urls_new Extracted exec URLs not seen on the previous run",
        "# TYPE meshsat_copycat_exec_urls_new gauge",
        f"meshsat_copycat_exec_urls_new {len(new_urls)}",
        "# HELP meshsat_copycat_exec_urls_live Extracted exec URLs currently serving a body (includes third-party artefacts, informational only)",
        "# TYPE meshsat_copycat_exec_urls_live gauge",
        f"meshsat_copycat_exec_urls_live {live}",
        "# HELP meshsat_copycat_suspect_urls_live Exec URLs that are NOT recognised third-party upstreams and are serving a body, on any host. THIS is the paging signal.",
        "# TYPE meshsat_copycat_suspect_urls_live gauge",
        f"meshsat_copycat_suspect_urls_live {suspect_live}",
        "# HELP meshsat_copycat_suspect_urls Exec URLs that are NOT recognised third-party upstreams, on any host",
        "# TYPE meshsat_copycat_suspect_urls gauge",
        f"meshsat_copycat_suspect_urls {sum(1 for u in exec_urls if not is_benign(u))}",
        "# HELP meshsat_copycat_pages_reachable Copycat pages that returned 200",
        "# TYPE meshsat_copycat_pages_reachable gauge",
        f"meshsat_copycat_pages_reachable {pages_reachable}",
        "# HELP meshsat_copycat_pages_changed Copycat pages whose body hash changed since the previous run",
        "# TYPE meshsat_copycat_pages_changed gauge",
        f"meshsat_copycat_pages_changed {pages_changed}",
        "# HELP meshsat_copycat_mark_repos Public repos on the copycat GitHub account whose name carries our mark",
        "# TYPE meshsat_copycat_mark_repos gauge",
        f"meshsat_copycat_mark_repos {len(mark_repos)}",
        "# HELP meshsat_copycat_mark_repos_new Such repos not seen on the previous run",
        "# TYPE meshsat_copycat_mark_repos_new gauge",
        f"meshsat_copycat_mark_repos_new {len(new_repos)}",
        "# HELP meshsat_copycat_forges_ok Forge repo listings that responded (github, gitlab, codeberg)",
        "# TYPE meshsat_copycat_forges_ok gauge",
        f"meshsat_copycat_forges_ok {forges_ok}",
        "# HELP meshsat_copycat_last_run_timestamp_seconds Unix time of the last completed run",
        "# TYPE meshsat_copycat_last_run_timestamp_seconds gauge",
        f"meshsat_copycat_last_run_timestamp_seconds {now}",
    ]

    target = METRICS if os.access(os.path.dirname(METRICS), os.W_OK) else FALLBACK
    tmp = target + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, target)
    os.chmod(target, 0o644)

    ev = dict(seen_evidence)
    for u, path in evidence:
        ev[u] = path
    save_state({
        "exec_urls": sorted(exec_urls),
        "page_hashes": page_hashes,
        "mark_repos": sorted(mark_repos),
        "evidence": ev,
        "last_run": now,
    })

    for u in sorted(new_urls):
        print(f"NEW EXEC URL: {u}", file=sys.stderr)
    for u, path in evidence:
        print(f"PAYLOAD CAPTURED: {u} -> {path}", file=sys.stderr)
    for r in sorted(new_repos):
        print(f"NEW REPO WITH MARK: {r}", file=sys.stderr)


if __name__ == "__main__":
    main()
