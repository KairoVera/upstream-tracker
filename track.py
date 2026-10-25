#!/usr/bin/env python3
"""Upstream tracker: detect tip changes on EVERY branch of the tracked
upstreams + push a signed Feishu card on change + optionally re-sync a GitHub
mirror. State (branch->tip) persists in state.json (committed back by the
workflow). First run only records tips (no notify).

All branches are discovered dynamically via `git ls-remote --heads`, so new
upstream branches are picked up automatically and deleted ones are reported.
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
        print("CMD FAIL:", a, r.stderr[:300], file=sys.stderr)
    return r


def all_tips(url):
    """{branch: tip_sha} for every branch on url (discovered dynamically)."""
    r = sh("git", "ls-remote", "--heads", url)
    out = {}
    if r.returncode:
        return out
    for line in r.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            out[parts[1].replace("refs/heads/", "")] = parts[0]
    return out


def recent(url, branch, n=4):
    d = "/tmp/trk-" + branch.replace("/", "_")
    sh("rm", "-rf", d)
    sh("git", "init", "-q", d)
    sh("git", "-C", d, "remote", "add", "up", url)
    if sh("git", "-C", d, "fetch", "-q", "--depth", str(n), "up",
          "refs/heads/%s:refs/tags/_t" % branch).returncode:
        return []
    return sh("git", "-C", d, "log", "--oneline", "-n", str(n), "_t").stdout.strip().splitlines()


def sign(ts):
    s = ("%s\n%s" % (ts, SECRET)).encode()
    return base64.b64encode(hmac.new(s, digestmod=hashlib.sha256).digest()).decode()


def notify(title, text):
    if not WEBHOOK:
        print("no FEISHU_WEBHOOK; skipping")
        return
    ts = str(int(time.time()))
    body = {"msg_type": "text", "content": {"text": title + "\n" + text},
            "timestamp": ts, "sign": sign(ts)}
    req = urllib.request.Request(WEBHOOK, data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    print("feishu resp:", urllib.request.urlopen(req, timeout=30).read().decode()[:200])


def re_mirror(up):
    mir = up["mirror"]
    target = "https://x-access-token:%s@github.com/%s.git" % (MTOKEN, mir["repo"])
    d = "/tmp/mir-" + up["id"]
    sh("rm", "-rf", d)
    if sh("git", "clone", "-q", up["url"], d).returncode:
        print("mirror clone failed:", up["id"], file=sys.stderr)
        return
    for bn in [b.replace("origin/", "") for b in sh("git", "-C", d, "branch", "-r")
               .stdout.split() if "HEAD" not in b]:
        sh("git", "-C", d, "push", "-q", "--force", target,
           "refs/remotes/origin/%s:refs/heads/%s" % (bn, bn))
    sh("git", "-C", d, "push", "-q", "--tags", "--force", target)
    print("mirror re-synced:", mir["repo"])


first_run = not state["tips"]
changes = []
deleted = []
for up in CFG["upstreams"]:
    tips = all_tips(up["url"])
    if not tips:
        print("no branches:", up["id"], file=sys.stderr)
        continue
    for br, tip in tips.items():
        key = up["id"] + "::" + br
        old = state["tips"].get(key)
        state["tips"][key] = tip
        if old and old != tip:
            changes.append({"up": up, "br": br, "old": old, "new": tip,
                           "recent": recent(up["url"], br)})
        elif old is None and not first_run:
            changes.append({"up": up, "br": br, "old": None, "new": tip,
                           "recent": recent(up["url"], br)})
    for key in list(state["tips"].keys()):
        owner, br = key.split("::", 1)
        if owner == up["id"] and br not in tips:
            del state["tips"][key]
            deleted.append((up, br))
    if up.get("mirror") and MTOKEN and any(c["up"]["id"] == up["id"] for c in changes):
        re_mirror(up)
    elif up.get("mirror") and not MTOKEN and any(c["up"]["id"] == up["id"] for c in changes):
        print("%s changed but MIRROR_TOKEN unset; skip re-sync" % up["id"], file=sys.stderr)

lines = []
for c in changes[:20]:
    up = c["up"]
    arrow = "NEW branch" if c["old"] is None else ("%s → %s" % (c["old"][:9], c["new"][:9]))
    lines.append("\U0001F514 %s \u00b7 %s\n  %s" % (up["name"], c["br"], arrow))
    for l in c["recent"][:3]:
        p = l.split(" ", 1)
        lines[-1] += "\n   \u2022 " + (p[1] if len(p) > 1 else p[0])
if len(changes) > 20:
    lines.append("   \u2026 +%d more" % (len(changes) - 20))
for up, br in deleted[:10]:
    lines.append("\U0001F7E1 branch deleted: %s \u00b7 %s" % (up["name"], br))

if lines:
    notify("\U0001F4DC \u4e0a\u6e38\u53d8\u52a8 (upstream-tracker, all branches)", "\n\n".join(lines))
    print("notified %d change(s), %d deleted" % (len(changes), len(deleted)))
elif first_run:
    print("first run: recorded %d tips, no notify" % len(state["tips"]))

json.dump(state, open("state.json", "w"), indent=2)
print("state updated (%d tips)" % len(state["tips"]))
