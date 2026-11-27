#!/usr/bin/env python3
"""Make today's Düello post and send it to every connected Buffer channel.

Env:
  STAGE           make (image + text into OUT_DIR) | send (to Buffer) | channels (list them)
  BUFFER_API_KEY  Buffer API key (GitHub secret)
  KIND            challenge | duel | yesterday | league (default: by Istanbul hour)
  OUT_DIR         folder for the images (default: out)
  IMAGE_BASE      public URL of OUT_DIR once pushed
"""
import datetime as dt
import json
import os
import random
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_post  # noqa: E402

API = "https://api.buffer.com"
STORE = "https://play.google.com/store/apps/details?id=com.u1games.duello"
TR = dt.timezone(dt.timedelta(hours=3))


def kind_for(hour):
    if hour < 11:
        return "challenge"
    if hour < 16:
        return "duel"
    if hour < 21:
        return "yesterday"
    return "league"


def meaning(word):
    """First meaning from the TDK dictionary, as the app shows it."""
    try:
        url = "https://sozluk.gov.tr/gts?ara=" + urllib.parse.quote(word)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
        m = data[0]["anlamlarListe"][0]["anlam"]
        return m.replace("&quot;", '"').strip()
    except Exception as e:  # noqa: BLE001
        print("meaning lookup failed:", e)
        return None


def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ["BUFFER_API_KEY"],
    })
    out = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if out.get("errors"):
        raise RuntimeError(json.dumps(out["errors"], ensure_ascii=False))
    return out["data"]


def channels():
    orgs = gql("query { account { organizations { id name } } }")["account"]["organizations"]
    found = []
    for o in orgs:
        q = "query($o: OrganizationId!) { channels(input: { organizationId: $o }) { id name service isDisconnected } }"
        for c in gql(q, {"o": o["id"]})["channels"]:
            if not c.get("isDisconnected"):
                found.append(c)
    return found


CREATE = """
mutation($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id dueAt } }
    ... on MutationError { message }
  }
}"""


def send(channel, text, image_url):
    service = channel["service"].lower()
    if service == "instagram":
        # links are not clickable in Instagram captions: point to the profile link instead
        text = text.split("\n\n👉")[0] + "\n\n📲 İndirme linki profilde: @duello.game"
    base = {"text": text, "channelId": channel["id"], "schedulingType": "automatic",
            "assets": [{"image": {"url": image_url, "metadata": {"altText": "Düello kelime oyunu"}}}]}
    if service == "instagram":
        base["metadata"] = {"instagram": {"type": "post", "shouldShareToFeed": True}}
    last = None
    # post at once; fall back to the next queue slot if this account cannot share now
    for mode in ("shareNow", "addToQueue"):
        try:
            res = gql(CREATE, {"input": dict(base, mode=mode)})["createPost"]
        except RuntimeError as e:
            last = str(e)
            continue
        if res.get("message"):
            last = res["message"]
            continue
        return f"{mode}: {res['post']['id']}"
    raise RuntimeError(last)


def make_stage(out_dir):
    now = dt.datetime.now(TR)
    kind = os.environ.get("KIND") or kind_for(now.hour)
    day = now.date()
    mean = meaning(make_post.daily(day - dt.timedelta(days=1))) if kind == "yesterday" else None
    if kind == "yesterday" and not mean:
        kind = "duel"
    rnd = random.Random(f"{day}-{kind}")
    im, text = make_post.make(kind, day, rnd, mean)
    text = f"{text}\n\n👉 {STORE}"
    name = f"{day}-{kind}.png"
    os.makedirs(out_dir, exist_ok=True)
    im.save(os.path.join(out_dir, name))
    with open(os.path.join(out_dir, "last.json"), "w", encoding="utf-8") as f:
        json.dump({"file": name, "text": text, "kind": kind}, f, ensure_ascii=False)
    print(kind, "|", text)


def send_stage(out_dir):
    last = json.load(open(os.path.join(out_dir, "last.json"), encoding="utf-8"))
    url = os.environ["IMAGE_BASE"].rstrip("/") + "/" + last["file"]
    failed = 0
    chans = channels()
    only = [x.strip().lower() for x in os.environ.get("SERVICES", "").split(",") if x.strip()]
    if only:
        chans = [c for c in chans if c["service"].lower() in only]
    print("channels:", [(c["service"], c["name"]) for c in chans])
    for c in chans:
        try:
            print(c["service"], c["name"], "->", send(c, last["text"], url))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(c["service"], c["name"], "FAILED:", e)
    if failed or not chans:
        sys.exit(1)


def main():
    out_dir = os.environ.get("OUT_DIR", "out")
    stage = os.environ.get("STAGE", "make")
    if stage == "make":
        make_stage(out_dir)
    elif stage == "send":
        send_stage(out_dir)
    elif stage == "channels":
        for c in channels():
            print(c["service"], c["name"], c["id"])


if __name__ == "__main__":
    main()
