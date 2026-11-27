#!/usr/bin/env python3
"""Düello Instagram Reels: 1080x1920, 30 fps, drawn frame by frame with PIL and piped to ffmpeg.

  python3 reels.py preview          key frames -> /tmp/reels_preview/*.png
  python3 reels.py render NAME OUT  one finished reel (with sound)
"""
import math
import os
import random
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw

import make_post as mp

W, H, FPS = 1080, 1920, 30
BG, BG2 = mp.BG, mp.BG2
GREEN, YELLOW, GREY, CORAL, SUN, CREAM, MUTED = mp.GREEN, mp.YELLOW, mp.GREY, mp.CORAL, mp.SUN, mp.CREAM, mp.MUTED
EMPTY = (0x4A, 0x2D, 0x85)
F = mp.font
UP = mp.up
EMBLEM = Image.open(os.path.join(mp.HERE, "emblem.png")).convert("RGBA")


def ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def back(x):
    x = max(0.0, min(1.0, x))
    c = 1.7
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def seg(t, a, b):
    return 0.0 if t <= a else 1.0 if t >= b else (t - a) / (b - a)


_bg = None


def background():
    global _bg
    if _bg is None:
        im = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(im)
        for y in range(H):
            k = y / H
            d.line([(0, y), (W, y)], fill=tuple(int(BG[i] + (BG2[i] - BG[i]) * k) for i in range(3)))
        _bg = im
    return _bg.copy()


def rays(im, cx, cy, t, alpha=10):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for k in range(20):
        a = k * math.pi / 10 + t * 0.25
        d.polygon([(cx, cy), (cx + 2400 * math.cos(a - 0.07), cy + 2400 * math.sin(a - 0.07)),
                   (cx + 2400 * math.cos(a + 0.07), cy + 2400 * math.sin(a + 0.07))], fill=(255, 255, 255, alpha))
    im.paste(lay, (0, 0), lay)


def text(d, xy, s, f, fill, anchor="mm"):
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


def scaled_text(im, xy, s, size, fill, scale=1.0, fontname="baloo2_extrabold.ttf", alpha=1.0):
    if scale <= 0.01 or alpha <= 0.01:
        return
    f = F(fontname, max(4, int(size * scale)))
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(lay).text(xy, s, font=f, fill=fill + (int(255 * alpha),), anchor="mm")
    im.paste(lay, (0, 0), lay)


def tile(d, x, y, size, color, letter=None, flip=1.0, f=None):
    """A tile; flip < 1 squashes it vertically (the turn-over)."""
    h = size * abs(math.cos(math.pi * (1 - flip))) if flip < 1 else size
    h = max(2, h)
    top = y + (size - h) / 2
    d.rounded_rectangle([x, top, x + size, top + h], radius=int(size * 0.17), fill=color)
    if letter and h > size * 0.4:
        text(d, (x + size / 2, top + h / 2 + size * 0.03), UP(letter), f, CREAM)


def board(d, rows, answer, n_rows, x0, y0, size, gap, t_rows, typing_letters=None):
    """rows: guesses; t_rows[i] = progress 0..1 of row i's colour flip; typing_letters: partial current row."""
    n = len(answer)
    f = F("baloo2_extrabold.ttf", int(size * 0.6))
    for r in range(n_rows):
        for i in range(n):
            x = x0 + i * (size + gap)
            y = y0 + r * (size + gap)
            if r < len(rows):
                word = rows[r]
                p = t_rows[r]
                marks = mp.score(word, answer)
                # each tile flips a little after the one before it
                q = seg(p, i * 0.12, i * 0.12 + 0.4)
                if q <= 0:
                    tile(d, x, y, size, EMPTY, word[i], f=f)
                    d.rounded_rectangle([x, y, x + size, y + size], radius=int(size * 0.17), outline=(0x8B, 0x6C, 0xD0), width=4)
                else:
                    col = GREEN if marks[i] == "g" else YELLOW if marks[i] == "y" else GREY
                    tile(d, x, y, size, col if q > 0.5 else EMPTY, word[i], flip=q, f=f)
            elif r == len(rows) and typing_letters:
                tile(d, x, y, size, EMPTY, typing_letters[i] if i < len(typing_letters) else None, f=f)
                if i < len(typing_letters):
                    d.rounded_rectangle([x, y, x + size, y + size], radius=int(size * 0.17), outline=(0x8B, 0x6C, 0xD0), width=4)
            else:
                d.rounded_rectangle([x, y, x + size, y + size], radius=int(size * 0.17), fill=(0x33, 0x1A, 0x63))


