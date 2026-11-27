#!/usr/bin/env python3
"""Düello social post generator: makes a 1080x1080 image and the post text.

Kinds:
  challenge  morning: today's word as coloured squares only (never the letters)
  duel       midday: a solved 1v1 board on a random non-daily word, letters shown
  yesterday  evening: yesterday's daily word revealed, with its meaning
  league     night: invite to the monthly league
"""
import datetime as dt
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W = H = 1080
BG, BG2 = (0x3A, 0x1C, 0x6E), (0x26, 0x11, 0x4D)
GREEN, YELLOW, GREY = (0x3F, 0xB2, 0x6A), (0xF2, 0xB5, 0x35), (0x5B, 0x4A, 0x82)
CORAL, SUN, CREAM, MUTED = (0xF2, 0x5C, 0x7A), (0xF7, 0xC9, 0x48), (255, 255, 255), (0xC9, 0xB8, 0xEE)


def font(name, size):
    return ImageFont.truetype(os.path.join(HERE, name), size)


def up(s):
    return s.replace("i", "İ").replace("ı", "I").upper()


def words(path):
    return [w.strip() for w in open(os.path.join(HERE, path), encoding="utf-8") if w.strip()]


ANSWERS = words("answers_tr.txt")
GUESSES = set(words("guesses_tr.txt")) | set(ANSWERS)


def answers(n):
    return [w for w in ANSWERS if len(w) == n]


def daily(day: dt.date):
    """Same rule as the app: Words.daily(date)."""
    l = answers(5)
    e = (day - dt.date(1970, 1, 1)).days
    return l[(e * 7919 + 104729) % len(l)]


def score(guess, answer):
    res = ["x"] * len(guess)
    left = {}
    for i, c in enumerate(guess):
        if c == answer[i]:
            res[i] = "g"
        else:
            left[answer[i]] = left.get(answer[i], 0) + 1
    for i, c in enumerate(guess):
        if res[i] != "g" and left.get(c, 0) > 0:
            res[i] = "y"
            left[c] -= 1
    return res


def solve(answer, rnd, tries=4):
    """A believable sequence of guesses that ends on the answer."""
    pool = [w for w in GUESSES if len(w) == len(answer)]
    rows = []
    for _ in range(tries - 1):
        cand = [w for w in pool if w != answer and all(score(w, answer) == score(w, answer) for _ in [0])]
        best = rnd.sample(cand, min(60, len(cand)))
        best.sort(key=lambda w: -sum(2 if m == "g" else 1 if m == "y" else 0 for m in score(w, answer)))
        pick = best[min(len(rows) * 2 + rnd.randint(0, 3), len(best) - 1)]
        rows.append(pick)
    rows.append(answer)
    return rows


def background():
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(BG[i] + (BG2[i] - BG[i]) * t) for i in range(3)))
    # soft rays behind the emblem
    rays = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rays)
    import math
    cx, cy = W / 2, 150
    for k in range(24):
        a = k * math.pi / 12
        rd.polygon([(cx, cy), (cx + 1600 * math.cos(a - 0.06), cy + 1600 * math.sin(a - 0.06)),
                    (cx + 1600 * math.cos(a + 0.06), cy + 1600 * math.sin(a + 0.06))], fill=(255, 255, 255, 9))
    im.paste(rays, (0, 0), rays)
    return im


