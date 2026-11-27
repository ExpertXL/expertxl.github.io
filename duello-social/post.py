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


def send(channel, text, image_url, due=None, video=None, cover_ms=None):
    service = channel["service"].lower()
    if service == "instagram":
        # links are not clickable in Instagram captions: point to the profile link instead
        text = text.split("\n\n👉")[0] + "\n\n📲 İndirme linki profilde: @duello.game"
    base = {"text": text, "channelId": channel["id"], "schedulingType": "automatic",
            "assets": [{"image": {"url": image_url, "metadata": {"altText": "Düello kelime oyunu"}}}]}
    if video:
        v = {"url": video}
        if cover_ms is not None:
            v["metadata"] = {"thumbnailOffset": cover_ms}
        base["assets"] = [{"video": v}]
    if service == "instagram":
        base["metadata"] = {"instagram": {"type": "reel" if video else "post", "shouldShareToFeed": True}}
    last = None
    # at an exact time when given; otherwise at once, falling back to the next queue slot
    tries = [{"mode": "customScheduled", "dueAt": due}] if due else [{"mode": "shareNow"}, {"mode": "addToQueue"}]
    for extra in tries:
        mode = extra["mode"]
        try:
            res = gql(CREATE, {"input": dict(base, **extra)})["createPost"]
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


SLOTS = [((9, 7), "challenge"), ((13, 13), "duel"), ((19, 11), "yesterday"), ((22, 9), "league")]


def upcoming(now, days=2):
    """The next posting slots, in Istanbul time, at least 10 minutes away."""
    out = []
    for d in range(days):
        day = now.date() + dt.timedelta(days=d)
        for (h, m), kind in SLOTS:
            at = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=TR)
            if at > now + dt.timedelta(minutes=10):
                out.append((day, kind, at))
    return out


def plan_make(out_dir):
    """Images and texts for every upcoming slot not planned yet."""
    os.makedirs(out_dir, exist_ok=True)
    book_path = os.path.join(out_dir, "planned.json")
    book = json.load(open(book_path, encoding="utf-8")) if os.path.exists(book_path) else {}
    todo = {}
    for day, kind, at in upcoming(dt.datetime.now(TR)):
        key = f"{day}-{kind}"
        if key in book:
            continue
        mean = meaning(make_post.daily(day - dt.timedelta(days=1))) if kind == "yesterday" else None
        k = kind if (kind != "yesterday" or mean) else "duel"
        rnd = random.Random(f"{day}-{k}")
        im, text = make_post.make(k, day, rnd, mean)
        name = f"{day}-{k}.png"
        im.save(os.path.join(out_dir, name))
        todo[key] = {"file": name, "text": f"{text}\n\n👉 {STORE}", "at": at.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:00.000Z")}
        print("made", key, at.strftime("%d.%m %H:%M"))
    json.dump(todo, open(os.path.join(out_dir, "todo.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def plan_send(out_dir):
    """Hands the made posts to Buffer with their exact time, and books them so they are never sent twice."""
    todo = json.load(open(os.path.join(out_dir, "todo.json"), encoding="utf-8"))
    book_path = os.path.join(out_dir, "planned.json")
    book = json.load(open(book_path, encoding="utf-8")) if os.path.exists(book_path) else {}
    if not todo:
        print("nothing new to plan")
        return
    chans = channels()
    print("channels:", [(c["service"], c["name"]) for c in chans])
    base_url = os.environ["IMAGE_BASE"].rstrip("/")
    failed = 0
    for key, post in sorted(todo.items(), key=lambda kv: kv[1]["at"]):
        ok = []
        for c in chans:
            try:
                ok.append(c["service"] + ": " + send(c, post["text"], f"{base_url}/{post['file']}", due=post["at"]))
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(key, c["service"], "FAILED:", e)
        print(key, post["at"], ok)
        if ok:
            book[key] = post["at"]
    # keep the book short: drop entries older than a week
    cutoff = (dt.datetime.now(TR).date() - dt.timedelta(days=7)).isoformat()
    book = {k: v for k, v in book.items() if k.startswith("reel-") or k[:10] >= cutoff}
    json.dump(book, open(book_path, "w", encoding="utf-8"), indent=1)
    if failed:
        sys.exit(1)


def send_reels():
    """Instagram Reels from reels/plan.json, each booked once in posts/planned.json."""
    here = os.path.dirname(os.path.abspath(__file__))
    plan = json.load(open(os.path.join(here, "reels", "plan.json"), encoding="utf-8"))
    book_path = os.path.join(here, "posts", "planned.json")
    book = json.load(open(book_path, encoding="utf-8")) if os.path.exists(book_path) else {}
    base = os.environ["IMAGE_BASE"].rsplit("/posts", 1)[0] + "/reels"
    chans = [c for c in channels() if c["service"].lower() == "instagram"]
    now = dt.datetime.now(dt.timezone.utc)
    failed = 0
    for r in plan:
        if r["key"] in book:
            continue
        at = dt.datetime.fromisoformat(r["at"].replace("Z", "+00:00"))
        due = r["at"] if at > now + dt.timedelta(minutes=5) else None
        for c in chans:
            try:
                print(r["key"], "->", send(c, r["text"], None, due=due, video=f"{base}/{r['file']}.mp4", cover_ms=r.get("cover_ms")))
                book[r["key"]] = r["at"]
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(r["key"], "FAILED:", e)
    json.dump(book, open(book_path, "w", encoding="utf-8"), indent=1)
    if failed:
        sys.exit(1)


def main():
    out_dir = os.environ.get("OUT_DIR", "out")
    stage = os.environ.get("STAGE", "make")
    if stage == "make":
        make_stage(out_dir)
    elif stage == "send":
        send_stage(out_dir)
    elif stage == "plan-make":
        plan_make(out_dir)
    elif stage == "plan-send":
        plan_send(out_dir)
    elif stage == "reels":
        send_reels()
    elif stage == "channels":
        for c in channels():
            print(c["service"], c["name"], c["id"])


if __name__ == "__main__":
    main()