def pill(im, cy, s, fill=CORAL, fg=CREAM, size=58, scale=1.0):
    if scale <= 0.02:
        return
    f = F("baloo2_extrabold.ttf", int(size * scale))
    d = ImageDraw.Draw(im)
    w = d.textlength(s, font=f) + 110 * scale
    h = size * 1.9 * scale
    d.rounded_rectangle([W / 2 - w / 2, cy - h / 2 + 10 * scale, W / 2 + w / 2, cy + h / 2 + 10 * scale], radius=int(h / 2), fill=tuple(max(0, c - 50) for c in fill))
    d.rounded_rectangle([W / 2 - w / 2, cy - h / 2, W / 2 + w / 2, cy + h / 2], radius=int(h / 2), fill=fill)
    text(d, (W / 2, cy + 4 * scale), s, f, fg)


def emblem(im, cx, cy, size, rot=0.0):
    if size < 4:
        return
    e = EMBLEM.resize((int(size), int(size)), Image.LANCZOS)
    if rot:
        e = e.rotate(rot, resample=Image.BICUBIC)
    im.paste(e, (int(cx - size / 2), int(cy - size / 2)), e)


def end_card(im, t, line):
    """Shared closing card, t from 0."""
    rays(im, W / 2, 700, t, 14)
    s = back(seg(t, 0, 0.5))
    emblem(im, W / 2, 700, 520 * s, rot=(1 - s) * -20)
    scaled_text(im, (W / 2, 1060), "DÜELLO", 150, CREAM, back(seg(t, 0.2, 0.7)))
    scaled_text(im, (W / 2, 1190), line, 56, SUN, 1, "nunito_extrabold.ttf", seg(t, 0.4, 0.8))
    pill(im, 1400, "Google Play'de ücretsiz", fill=GREEN, scale=back(seg(t, 0.6, 1.1)))
    scaled_text(im, (W / 2, 1560), "Ara: \"Düello\"", 50, MUTED, 1, "nunito_extrabold.ttf", seg(t, 0.9, 1.3))


# ---------------------------------------------------------------- reel 1: how many tries?
R1_ANSWER = "kalem"
R1_ROWS = ["deniz", "masal", "kelam", "kalem"]
R1_LEN = 14.0


def reel1(t):
    im = background()
    d = ImageDraw.Draw(im)
    rows_t = 1.6
    per = 2.0
    size, gap = 150, 18
    x0 = (W - (5 * size + 4 * gap)) / 2
    if t < 10.6:
        rays(im, W / 2, 300, t, 7)
        k = back(seg(t, 0, 0.5))
        scaled_text(im, (W / 2, 250), "KAÇ DENEMEDE", 96, CREAM, k)
        scaled_text(im, (W / 2, 355), "BULURSUN?", 120, SUN, back(seg(t, 0.25, 0.75)))
        scaled_text(im, (W / 2, 460), "5 harf · 6 hak", 48, MUTED, 1, "nunito_extrabold.ttf", seg(t, 0.5, 1.0))
        done, typing, prog = [], None, []
        for r, w in enumerate(R1_ROWS):
            a = rows_t + r * per
            if t >= a:
                ty = seg(t, a, a + 0.9)
                letters = w[: int(ty * 5 + 0.001)]
                if ty < 1:
                    typing = letters
                    break
                done.append(w)
                prog.append(seg(t, a + 0.95, a + 1.75))
        board(d, done, R1_ANSWER, 6, x0, 560, size, gap, prog, typing)
        # tries counter
        n = len([p for p in prog if p > 0.9])
        if n:
            scaled_text(im, (W / 2, 1640), f"{n}. deneme", 64, CREAM, 1, "nunito_extrabold.ttf")
        win = seg(t, rows_t + 3 * per + 1.8, rows_t + 3 * per + 2.4)
        if win > 0:
            pill(im, 1520, "4 denemede buldum! Ya sen?", fill=CORAL, scale=back(win))
    else:
        end_card(im, t - 10.6, "Kelime bulmacası, ama 1'e 1!")
    return im


