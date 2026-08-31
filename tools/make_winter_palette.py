# -*- coding: utf-8 -*-
"""겨울 설원 색상표 + 장면 목업 생성기.

산출물:
  assets/palettes/winter_snowfield.png      색상칩 시트
  assets/palettes/winter_scene_mockup.png   장면 목업 (1280x720)

텍스처를 만들지 않는다. 색상 값을 눈으로 검증하기 위한 이미지다.
실행:  python tools/make_winter_palette.py
"""
import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFont

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets", "palettes")
os.makedirs(OUT_DIR, exist_ok=True)

FONT_KR = "C:/Windows/Fonts/malgun.ttf"
FONT_MONO = "C:/Windows/Fonts/consola.ttf"
FONT_MONO_B = "C:/Windows/Fonts/consolab.ttf"


def font(path, size):
    return ImageFont.truetype(path, size)


# --- 색 변환 ----------------------------------------------------------------
def s2l(c):
    """sRGB 0~1 -> 선형 0~1"""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def l2s(c):
    """선형 0~1 -> sRGB 0~1"""
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def lin_rgb_to_srgb255(lin):
    return tuple(int(round(l2s(c) * 255)) for c in lin)


def luma(rgb):
    """상대 휘도 (선형 기준). 0~1"""
    r, g, b = (s2l(c / 255.0) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b):
    la, lb = luma(a), luma(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def shade(rgb, f):
    return tuple(max(0, min(255, int(round(c * f)))) for c in rgb)


# --- 팔레트 -----------------------------------------------------------------
# (키, 표시 이름, sRGB 0~255, 용도 메모)
PALETTE = [
    ("sky_top", "하늘 위쪽 (천정)", (43, 92, 168),
     "sky_top_color · 건조한 겨울 맑은 하늘의 깊은 청색"),
    ("sky_horizon", "하늘 지평선", (204, 219, 230),
     "sky_horizon_color · 눈안개로 흐려진 창백한 띠"),
    ("sky_ground_horizon", "하늘 아래쪽 (지평선측)", (219, 227, 235),
     "ground_horizon_color · 설원 반사"),
    ("sky_ground_bottom", "하늘 아래쪽 (바닥)", (168, 184, 209),
     "ground_bottom_color · 눈이 되쏘는 푸른 반사광"),
    ("sun", "태양광 색", (230, 240, 255),
     "DirectionalLight3D.light_color · 낮은 겨울 해, 차갑게"),
    ("fog", "안개 색", (199, 214, 230),
     "fog_light_color · fog_density 0.010 과 함께"),
    ("ambient", "주변광 (ambient)", (148, 173, 219),
     "ambient_light_color · 하늘에서 내려앉는 푸른 그늘빛"),
    ("snow_lit", "눈 지면 — 볕", (252, 250, 243),
     "직사광 받는 눈. 파랑기를 빼고 살짝 따뜻하게 (주인공 하늘색과 색상으로 갈라진다)"),
    ("snow_mid", "눈 지면 — 중간", (214, 223, 233),
     "볕/그늘 사이 전이"),
    ("snow_shadow", "눈 지면 — 그늘", (138, 161, 204),
     "눈 그림자. 하늘빛을 받아 확실히 푸르다"),
    ("bark", "소나무 껍질", (61, 46, 38),
     "어두운 갈색. 설원 대비 앵커"),
    ("needle", "솔잎", (41, 69, 59),
     "어두운 침엽수 녹색. 채도 낮게"),
    ("branch_snow", "가지에 쌓인 눈", (233, 238, 245),
     "지면 눈보다 살짝 어둡게. 침엽 사이에 끼는 밝은 조각"),
    ("far_pine", "먼 소나무 (안개 적용 후)", (163, 182, 203),
     "참고값 — 안개가 needle 을 이만큼 지운다"),
    ("player_fur", "[참고] 주인공 털 (FUR)", lin_rgb_to_srgb255((0.45, 0.72, 0.92)),
     "블렌더 선형 (0.45,0.72,0.92) 을 sRGB 로 환산"),
    ("player_membrane", "[참고] 주인공 비막 (MEMBRANE)", lin_rgb_to_srgb255((0.40, 0.62, 0.85)),
     "블렌더 선형 (0.40,0.62,0.85) 을 sRGB 로 환산"),
]

P = {k: c for k, _n, c, _m in PALETTE}


BACKGROUND_KEYS = {"sky_top", "sky_horizon", "fog", "snow_lit", "snow_mid",
                   "snow_shadow", "needle", "bark", "branch_snow", "far_pine"}


def wrap_text(text, fnt, max_w, d):
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=fnt) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# --- 1) 색상칩 시트 ---------------------------------------------------------
def build_palette_sheet():
    W = 1180
    ROW = 90
    TOP = 108
    BOT = 118
    H = TOP + ROW * len(PALETTE) + BOT

    bg = (26, 30, 38)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    f_title = font(FONT_KR, 30)
    f_sub = font(FONT_KR, 15)
    f_name = font(FONT_KR, 19)
    f_memo = font(FONT_KR, 14)
    f_mono = font(FONT_MONO, 14)
    f_mono_b = font(FONT_MONO_B, 15)

    d.text((36, 30), "겨울 설원 색상표 — 하늘 다람쥐", font=f_title, fill=(238, 244, 252))
    d.text((38, 70), "눈 덮인 소나무 숲 / 겨울.  Godot Color(r,g,b) 는 sRGB 0~1, 블렌더 Base Color 는 선형 0~1.",
           font=f_sub, fill=(150, 166, 190))
    d.line([(36, 98), (W - 36, 98)], fill=(64, 74, 92), width=1)

    for i, (key, name, rgb, memo) in enumerate(PALETTE):
        y = TOP + i * ROW
        if i % 2 == 0:
            d.rectangle([28, y, W - 28, y + ROW - 6], fill=(32, 37, 47))

        # 칩 (밝은/어두운 배경 위 반반 — 색이 실제로 어떻게 보이는지)
        cx, cy, cs = 44, y + 8, 62
        d.rectangle([cx, cy, cx + cs, cy + cs], fill=rgb)
        d.rectangle([cx, cy, cx + cs, cy + cs], outline=(90, 102, 122), width=1)

        srgb01 = tuple(round(c / 255.0, 3) for c in rgb)
        lin01 = tuple(round(s2l(c / 255.0), 3) for c in rgb)
        hexs = "#%02X%02X%02X" % rgb

        tx = cx + cs + 22
        d.text((tx, y + 6), name, font=f_name, fill=(232, 239, 248))
        d.text((tx, y + 31),
               "%-9s  RGB(%3d,%3d,%3d)" % (hexs, *rgb),
               font=f_mono_b, fill=(178, 196, 220))
        d.text((tx, y + 51),
               "Godot(%.3f, %.3f, %.3f)  linear(%.3f, %.3f, %.3f)"
               % (*srgb01, *lin01),
               font=f_mono, fill=(140, 158, 184))

        # 오른쪽 블록: 메모 (필요하면 두 줄) + 주인공 대비
        mx = 660
        lines = wrap_text(memo, f_memo, W - 40 - mx, d)
        for li, ln in enumerate(lines[:2]):
            d.text((mx, y + 8 + li * 19), ln, font=f_memo, fill=(126, 142, 166))
        if key in BACKGROUND_KEYS:
            cr = contrast_ratio(rgb, P["player_fur"])
            col = (120, 210, 140) if cr >= 1.9 else ((225, 190, 100) if cr >= 1.45 else (232, 110, 110))
            d.text((mx, y + 8 + max(1, len(lines[:2])) * 19 + 4),
                   "주인공 대비 %.2f:1  %s" % (cr, "양호" if cr >= 1.9 else ("주의" if cr >= 1.45 else "묻힘")),
                   font=f_memo, fill=col)

    # 하단: 안개 밀도 / 사용 메모
    fy = H - BOT + 8
    d.line([(36, fy - 10), (W - 36, fy - 10)], fill=(64, 74, 92), width=1)
    d.text((38, fy), "fog_density = 0.010  ·  fog_sky_affect = 0.25  ·  sun light_energy = 1.05  ·  ambient_light_sky_contribution = 0.75",
           font=f_sub, fill=(186, 200, 220))
    d.text((38, fy + 26), "'주인공 대비'는 주인공 털색과의 명도 대비비. 1.45 미만이면 그 색 위에서 주인공이 묻힌다.",
           font=f_sub, fill=(150, 166, 190))
    d.text((38, fy + 52), "생성: tools/make_winter_palette.py  —  PNG 를 직접 고치지 말고 스크립트를 고칠 것.",
           font=f_sub, fill=(112, 126, 148))

    path = os.path.join(OUT_DIR, "winter_snowfield.png")
    img.save(path)
    return path, img.size