def header(im, d):
    em = Image.open(os.path.join(HERE, "emblem.png")).convert("RGBA").resize((170, 170), Image.LANCZOS)
    im.paste(em, (W // 2 - 85, 26), em)
    t = "DÜELLO"
    f = font("baloo2_extrabold.ttf", 66)
    d.text((W / 2, 205), t, font=f, fill=CREAM, anchor="mm")


def centered(d, y, text, f, fill):
    d.text((W / 2, y), text, font=f, fill=fill, anchor="mm")


def grid(im, d, rows, answer, top, letters, cell=None, gap=12):
    n = len(answer)
    cell = cell or min(118, int((W - 160 - gap * (n - 1)) / n))
    total_w = n * cell + (n - 1) * gap
    x0 = (W - total_w) // 2
    f = font("baloo2_extrabold.ttf", int(cell * 0.62))
    for r, word in enumerate(rows):
        marks = score(word, answer)
        for i, m in enumerate(marks):
            x = x0 + i * (cell + gap)
            y = top + r * (cell + gap)
            col = GREEN if m == "g" else YELLOW if m == "y" else GREY
            d.rounded_rectangle([x, y, x + cell, y + cell], radius=int(cell * 0.18), fill=col)
            if letters:
                d.text((x + cell / 2, y + cell / 2 + 4), up(word[i]), font=f, fill=CREAM, anchor="mm")
    return top + len(rows) * (cell + gap)


def pill(d, y, text, fill=CORAL, fg=CREAM):
    f = font("baloo2_extrabold.ttf", 46)
    w = d.textlength(text, font=f) + 90
    d.rounded_rectangle([W / 2 - w / 2, y, W / 2 + w / 2, y + 92], radius=46, fill=fill)
    d.text((W / 2, y + 48), text, font=f, fill=fg, anchor="mm")


def footer(d):
    centered(d, H - 50, "Google Play'de ücretsiz · \"Düello\" ara", font("nunito_extrabold.ttf", 32), MUTED)


def wrap(d, text, f, width):
    out, line = [], ""
    for w in text.split():
        t = (line + " " + w).strip()
        if d.textlength(t, font=f) <= width:
            line = t
        else:
            out.append(line)
            line = w
    if line:
        out.append(line)
    return out


def make(kind, day, rnd, meaning=None):
    im = background()
    d = ImageDraw.Draw(im)
    header(im, d)
    big = font("baloo2_extrabold.ttf", 60)
    mid = font("nunito_extrabold.ttf", 38)
    if kind == "challenge":
        ans = daily(day)
        rows = solve(ans, rnd, rnd.choice([3, 4, 5]))
        centered(d, 290, "Günün kelimesi hazır!", big, SUN)
        centered(d, 350, f"{day.strftime('%d.%m.%Y')} · 5 harf · 6 hak", mid, MUTED)
        end = grid(im, d, rows, ans, 400, letters=False, cell=96)
        pill(d, end + 30, f"Ben {len(rows)} denemede buldum. Ya sen?")
        text = rnd.choice([
            f"Günün kelimesini {len(rows)} denemede buldum 🟩 Sen kaçta bulursun? #Düello #kelimeoyunu",
            f"Bugünün kelimesi seni bekliyor. {len(rows)}/6 ile çözdüm, geçebilir misin? 🟨🟩 #Düello #wordle",
        ])
    elif kind == "duel":
        n = rnd.choice([5, 5, 6, 6, 7])
        today_word = daily(day)
        ans = rnd.choice([w for w in answers(n) if w != today_word])
        rows = solve(ans, rnd, 3 if n >= 6 else rnd.choice([3, 4]))
        centered(d, 290, "Rakibimden önce buldum!", big, SUN)
        centered(d, 350, f"{n} harfli düello · {len(rows)}. hamlede", mid, MUTED)
        end = grid(im, d, rows, ans, 400, letters=True, cell=min(110, int((W - 200) / n) - 12))
        pill(d, end + 30, "Düelloya var mısın? ⚔")
        text = rnd.choice([
            f"{up(ans)} kelimesini rakibimden önce buldum, potu kaptım 💰 Düelloya var mısın? #Düello #kelimeoyunu",
            f"{n} harfli düelloda {len(rows)}. hamlede {up(ans)}! Sıradaki rakip sen ol ⚔ #Düello",
        ])
    elif kind == "yesterday":
        ans = daily(day - dt.timedelta(days=1))
        centered(d, 290, "Dünün kelimesi", big, SUN)
        grid(im, d, [ans], ans, 360, letters=True, cell=118)
        body = font("nunito_extrabold.ttf", 40)
        lines = wrap(d, meaning or "", body, W - 200)[:4]
        y = 540
        for ln in lines:
            centered(d, y, ln, body, CREAM)
            y += 54
        pill(d, max(y + 40, 820), "Bugünkünü sen bul!")
        text = f"Dünün kelimesi: {up(ans)} 📖 Bugünün kelimesi seni bekliyor, kaç denemede bulacaksın? #Düello #TDK"
    else:  # league
        centered(d, 300, "Aylık ligde yerini al!", big, SUN)
        sub = font("nunito_extrabold.ttf", 44)
        for i, ln in enumerate(["Gerçek rakiplerle düello yap,", "kazandığın altınla sıralamada yüksel."]):
            centered(d, 380 + i * 60, ln, sub, CREAM)
        demo = "düello"
        grid(im, d, [demo], demo, 540, letters=True, cell=118)
        pill(d, 760, "Ayın şampiyonu sen ol 🏆", fill=SUN, fg=BG2)
        text = "Bu ayın Düello şampiyonu kim olacak? Gerçek rakiplerle kelime düellosu 🏆 #Düello #kelimeoyunu"
    footer(d)
    return im, text


if __name__ == "__main__":
    kind = sys.argv[1]
    out = sys.argv[2]
    day = dt.date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else dt.date.today()
    meaning = sys.argv[4] if len(sys.argv) > 4 else None
    rnd = random.Random(f"{day}-{kind}")
    im, text = make(kind, day, rnd, meaning)
    im.save(out)
    print(text)