# ---------------------------------------------------------------- reel 2: 1v1 duel race
R2_ANSWER = "şöhret"
R2_ROWS = [("sen", "kartal"), ("rakip", "mesele"), ("sen", "şehrin"), ("rakip", "şöhret")]
R2_ROWS = [("sen", "kartal"), ("rakip", "metres"), ("sen", "şahane"), ("rakip", "şerbet"), ("sen", "şöhret")]
R2_LEN = 15.0


def avatar(d, cx, cy, s, letter, col, active):
    if active:
        d.rounded_rectangle([cx - s / 2 - 8, cy - s / 2 - 8, cx + s / 2 + 8, cy + s / 2 + 8], radius=int(s * 0.32), outline=SUN, width=8)
    d.rounded_rectangle([cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2], radius=int(s * 0.28), fill=col)
    text(d, (cx, cy + 6), letter, F("baloo2_extrabold.ttf", int(s * 0.62)), CREAM)


def coin(d, cx, cy, r):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0xD9, 0x9A, 0x1C))
    d.ellipse([cx - r * 0.82, cy - r * 0.82, cx + r * 0.82, cy + r * 0.82], fill=SUN)
    text(d, (cx, cy + r * 0.08), "D", F("baloo2_extrabold.ttf", int(r * 1.1)), (0xB0, 0x6A, 0x00))