# --- 2) 장면 목업 -----------------------------------------------------------
def draw_pine(d, x, base_y, h, half_w, needle, snow, bark, tiers=6, snow_amt=1.0):
    """소나무 한 그루. base_y 가 밑동, 위로 h 만큼."""
    trunk_w = max(1, int(half_w * 0.15))
    d.rectangle([x - trunk_w, base_y - h * 0.32, x + trunk_w, base_y], fill=bark)

    top_y = base_y - h
    for t in range(tiers):
        f0 = t / tiers
        f1 = (t + 1) / tiers
        ty = top_y + h * 0.90 * f0
        by = top_y + h * 0.90 * f1 + h * 0.10
        w = half_w * (0.18 + 0.82 * (f1 ** 0.80))
        d.polygon([(x, ty), (x - w, by), (x + w, by)], fill=needle)
        if snow_amt > 0.02:
            # 가지 윗면에 얹힌 눈: 같은 삼각형을 위로 살짝 올려 겹친다
            off = max(1.0, h * 0.010)
            sw = w * (0.60 + 0.20 * snow_amt)
            sy = by - (by - ty) * (0.34 + 0.24 * snow_amt)
            d.polygon([(x, ty - off), (x - sw, sy - off), (x + sw, sy - off)],
                      fill=mix(needle, snow, min(1.0, 0.50 + 0.50 * snow_amt)))


