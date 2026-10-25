#!/usr/bin/env python3
"""Upstream tracker: detect tip changes on tracked branches + push a signed
Feishu card on change + (optionally) re-sync a GitHub mirror.

State is kept in state.json (committed back by the workflow). First run only
records tips (no notify) so we don't spam an initial dump.
"""
import json, os, sys, subprocess, time, hmac, hashlib, base64, urllib.request

CFG = json.load(open("upstreams.json"))
state = json.load(open("state.json"))
state.setdefault("tips", {})
WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
SECRET = os.environ.get("FEISHU_SECRET", "")
MTOKEN = os.environ.get("MIRROR_TOKEN", "")


def sh(*a, check=False):
    r = subprocess.run(a, capture_output=True, text=True)
    if check and r.returncode:
        print("CMD FAIL:", a, r.stderr[:400], file=sys.stderr)
    return r


def lsremote(url, ref):
    """Return the tip SHA of ref on url, or None."""
    r = sh("git", "ls-remote", url, ref)
    if r.returncode:
        return None
    for line in r.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[1] == ref:
            return parts[0]
    return None


def recent(url, branch, n=6):
    """Shallow-fetch the branch tip + return the last N oneline subjects."""
    d = "/tmp/trk-" + branch.replace("/", "_")
    sh("rm", "-rf", d)
    sh("git", "init", "-q", d)
    sh("git", "-C", d, "remote", "add", "up", url)
    r = sh("git", "-C", d, "fetch", "-q", "--depth", str(n), "up",
           f"refs/heads/{branch}:refs/tags/_t")
    if r.returncode:
        return []
    log = sh("git", "-C", d, "log", "--oneline", "-n", str(n), "_t").stdout.strip()
    return log.splitlines()


def sign(ts):
    s = ("%s\n%s" % (ts, SECRET)).encode()
    return base64.b64encode(hmac.new(s, digestmod=hashlib.sha256).digest()).decode()


def notify(title, text):
    if not WEBHOOK:
        print("no FEISHU_WEBHOOK set; skipping notify")
        return
    ts = str(int(time.time()))
    body = {"msg_type": "text", "content": {"text": title + "\n" + text},
            "timestamp": ts, "sign": sign(ts)}
    req = urllib.request.Request(WEBHOOK, data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=30).read().decode()
    print("feishu resp:", resp[:200])


def re_mirror(up):
    """Re-push all heads + tags of up's source to its GitHub mirror (needs MTOKEN)."""
    mir = up["mirror"]
    target = "https://x-access-token:%s@github.com/%s.git" % (MTOKEN, mir["repo"])
    d = "/tmp/mir-" + up["id"]
    sh("rm", "-rf", d)
    if sh("git", "clone", "-q", up["url"], d).returncode:
        print("mirror clone failed for", up["id"], file=sys.stderr)
        return
    heads = [b.replace("origin/", "") for b in sh("git", "-C", d, "branch", "-r")
             .stdout.split() if "HEAD" not in b]
    for bn in heads:
        sh("git", "-C", d, "push", "-q", "--force", target,
           "refs/remotes/origin/%s:refs/heads/%s" % (bn, bn))
    sh("git", "-C", d, "push", "-q", "--tags", "--force", target)
    print("mirror re-synced:", mir["repo"])


changes = []
first_run = not state["tips"]
for up in CFG["upstreams"]:
    for br in up["branches"]:
        new = lsremote(up["url"], "refs/heads/" + br)
        if not new:
            print("no ref %s:%s" % (up["id"], br), file=sys.stderr)
            continue
        key = up["id"] + "::" + br
        old = state["tips"].get(key)
        state["tips"][key] = new
        if old and old != new:
            changes.append({"up": up, "br": br, "old": old, "new": new,
                           "recent": recent(up["url"], br)})

lines = []
for c in changes:
    up = c["up"]
    head = "\U0001F514 %s \u00b7 %s\n  %s \u2192 %s" % (up["name"], c["br"], c["old"][:9], c["new"][:9])
    for l in c["recent"][:5]:
        sha, subject = (l.split(" ", 1) + [""])[:2]
        head += "\n   \u2022 %s %s" % (sha, subject)
    lines.append(head)
    if up.get("mirror") and MTOKEN:
        re_mirror(up)
    elif up.get("mirror") and not MTOKEN:
        print("SUSFS changed but MIRROR_TOKEN not set; skipping mirror re-sync", file=sys.stderr)

if lines:
    notify("\U0001F4DC \u4e0a\u6e38\u53d8\u52a8 (upstream-tracker hourly)", "\n\n".join(lines))
    print("notified", len(lines), "change(s)")
elif first_run:
    print("first run: recorded %d tips, no notify" % len(state["tips"]))

json.dump(state, open("state.json", "w"), indent=2)
print("state updated (%d tips)" % len(state["tips"]))