def reel2(t):
    im = background()
    d = ImageDraw.Draw(im)
    if t >= 11.8:
        end_card(im, t - 11.8, "Rakibinden önce bul, potu kap!")
        return im
    rays(im, W / 2, 230, t, 6)
    scaled_text(im, (W / 2, 150), "1'E 1 KELİME DÜELLOSU", 74, SUN, back(seg(t, 0, 0.5)))
    # players
    per, start = 1.7, 1.4
    turn = int(max(0, t - start) // per) % 2
    avatar(d, 230, 330, 150, "S", CORAL, turn == 0 and t < 10)
    avatar(d, W - 230, 330, 150, "R", (0x5A, 0xA9, 0xFF), turn == 1 and t < 10)
    text(d, (230, 450), "Sen", F("nunito_extrabold.ttf", 44), CREAM)
    text(d, (W - 230, 450), "Rakip", F("nunito_extrabold.ttf", 44), CREAM)
    # pot, doubled at 6.2s
    dbl = seg(t, 6.0, 6.6)
    pot = 600 if dbl < 0.5 else 1200
    s = 1 + 0.35 * math.sin(math.pi * dbl)
    d.rounded_rectangle([W / 2 - 150, 280, W / 2 + 150, 380], radius=50, fill=(0x26, 0x11, 0x4D))
    coin(d, W / 2 - 85, 330, 30)
    scaled_text(im, (W / 2 + 30, 334), f"{pot:,}".replace(",", "."), 60, SUN, s)
    if 6.0 <= t < 7.6:
        pill(im, 520, "x2 KATLADI!", fill=SUN, fg=BG2, scale=back(seg(t, 6.0, 6.4)) * (1 - seg(t, 7.3, 7.6)))
    # board: rows alternate players, outlined by owner colour
    size, gap = 130, 16
    n = 6
    x0 = (W - (n * size + (n - 1) * gap)) / 2
    y0 = 620
    done, prog = [], []
    for r, (who, w) in enumerate(R2_ROWS):
        a = start + r * per
        if t >= a + 0.6:
            done.append(w)
            prog.append(seg(t, a + 0.6, a + 1.3))
    board(d, done, R2_ANSWER, 7, x0, y0, size, gap, prog)
    for r, (who, w) in enumerate(R2_ROWS[: len(done)]):
        y = y0 + r * (size + gap) + size / 2
        col = CORAL if who == "sen" else (0x5A, 0xA9, 0xFF)
        d.rounded_rectangle([x0 - 46, y - 30, x0 - 18, y + 30], radius=12, fill=col)
    # timer bar
    if t < 9.9:
        tl = 1 - ((t - start) % per) / per if t > start else 1
        d.rounded_rectangle([140, 1680, W - 140, 1710], radius=15, fill=(0x33, 0x1A, 0x63))
        d.rounded_rectangle([140, 1680, 140 + (W - 280) * tl, 1710], radius=15, fill=GREEN if tl > 0.35 else CORAL)
    win = seg(t, 10.0, 10.5)
    if win > 0:
        pill(im, 1760, "KAZANDIN! +1.200 altın", fill=GREEN, scale=back(win))
        # coins flying to the player
        rnd = random.Random(3)
        for k in range(14):
            q = seg(t, 10.2 + k * 0.05, 11.0 + k * 0.05)
            if 0 < q < 1:
                sx, sy = W / 2 + rnd.uniform(-120, 120), 330
                cx = sx + (230 - sx) * ease(q)
                cy = sy - 160 * math.sin(math.pi * q) + (330 - sy) * q
                coin(d, cx, cy, 26)
    return im


# ---------------------------------------------------------------- reel 3: can you find it?
R3_ANSWER = "bahar"
R3_ROWS = ["kalem", "sabah"]
R3_MEANING = "İlkbahar; kış ile yaz arasındaki mevsim"
R3_LEN = 13.0


def reel3(t):
    im = background()
    d = ImageDraw.Draw(im)
    if t >= 9.6:
        end_card(im, t - 9.6, "Her gün yeni bir kelime")
        return im
    rays(im, W / 2, 300, t, 7)
    scaled_text(im, (W / 2, 240), "BU KELİMEYİ", 100, CREAM, back(seg(t, 0, 0.5)))
    scaled_text(im, (W / 2, 350), "BULABİLİR MİSİN?", 100, SUN, back(seg(t, 0.25, 0.75)))
    size, gap = 150, 18
    x0 = (W - (5 * size + 4 * gap)) / 2
    prog = [seg(t, 0.8, 1.6), seg(t, 1.2, 2.0)]
    reveal = seg(t, 7.0, 7.8)
    rows = list(R3_ROWS) + (["bahar"] if reveal > 0 else [])
    if reveal > 0:
        prog.append(reveal)
    board(d, rows, R3_ANSWER, 3, x0, 520, size, gap, prog)
    # hint and countdown
    if t < 7.0:
        scaled_text(im, (W / 2, 1110), "İpucu: bir mevsim", 54, MUTED, 1, "nunito_extrabold.ttf", seg(t, 2.0, 2.5))
        left = 5 - int(max(0.0, t - 2.0))
        if 2.0 <= t < 7.0:
            ph = (t - 2.0) % 1.0
            scaled_text(im, (W / 2, 1400), str(left), 300, CORAL if left <= 2 else SUN, 1.25 - 0.25 * ease(ph * 2), alpha=1 - seg(ph, 0.75, 1.0))
            scaled_text(im, (W / 2, 1640), "Yorumlara yaz!", 60, CREAM, 1, "nunito_extrabold.ttf")
    else:
        scaled_text(im, (W / 2, 1150), "BAHAR", 130, GREEN, back(seg(t, 7.6, 8.1)))
        lines = mp.wrap(d, R3_MEANING, F("nunito_extrabold.ttf", 50), W - 220)
        for i, ln in enumerate(lines):
            scaled_text(im, (W / 2, 1290 + i * 66), ln, 50, CREAM, 1, "nunito_extrabold.ttf", seg(t, 8.0, 8.5))
        pill(im, 1560, "Bildin mi?", fill=CORAL, scale=back(seg(t, 8.4, 8.9)))
    return im


REELS = {"kac-deneme": (reel1, R1_LEN), "duello": (reel2, R2_LEN), "bulabilir-misin": (reel3, R3_LEN)}


# ---------------------------------------------------------------- sound: small synthesized effects, no music rights needed
SR = 44100


def tone(freq, dur, vol=0.3, decay=8.0, kind="sine"):
    n = int(SR * dur)
    tt = np.arange(n) / SR
    if kind == "sine":
        w = np.sin(2 * np.pi * freq * tt)
    else:
        w = np.sign(np.sin(2 * np.pi * freq * tt)) * 0.5
    return (w * np.exp(-decay * tt) * vol).astype(np.float32)


def add(buf, at, snd):
    i = int(at * SR)
    j = min(len(buf), i + len(snd))
    if i < len(buf):
        buf[i:j] += snd[: j - i]


def beat(buf, length, bpm=100):
    """A soft, steady pulse under the whole reel."""
    step = 60 / bpm
    k = 0
    while k * step < length:
        at = k * step
        add(buf, at, tone(70, 0.25, 0.35, 18))
        add(buf, at, tone(140, 0.08, 0.15, 40))
        if k % 2 == 1:
            add(buf, at, (np.random.RandomState(k).randn(int(SR * 0.06)) * 0.05 * np.exp(-np.arange(int(SR * 0.06)) / SR * 60)).astype(np.float32))
        k += 1


def sounds(name, length):
    buf = np.zeros(int(SR * length), np.float32)
    beat(buf, length)
    click = tone(1400, 0.04, 0.18, 90)
    flip = tone(660, 0.09, 0.16, 35)
    ding = tone(880, 0.5, 0.25, 5) + tone(1320, 0.5, 0.15, 6)
    chime = sum(tone(f, 0.9, 0.18, 3.5) for f in (523, 659, 784, 1047))  # same lengths, safe to add
    if name == "kac-deneme":
        for r in range(4):
            a = 1.6 + r * 2.0
            for i in range(5):
                add(buf, a + i * 0.18, click)
                add(buf, a + 0.95 + 0.8 * (i * 0.12 + 0.2), flip)
        add(buf, 9.6, chime)
        add(buf, 10.6, ding)
    elif name == "duello":
        for r in range(5):
            a = 1.4 + r * 1.7
            for i in range(6):
                add(buf, a + 0.6 + 0.7 * (i * 0.12 + 0.2), flip)
        add(buf, 6.0, tone(220, 0.4, 0.3, 4, "sq"))
        add(buf, 6.0, tone(440, 0.4, 0.2, 4))
        add(buf, 10.0, chime)
        for k in range(14):
            add(buf, 10.6 + k * 0.05, tone(1800 + k * 40, 0.05, 0.08, 60))
        add(buf, 11.8, ding)
    else:
        for i in range(5):
            add(buf, 0.8 + 0.8 * (i * 0.12 + 0.2), flip)
            add(buf, 1.2 + 0.8 * (i * 0.12 + 0.2), flip)
        for k in range(5):
            add(buf, 2.0 + k, tone(1000 if k < 3 else 1300, 0.12, 0.25, 25))
        for i in range(5):
            add(buf, 7.0 + 0.8 * (i * 0.12 + 0.2), flip)
        add(buf, 7.6, chime)
        add(buf, 9.6, ding)
    # fade out
    n = int(SR * 0.8)
    buf[-n:] *= np.linspace(1, 0, n)
    peak = np.max(np.abs(buf)) or 1
    return (buf / peak * 0.8 * 32767).astype(np.int16)


def render(name, out):
    fn, length = REELS[name]
    tmp_v = out + ".v.mp4"
    tmp_a = out + ".wav"
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart", tmp_v],
                         stdin=subprocess.PIPE)
    for k in range(int(length * FPS)):
        p.stdin.write(fn(k / FPS).convert("RGB").tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit("video encode failed")
    with wave.open(tmp_a, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(sounds(name, length).tobytes())
    part = out + ".part.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp_v, "-i", tmp_a, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", part], check=True)
    os.replace(part, out)
    os.remove(tmp_v)
    os.remove(tmp_a)


if __name__ == "__main__":
    if sys.argv[1] == "preview":
        os.makedirs("/tmp/reels_preview", exist_ok=True)
        for name, times in {"kac-deneme": [0.9, 6.5, 10.2, 12.5], "duello": [3.6, 6.3, 10.8, 13.5], "bulabilir-misin": [1.5, 4.4, 8.9, 11.5]}.items():
            for t in times:
                REELS[name][0](t).save(f"/tmp/reels_preview/{name}-{t:05.2f}.png")
    else:
        render(sys.argv[2], sys.argv[3])