def tapered_shadow(d, x, y, length, w0, w1, col_a):
    """밑동에서 왼쪽으로 뻗는 가늘어지는 그림자 (해가 오른쪽)."""
    d.polygon([(x, y - w0 * 0.35), (x - length, y - w1 * 0.5 - length * 0.055),
               (x - length, y + w1 * 0.5 - length * 0.055), (x, y + w0 * 0.65)],
              fill=col_a)


def build_mockup():
    S = 2  # 슈퍼샘플 배율
    W, H = 1280 * S, 720 * S
    HORIZON = 396 * S

    img = Image.new("RGB", (W, H), P["sky_horizon"])
    d = ImageDraw.Draw(img)
    rnd = random.Random(20260831)

    # 하늘 그라디언트 (위쪽 깊은 청 -> 지평선 창백)
    # 지수를 크게 잡아 창백한 지평선 띠를 좁게 유지한다 (= Godot sky_curve 를 낮추는 것과 같은 효과)
    for y in range(HORIZON):
        t = (y / float(HORIZON)) ** 1.9
        d.line([(0, y), (W, y)], fill=mix(P["sky_top"], P["sky_horizon"], t))

    # 낮은 겨울 해 — 지평선 가까이, 옅은 확산광
    sun_x, sun_y = int(W * 0.775), HORIZON - int(40 * S)
    glow = Image.new("RGB", (W, HORIZON), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    R = int(330 * S)
    steps = 48
    for i in range(steps, 0, -1):
        r = R * i / steps
        a = (1.0 - i / steps) ** 2.3
        v = int(255 * a * 0.52)
        gd.ellipse([sun_x - r, sun_y - r * 0.80, sun_x + r, sun_y + r * 0.80],
                   fill=(v, int(v * 0.99), int(v * 0.94)))
    gd.ellipse([sun_x - 12 * S, sun_y - 10 * S, sun_x + 12 * S, sun_y + 10 * S],
               fill=(200, 199, 192))
    from PIL import ImageChops, ImageFilter
    sky_part = img.crop((0, 0, W, HORIZON))
    img.paste(ImageChops.add(sky_part, glow.filter(ImageFilter.GaussianBlur(6 * S))), (0, 0))
    d = ImageDraw.Draw(img)

    # 눈 지면 그라디언트 (지평선 안개색 -> 앞쪽 볕 눈)
    GH = H - HORIZON
    for y in range(HORIZON, H):
        t = (y - HORIZON) / float(GH)
        if t < 0.18:
            c = mix(P["sky_ground_horizon"], P["snow_mid"], t / 0.18)
        else:
            c = mix(P["snow_mid"], P["snow_lit"], ((t - 0.18) / 0.82) ** 0.75)
        d.line([(0, y), (W, y)], fill=c)

    # 눈 표면의 완만한 굴곡 — 푸른 그늘 띠 (부드럽게 흐린다)
    drift = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(drift)
    for _ in range(30):
        t = rnd.random()
        yy = HORIZON + int(GH * 0.04 + GH * 1.02 * (t ** 1.45))
        depth = max(0.0, (yy - HORIZON) / float(GH))
        w = int((120 + 1000 * depth) * S * (0.55 + rnd.random()))
        hh = int((6 + 46 * depth) * S)
        xx = rnd.randint(-int(300 * S), W)
        a = int(16 + 34 * depth)
        dd.ellipse([xx, yy, xx + w, yy + hh], fill=P["snow_shadow"] + (a,))
    drift = drift.filter(ImageFilter.GaussianBlur(9 * S))
    img = Image.alpha_composite(img.convert("RGBA"), drift).convert("RGB")
    d = ImageDraw.Draw(img)

    # 나무 띠 (먼 곳 -> 가까운 곳). 안개 혼합량이 다르다.
    bands = [
        # (밑동 y, 높이범위, 반폭범위, 안개혼합, 그루수, 눈량)
        (HORIZON + 2 * S, (24, 50), (7, 12), 0.80, 165, 0.35),
        (HORIZON + 13 * S, (46, 90), (12, 21), 0.62, 95, 0.55),
        (HORIZON + 33 * S, (84, 152), (19, 34), 0.40, 55, 0.75),
        (HORIZON + 76 * S, (140, 240), (30, 54), 0.22, 28, 0.90),
    ]
    for base_y, hr, wr, fogmix, n, snow_amt in bands:
        needle = mix(P["needle"], P["fog"], fogmix)
        snow_c = mix(P["branch_snow"], P["fog"], fogmix * 0.8)
        bark_c = mix(P["bark"], P["fog"], fogmix)
        xs = sorted(rnd.uniform(-40 * S, W + 40 * S) for _ in range(n))
        for x in xs:
            h = rnd.uniform(*hr) * S
            hw = rnd.uniform(*wr) * S
            draw_pine(d, x, base_y + rnd.uniform(-5, 5) * S, h, hw,
                      needle, snow_c, bark_c, tiers=6, snow_amt=snow_amt)

    # 근경 나무의 긴 그림자 (해가 오른쪽 -> 왼쪽으로 뻗는다). 나무보다 먼저.
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    for (bx, by, ln, w0, w1, a) in [(168, 704, 430, 40, 96, 92),
                                    (1188, 658, 340, 34, 78, 84),
                                    (982, 608, 230, 22, 52, 70),
                                    (742, 562, 150, 15, 34, 58)]:
        tapered_shadow(sd, bx * S, by * S, ln * S, w0 * S, w1 * S,
                       P["snow_shadow"] + (a,))
    sh = sh.filter(ImageFilter.GaussianBlur(11 * S))
    img = Image.alpha_composite(img.convert("RGBA"), sh).convert("RGB")
    d = ImageDraw.Draw(img)

    # 중경 소나무 몇 그루 (빈 설원을 메우고, 주인공 뒤 어두운 배경을 만든다)
    for (x, by, h, hw, fog) in [(742, 562, 165, 38, 0.16), (392, 545, 140, 33, 0.18),
                                (866, 520, 110, 26, 0.24)]:
        draw_pine(d, x * S, by * S, h * S, hw * S,
                  mix(P["needle"], P["fog"], fog), P["branch_snow"],
                  mix(P["bark"], P["fog"], fog), tiers=6, snow_amt=0.9)

    # 근경 소나무 (안개 거의 없음)
    draw_pine(d, 168 * S, 706 * S, 430 * S, 98 * S,
              P["needle"], P["branch_snow"], P["bark"], tiers=7, snow_amt=1.0)
    draw_pine(d, 1188 * S, 660 * S, 350 * S, 82 * S,
              P["needle"], P["branch_snow"], P["bark"], tiers=7, snow_amt=1.0)
    draw_pine(d, 982 * S, 610 * S, 240 * S, 56 * S,
              mix(P["needle"], P["fog"], 0.10), P["branch_snow"],
              mix(P["bark"], P["fog"], 0.10), tiers=6, snow_amt=0.9)

    # 주인공 접지 그림자 — 흰 설원 위에서 시인성을 만드는 결정적 장치
    psh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(psh).ellipse([478 * S, 520 * S, 636 * S, 556 * S],
                                fill=P["snow_shadow"] + (150,))
    psh = psh.filter(ImageFilter.GaussianBlur(7 * S))
    img = Image.alpha_composite(img.convert("RGBA"), psh).convert("RGB")

    # 주인공 — 지평선에 걸치도록 배치 (창백한 지평선 하늘 / 먼 숲 / 눈밭을 동시에 만난다)
    draw_squirrel(img, cx=556 * S, cy=386 * S, span=224 * S)

    img = img.resize((1280, 720), Image.LANCZOS)

    # 캡션
    d2 = ImageDraw.Draw(img)
    f = font(FONT_KR, 15)
    fs = font(FONT_KR, 13)
    d2.text((470, 556), "접지 그림자", font=fs, fill=(92, 116, 158))
    d2.rectangle([0, 690, 1280, 720], fill=(18, 22, 30))
    d2.text((12, 697),
            "겨울 설원 목업 — winter_snowfield.png 의 색만 사용 · 주인공은 지평선에 걸쳐 배치(최악 조건: 창백한 하늘 + 눈밭)",
            font=f, fill=(196, 208, 224))

    path = os.path.join(OUT_DIR, "winter_scene_mockup.png")
    img.save(path)
    return path, img.size


def draw_squirrel(img, cx, cy, span):
    """위-뒤에서 본 활공 자세. span = 비막을 펼친 가로 폭(px).

    윤곽선도, 시인성을 위한 보정도 넣지 않는다. FUR/MEMBRANE 실제 색과
    부드러운 형태 음영만으로 그려서 '배경에 묻히는가'를 정직하게 본다.
    좌표는 전부 span 배수 (머리가 위, 꼬리가 아래).
    """
    from PIL import ImageChops
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)

    def q(x, y):
        return (cx + x * span, cy + y * span)

    def eb(x0, y0, x1, y1):
        return [cx + x0 * span, cy + y0 * span, cx + x1 * span, cy + y1 * span]

    fur = P["player_fur"]
    mem = P["player_membrane"]

    # 꼬리 — 넓적하게 펴진 상태 (비막 뒤로 빠져나온다)
    d.polygon([q(-0.09, 0.02), q(0.09, 0.02), q(0.135, 0.46), q(-0.135, 0.46)], fill=fur)
    d.ellipse(eb(-0.135, 0.24, 0.135, 0.68), fill=fur)

    # 비막 — 앞 모서리(손)에서 뒤 모서리(발)로 이어진 한 장
    d.polygon([
        q(0.10, -0.34), q(0.30, -0.385), q(0.455, -0.325), q(0.508, -0.215),
        q(0.500, -0.020), q(0.440, 0.155), q(0.340, 0.255), q(0.205, 0.238),
        q(0.100, 0.140), q(-0.100, 0.140), q(-0.205, 0.238), q(-0.340, 0.255),
        q(-0.440, 0.155), q(-0.500, -0.020), q(-0.508, -0.215), q(-0.455, -0.325),
        q(-0.30, -0.385), q(-0.10, -0.34),
    ], fill=mem)

    # 몸통
    d.ellipse(eb(-0.148, -0.40, 0.148, 0.21), fill=fur)

    # 귀 (머리 뒤로 먼저)
    for u in (-1, 1):
        d.ellipse(eb(u * 0.092 - 0.052, -0.605, u * 0.092 + 0.052, -0.495), fill=fur)
    # 머리
    d.ellipse(eb(-0.128, -0.585, 0.128, -0.335), fill=fur)

    # --- 형태 음영: 위-오른쪽에서 빛, 아래-왼쪽이 어둡다 ---
    bx0, by0 = int(cx - 0.62 * span), int(cy - 0.70 * span)
    bx1, by1 = int(cx + 0.62 * span), int(cy + 0.78 * span)
    gw = gh = 96
    small = Image.new("L", (gw, gh))
    px = small.load()
    for gy in range(gh):
        for gx in range(gw):
            t = ((gx / (gw - 1.0)) - (gy / (gh - 1.0))) * 0.5 + 0.5  # 우상=1, 좌하=0
            px[gx, gy] = int(112 * max(0.0, min(1.0, 1.0 - t)) ** 1.15)
    grad = small.resize((bx1 - bx0, by1 - by0), Image.BILINEAR)

    a_full = Image.new("L", lay.size, 0)
    a_full.paste(grad, (bx0, by0))
    a_full = ImageChops.multiply(a_full, lay.split()[3])
    tint = Image.new("RGBA", lay.size, (16, 38, 76, 0))
    tint.putalpha(a_full)
    lay = Image.alpha_composite(lay, tint)

    img.paste(Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB"), (0, 0))


# --- 3) 검증용 대비 시트 (프로젝트 밖) --------------------------------------
def build_contrast_sheet(path):
    keys = ["sky_top", "sky_horizon", "sky_ground_bottom", "fog", "ambient",
            "snow_lit", "snow_mid", "snow_shadow", "far_pine", "needle", "bark",
            "branch_snow"]
    CW, CH = 176, 132
    cols = 6
    rows = (len(keys) + cols - 1) // cols
    img = Image.new("RGB", (cols * CW, rows * CH + 34), (20, 22, 28))
    d = ImageDraw.Draw(img)
    f = font(FONT_KR, 13)
    fb = font(FONT_MONO_B, 13)
    d.text((8, 8), "주인공(FUR/MEMBRANE) 시인성 테스트 — 각 배경색 위", font=f, fill=(230, 236, 246))
    for i, k in enumerate(keys):
        r, c = divmod(i, cols)
        x, y = c * CW, 34 + r * CH
        d.rectangle([x, y, x + CW - 2, y + CH - 2], fill=P[k])
        d.ellipse([x + 44, y + 26, x + CW - 46, y + 78], fill=P["player_fur"])
        d.ellipse([x + 62, y + 36, x + CW - 64, y + 68], fill=P["player_membrane"])
        cr = contrast_ratio(P[k], P["player_fur"])
        tc = (20, 20, 20) if luma(P[k]) > 0.28 else (240, 240, 240)
        d.text((x + 8, y + 90), k, font=f, fill=tc)
        d.text((x + 8, y + 108), "%.2f:1" % cr, font=fb, fill=tc)
    img.save(path)
    return path


if __name__ == "__main__":
    p1, s1 = build_palette_sheet()
    print("palette  ->", p1, s1)
    p2, s2 = build_mockup()
    print("mockup   ->", p2, s2)
    scratch = os.environ.get("SCRATCH_DIR")
    if scratch:
        print("contrast ->", build_contrast_sheet(os.path.join(scratch, "contrast.png")))
    for k in ("sky_top", "sky_horizon", "snow_lit", "snow_mid", "snow_shadow",
              "far_pine", "needle", "fog"):
        print("%-20s vs FUR : %.2f:1" % (k, contrast_ratio(P[k], P["player_fur"])))
