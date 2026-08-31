#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
하늘다람쥐 - 「눈 덮인 설원 / 소나무 숲」 오디오 합성기.

원본은 이 스크립트다. 산출물(.wav/.ogg)은 여기서만 생성하고 손으로 고치지 않는다.
표준 라이브러리(wave/array/math/random)만 쓴다. numpy 는 이 환경에 없다.

  python tools/audio/make_audio.py
  python tools/audio/check_audio.py     # 수치 검증

루프 파일의 이음매 처리:
  길이 N 의 루프를 만들 때 실제로는 N+F 샘플을 만든 뒤,
  앞 F 구간에 뒤쪽 F 구간을 등파워(sin/cos) 크로스페이드로 겹쳐 넣고 N 으로 자른다.
  그러면 out[N-1] = raw[N-1] 다음에 out[0] = raw[N] 이 오므로
  원래 연속이던 스트림이 그대로 이어져 이음매가 수학적으로 사라진다.
  느린 돌풍 엔벨로프는 주기를 정확히 N 으로 잡아 크로스페이드가 엔벨로프를 흐트러뜨리지 않게 한다.
"""

import array
import math
import os
import random
import subprocess
import sys
import wave

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SR = 44100
TWO_PI = 2.0 * math.pi

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
AUD = os.path.join(ROOT, "assets", "audio")
AMB_DIR = os.path.join(AUD, "ambience")
PLR_DIR = os.path.join(AUD, "player")
FS_DIR = os.path.join(PLR_DIR, "footstep")


# ---------------------------------------------------------------- 기본 유틸

def buf(n, v=0.0):
    return array.array("d", [v]) * n if n else array.array("d")


def noise(n, rng):
    r = rng.random
    return array.array("d", [r() * 2.0 - 1.0 for _ in range(n)])


def lp1(b, fc, passes=1):
    """1차 로우패스. 여러 번 걸면 기울기가 가팔라진다."""
    a = 1.0 - math.exp(-TWO_PI * fc / SR)
    n = len(b)
    for _ in range(passes):
        y = 0.0
        for i in range(n):
            y += a * (b[i] - y)
            b[i] = y
    return b


def hp1(b, fc):
    """1차 하이패스 (원신호 - 로우패스). DC/저역 뭉침 제거용."""
    a = 1.0 - math.exp(-TWO_PI * fc / SR)
    y = 0.0
    for i in range(len(b)):
        x = b[i]
        y += a * (x - y)
        b[i] = x - y
    return b


def svf_bp(b, fc, q):
    """Chamberlin 상태변수 필터의 밴드패스 출력. q 가 클수록 공진이 좁고 뾰족하다."""
    f = 2.0 * math.sin(math.pi * min(fc, SR * 0.22) / SR)
    damp = 1.0 / max(q, 0.5)
    low = 0.0
    band = 0.0
    for i in range(len(b)):
        high = b[i] - low - damp * band
        band += f * high
        low += f * band
        b[i] = band
    return b


def rms(b):
    if not len(b):
        return 0.0
    return math.sqrt(sum(v * v for v in b) / len(b))


def peak(b):
    return max(abs(v) for v in b) if len(b) else 0.0


def gain(b, g):
    for i in range(len(b)):
        b[i] *= g
    return b


def norm_peak(b, target):
    p = peak(b)
    return gain(b, target / p) if p > 1e-12 else b


def norm_rms(b, target):
    r = rms(b)
    return gain(b, target / r) if r > 1e-12 else b


def add_into(dst, src, at, g=1.0):
    n = len(dst)
    for j in range(len(src)):
        i = at + j
        if 0 <= i < n:
            dst[i] += src[j] * g


def fade_edges(b, in_ms, out_ms):
    """시작·끝을 0 으로 붙여 재생 시작/종료 때의 '툭' 소리를 막는다."""
    n = len(b)
    ni = min(n, max(1, int(SR * in_ms / 1000.0)))
    no = min(n, max(1, int(SR * out_ms / 1000.0)))
    for i in range(ni):
        b[i] *= 0.5 - 0.5 * math.cos(math.pi * i / ni)
    for j in range(no):
        i = n - 1 - j
        b[i] *= 0.5 - 0.5 * math.cos(math.pi * j / no)
    return b


def dbfs(x):
    return -999.0 if x <= 1e-12 else 20.0 * math.log10(x)


def lin(db):
    return 10.0 ** (db / 20.0)


# ---------------------------------------------------------------- 루프 도구

def gust_env(n, comps, lo, hi, decim=50):
    """주기가 정확히 n 인 저주파 합성 엔벨로프.

    comps 는 (하모닉 차수 k, 진폭, 위상). 주파수가 전부 k/n 이므로 결과는 n 주기로 딱 반복된다.
    LFO 는 매우 느리므로 decim 배 솎아 계산하고 선형 보간한다(순수 파이썬 속도 대책).
    """
    assert n % decim == 0, "루프 길이는 decim 의 배수여야 한다"
    m = n // decim
    ctrl = [0.0] * m
    for k, a, ph in comps:
        w = TWO_PI * k * decim / n
        for i in range(m):
            ctrl[i] += a * math.sin(w * i + ph)
    mn, mx = min(ctrl), max(ctrl)
    span = (mx - mn) or 1.0
    for i in range(m):
        ctrl[i] = lo + (hi - lo) * (ctrl[i] - mn) / span

    e = buf(n)
    for i in range(m):
        a0 = ctrl[i]
        a1 = ctrl[(i + 1) % m]          # 마지막 구간은 0 번으로 되돌아 -> 주기 유지
        step = (a1 - a0) / decim
        base = i * decim
        v = a0
        for j in range(decim):
            e[base + j] = v
            v += step
    return e


def loop_wrap(b, n, f):
    """길이 n+f 인 원재료를 이음매 없는 길이 n 루프로 접는다."""
    assert len(b) >= n + f
    out = array.array("d", b[:n])
    for i in range(f):
        u = (i + 0.5) / f
        out[i] = b[i] * math.sin(0.5 * math.pi * u) + b[n + i] * math.cos(0.5 * math.pi * u)
    return out


# ---------------------------------------------------------------- 파일 쓰기

assert sys.byteorder == "little", "array('h') 직렬화가 리틀엔디안 전제다"


def write_wav(path, chans):
    nch = len(chans)
    n = len(chans[0])
    data = array.array("h", bytes(2 * n * nch))
    clipped = 0
    for c, ch in enumerate(chans):
        for i in range(n):
            v = int(round(ch[i] * 32767.0))
            if v > 32767:
                v = 32767
                clipped += 1
            elif v < -32768:
                v = -32768
                clipped += 1
            data[c + i * nch] = v
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(nch)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
    if clipped:
        print("  [경고] 클리핑 %d 샘플: %s" % (clipped, path))
    return clipped


def to_ogg(wav_path, ogg_path, q=5):
    os.makedirs(os.path.dirname(ogg_path), exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", wav_path,
           "-c:a", "libvorbis", "-q:a", str(q), ogg_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 실패: %s" % (r.stderr or r.stdout))
    return ogg_path


# ---------------------------------------------------------------- 소재 합성

def snow_crunch(rng, dur, res_f, grains, low_amt=0.35, res_amt=0.55):
    """눈을 밟을 때의 '뽀득'. 아주 짧은 알갱이(그레인) 다발을 공진 밴드패스에 통과시킨다."""
    n = int(dur * SR)
    src = noise(n, rng)

    # 그레인 게이트 - 앞쪽에 몰리도록 가중
    g = buf(n)
    for _ in range(grains):
        w = max(4, int(rng.uniform(0.0025, 0.0095) * SR))
        start = int((n - w) * (rng.random() ** 1.5) * 0.85)
        amp = rng.uniform(0.25, 1.0)
        for j in range(w):
            g[start + j] += amp * (0.5 - 0.5 * math.cos(TWO_PI * j / w))
    gm = max(g) or 1.0
    for i in range(n):
        src[i] *= min(1.0, g[i] / gm * 1.35)

    body = array.array("d", src)
    svf_bp(body, 1400.0, 0.9)
    squeak = array.array("d", src)
    svf_bp(squeak, res_f, 4.0)

    low = noise(n, rng)
    lp1(low, 260.0, 2)

    out = buf(n)
    for i in range(n):
        t = i / SR
        out[i] = body[i] + res_amt * squeak[i] + low_amt * low[i] * math.exp(-t / 0.035)

    for i in range(n):
        t = i / SR
        out[i] *= min(1.0, t / 0.002) * math.exp(-t / (dur * 0.30))

    fade_edges(out, 0.5, 12.0)
    return out


def snow_drop(rng):
    """가지에 얹힌 눈이 툭 떨어지는 소리. 부드러운 퍼프 + 아주 작은 알갱이."""
    dur = 0.42
    n = int(dur * SR)
    b = noise(n, rng)
    lp1(b, 850.0, 2)
    for i in range(n):
        t = i / SR
        b[i] *= min(1.0, t / 0.006) * math.exp(-t / 0.095)
    tick = noise(n, rng)
    svf_bp(tick, 2400.0, 1.6)
    for i in range(n):
        t = i / SR
        b[i] += tick[i] * 0.25 * math.exp(-t / 0.020)
    norm_peak(b, 1.0)
    fade_edges(b, 1.0, 25.0)
    return b


def branch_sway(rng, dur):
    """바람에 가지와 솔잎이 흔들리는 스웰. 시작·끝 진폭이 정확히 0 이라 어디에 놓아도 안전하다."""
    n = int(dur * SR)
    b = noise(n, rng)
    svf_bp(b, 1500.0, 0.75)
    lowb = noise(n, rng)
    lp1(lowb, 240.0, 2)
    for i in range(n):
        u = i / n
        env = math.sin(math.pi * u) ** 2
        b[i] = (b[i] + lowb[i] * 0.55) * env
    norm_peak(b, 1.0)
    return b


# ---------------------------------------------------------------- 원샷 레벨 정리

LOUD_WIN_MS = 100.0


def loudness(b, win_ms=LOUD_WIN_MS):
    """원샷의 음량 지표: 100 ms 슬라이딩 창 RMS 의 최댓값.

    파일 전체 RMS 로 재면 감쇠 꼬리가 긴 소리(착지음)가 부당하게 작게 나오고,
    그걸 목표에 맞추려 게인을 올리면 트랜지언트만 리미터에 걸려 찌그러진다.
    라우드니스 미터(momentary 400 ms)와 같은 발상이되, 이 프로젝트의 효과음이
    145~550 ms 로 짧아 창을 100 ms 로 줄였다.
    """
    n = len(b)
    if n == 0:
        raise RuntimeError("빈 버퍼")
    w = min(n, int(SR * win_ms / 1000.0))
    acc = 0.0
    for i in range(w):
        acc += b[i] * b[i]
    best = acc
    for i in range(w, n):
        acc += b[i] * b[i] - b[i - w] * b[i - w]
        if acc > best:
            best = acc
    if best <= 1e-24:
        raise RuntimeError("무음 버퍼")
    return math.sqrt(best / w)


def soft_limit(b, ceiling):
    """tanh 리미터. 피크만 부드럽게 눌러 ceiling 아래로 붙인다.

    통째로 게인을 줄이면(단순 정규화) 크레스트가 큰 착지음이 목표 음량에 한참 못 미친다.
    tanh 는 작은 진폭에서는 거의 선형(오차 <0.3%)이라 지속부의 음색은 건드리지 않고
    맨 앞 트랜지언트만 압축한다. 대신 압축량이 크면 그 구간에 배음이 생긴다.
    """
    for i in range(len(b)):
        b[i] = ceiling * math.tanh(b[i] / ceiling)
    return b


def finalize_oneshot(b, loud_db, peak_ceiling_db, max_limit_db=1.5):
    """음량(100 ms 창 최대 RMS)을 목표에 맞추되 피크는 천장 아래로 유지한다.

    게인 -> 리미팅 -> 재측정 을 반복해 수렴시킨다.
    리미팅 총량이 max_limit_db 를 넘으면 소재의 크레스트가 잘못된 것이므로 실패로 본다
    (억지로 눌러 찌그러뜨리느니 소재를 고치는 게 맞다).
    """
    target = lin(loud_db)
    ceil_val = lin(peak_ceiling_db)
    limited_db = 0.0
    for _ in range(8):
        g = target / loudness(b)
        if abs(dbfs(g)) < 0.03:
            break
        gain(b, g)
        p = peak(b)
        if p > ceil_val * 0.999:
            limited_db += dbfs(p / ceil_val)
            soft_limit(b, ceil_val)
    if limited_db > max_limit_db:
        raise RuntimeError("리미팅 %.1f dB - 소재의 크레스트가 너무 크다" % limited_db)
    if limited_db > 0.05:
        print("    (리미팅 %.1f dB 적용 - 트랜지언트에 약간의 새추레이션)" % limited_db)
    return b


# ---------------------------------------------------------------- 1) 겨울 숲 앰비언스

def make_ambience():
    print("[1] 겨울 소나무 숲 앰비언스 (루프)")
    T = 24.0
    N = int(T * SR)                 # 1,058,400  (50 의 배수)
    F = int(3.0 * SR)               # 크로스페이드 3초
    NX = N + F
    rng = random.Random(20260831)

    chans = []
    for ch in range(2):
        off = 0.0 if ch == 0 else 1.13     # 좌우 돌풍 위상차 -> 스테레오 폭
        # 느리게 오가는 돌풍. 최저 0.09 까지 떨어져 '휑한' 정적 구간이 생긴다.
        env = gust_env(N, [(1, 1.00, 0.30 + off), (2, 0.55, 2.10 + off),
                           (3, 0.36, 4.05 + off), (5, 0.22, 1.20 + off),
                           (7, 0.13, 5.30 + off)], 0.09, 1.0)

        # (a) 낮게 부는 바람 본체
        bed = noise(NX, rng)
        lp1(bed, 210.0, 2)
        hp1(bed, 28.0)
        norm_rms(bed, 1.0)

        # (b) 솔잎 사이를 스치는 바람의 쉭 소리 - 돌풍이 셀 때만 올라온다
        hiss = noise(NX, rng)
        svf_bp(hiss, 2100.0, 0.7)
        norm_rms(hiss, 1.0)

        # (c) 숲의 빈 공간이 주는 아주 낮은 웅 - 거의 일정
        sub = noise(NX, rng)
        lp1(sub, 75.0, 3)
        hp1(sub, 22.0)
        norm_rms(sub, 1.0)

        raw = buf(NX)
        for i in range(NX):
            e = env[i - N] if i >= N else env[i]     # 엔벨로프는 N 주기
            raw[i] = (bed[i] * e * 0.72
                      + hiss[i] * (e * e) * 0.16
                      + sub[i] * (0.35 + 0.25 * e) * 0.30)

        chans.append(loop_wrap(raw, N, F))
        print("    채널 %d 베드 합성 완료" % ch)

    # 산발적 사건: 가지 흔들림과 눈 떨어짐. 전부 루프 안쪽에 완전히 들어가게 배치한다.
    erng = random.Random(777)
    for t, dur, pan, g in [(1.8, 2.6, -0.55, 0.55), (8.6, 3.2, 0.62, 0.48),
                           (14.2, 2.2, -0.20, 0.40), (19.4, 2.8, 0.35, 0.52)]:
        s = branch_sway(erng, dur)
        at = int(t * SR)
        assert at + len(s) < N, "가지 흔들림이 루프 끝을 넘는다"
        add_into(chans[0], s, at, g * 0.62 * (0.5 - 0.5 * pan))
        add_into(chans[1], s, at, g * 0.62 * (0.5 + 0.5 * pan))

    for t, pan, g in [(3.9, 0.70, 0.30), (6.7, -0.45, 0.22), (11.9, 0.15, 0.26),
                      (16.5, -0.75, 0.20), (21.6, 0.50, 0.25)]:
        d = snow_drop(erng)
        at = int(t * SR)
        assert at + len(d) < N, "눈 떨어짐이 루프 끝을 넘는다"
        add_into(chans[0], d, at, g * (0.5 - 0.5 * pan))
        add_into(chans[1], d, at, g * (0.5 + 0.5 * pan))

    # 목표: 조용한 배경. RMS -26 dBFS, 피크는 -4 dBFS 아래.
    target = lin(-26.0)
    cur = math.sqrt(sum(rms(c) ** 2 for c in chans) / 2.0)
    for c in chans:
        gain(c, target / cur)
    p = max(peak(c) for c in chans)
    if p > lin(-4.0):
        for c in chans:
            gain(c, lin(-4.0) / p)

    wav = os.path.join(AMB_DIR, "amb_winter_forest.wav")
    write_wav(wav, chans)
    ogg = to_ogg(wav, os.path.join(AMB_DIR, "amb_winter_forest.ogg"), q=5)
    os.remove(wav)
    print("    -> %s" % ogg)


# ---------------------------------------------------------------- 2) 활공 바람

def make_glide_wind():
    print("[2] 활공 바람 (루프)")
    T = 8.0
    N = int(T * SR)                 # 352,800 (50 의 배수)
    F = int(2.0 * SR)
    NX = N + F
    rng = random.Random(31415)

    chans = []
    for ch in range(2):
        off = 0.0 if ch == 0 else 0.83
        # 성격이 '일정'해야 게임에서 볼륨·피치로 제어할 수 있다. 변동 폭은 약 1.3 dB.
        env = gust_env(N, [(1, 1.0, 0.4 + off), (2, 0.6, 2.6 + off), (3, 0.4, 5.1 + off)],
                       0.86, 1.0)

        body = noise(NX, rng)
        svf_bp(body, 620.0, 0.55)
        norm_rms(body, 1.0)

        rumble = noise(NX, rng)
        lp1(rumble, 260.0, 2)
        hp1(rumble, 35.0)
        norm_rms(rumble, 1.0)

        air = noise(NX, rng)
        svf_bp(air, 2600.0, 1.1)
        norm_rms(air, 1.0)

        raw = buf(NX)
        for i in range(NX):
            e = env[i - N] if i >= N else env[i]
            raw[i] = (body[i] * 0.62 + rumble[i] * 0.46 + air[i] * 0.20) * e

        chans.append(loop_wrap(raw, N, F))
        print("    채널 %d 합성 완료" % ch)

    target = lin(-20.0)             # 최대 속도 기준. 게임에서 속도에 따라 줄여 쓴다.
    cur = math.sqrt(sum(rms(c) ** 2 for c in chans) / 2.0)
    for c in chans:
        gain(c, target / cur)
    p = max(peak(c) for c in chans)
    if p > lin(-3.0):
        for c in chans:
            gain(c, lin(-3.0) / p)

    wav = os.path.join(PLR_DIR, "sfx_glide_wind.wav")
    write_wav(wav, chans)
    ogg = to_ogg(wav, os.path.join(PLR_DIR, "sfx_glide_wind.ogg"), q=5)
    os.remove(wav)
    print("    -> %s" % ogg)


# ---------------------------------------------------------------- 3) 점프

def make_jump():
    print("[3] 점프")
    rng = random.Random(4101)
    dur = 0.22
    n = int(dur * SR)
    out = buf(n)

    # 가볍게 위로 훑고 올라가는 '흡' - 작은 동물다운 높은 음역
    ph = 0.0
    for i in range(n):
        t = i / SR
        u = min(1.0, t / 0.125)
        f = 300.0 + 470.0 * (u ** 0.62)
        ph += TWO_PI * f / SR
        s = math.sin(ph) + 0.22 * math.sin(2 * ph) + 0.07 * math.sin(3 * ph)
        out[i] = s * min(1.0, t / 0.004) * math.exp(-t / 0.068)

    norm_peak(out, 0.80)
    push = snow_crunch(rng, 0.10, 2100.0, 16, low_amt=0.50, res_amt=0.35)
    norm_peak(push, 0.38)
    add_into(out, push, 0)

    fade_edges(out, 0.5, 18.0)
    finalize_oneshot(out, loud_db=-16.0, peak_ceiling_db=-3.0)
    write_wav(os.path.join(PLR_DIR, "sfx_jump.wav"), [out])
    print("    -> sfx_jump.wav (%.0f ms)" % (dur * 1000))


# ---------------------------------------------------------------- 4) 눈 위 착지

def make_land():
    print("[4] 눈 위 착지")
    rng = random.Random(5202)
    dur = 0.55
    n = int(dur * SR)
    out = buf(n)

    # 눈에 푹 파묻히는 퍼프 (딱딱한 땅이 아니라 흡음되는 눈이라 고역이 거의 없다).
    # 어택을 10 ms 로 둔 것은 의도다. 눈은 딱딱한 표면과 달리 '탁' 하고 서지 않는다.
    # 덤으로 트랜지언트 피크가 낮아져 리미팅을 거의 안 걸어도 목표 음량에 닿는다.
    puff = noise(n, rng)
    lp1(puff, 700.0, 2)
    hp1(puff, 35.0)                       # DC 제거
    for i in range(n):
        t = i / SR
        out[i] += puff[i] * min(1.0, t / 0.010) * math.exp(-t / 0.135)

    # 낮은 몸통 - 짧고 둔탁하게. 길면 무거워져 톤이 안 맞는다.
    for i in range(n):
        t = i / SR
        s = math.sin(TWO_PI * 92.0 * t) * 0.55 + math.sin(TWO_PI * 66.0 * t) * 0.32
        out[i] += s * min(1.0, t / 0.008) * math.exp(-t / 0.052) * 0.26

    # 착지 순간 눈 알갱이가 부서지는 소리
    # 알갱이 층은 가장 큰 그레인 하나가 피크를 독점한다(크레스트 약 22 dB).
    # 그걸 그대로 두면 전체 게인을 올릴 수 없으므로 층 단계에서 낮게 깔아둔다.
    cr = snow_crunch(rng, 0.20, 1750.0, 30, low_amt=0.20, res_amt=0.50)
    norm_peak(cr, 0.20)
    add_into(out, cr, int(0.004 * SR))

    # 주저앉는 꼬리
    tail = noise(n, rng)
    lp1(tail, 380.0, 3)
    hp1(tail, 35.0)
    for i in range(n):
        t = i / SR
        out[i] += tail[i] * (1.0 - math.exp(-t / 0.045)) * math.exp(-t / 0.19) * 0.60

    fade_edges(out, 0.5, 30.0)
    finalize_oneshot(out, loud_db=-15.5, peak_ceiling_db=-2.0)
    write_wav(os.path.join(PLR_DIR, "sfx_land_snow.wav"), [out])
    print("    -> sfx_land_snow.wav (%.0f ms)" % (dur * 1000))


# ---------------------------------------------------------------- 5) 눈 위 발소리 x4

FOOTSTEP_VARIANTS = [
    # (시드, 길이 s, 공진 Hz, 그레인 수, 레벨 미세조정 dB)
    (9001, 0.160, 1650.0, 22, -0.4),
    (9002, 0.185, 1980.0, 27, +0.6),
    (9003, 0.145, 2260.0, 19, -0.9),
    (9004, 0.200, 2520.0, 31, +0.9),
]


def make_footsteps():
    print("[5] 눈 위 발소리 (변형 4종)")
    # 공진 주파수·그레인 밀도·길이를 조금씩 달리해 연속 재생 때 기계적으로 들리지 않게 한다.
    for idx, (seed, dur, res_f, grains, trim_db) in enumerate(FOOTSTEP_VARIANTS, start=1):
        rng = random.Random(seed)
        s = snow_crunch(rng, dur, res_f, grains, low_amt=0.40, res_amt=0.60)

        # 발이 눈을 누르며 들어가는 짧은 저역
        n = len(s)
        press = noise(n, rng)
        lp1(press, 200.0, 2)
        for i in range(n):
            t = i / SR
            s[i] += press[i] * min(1.0, t / 0.004) * math.exp(-t / 0.045) * 0.55

        fade_edges(s, 0.5, 14.0)
        finalize_oneshot(s, loud_db=-23.5 + trim_db, peak_ceiling_db=-3.0)
        path = os.path.join(FS_DIR, "sfx_footstep_snow_%02d.wav" % idx)
        write_wav(path, [s])
        print("    -> %s (%.0f ms, 공진 %.0f Hz)"
              % (os.path.basename(path), dur * 1000, res_f))


# ----------------------------------------------------------------------------

def main():
    for d in (AMB_DIR, PLR_DIR, FS_DIR):
        os.makedirs(d, exist_ok=True)
    make_jump()
    make_land()
    make_footsteps()
    make_glide_wind()
    make_ambience()
    print("\n합성 완료. 검증: python tools/audio/check_audio.py")


if __name__ == "__main__":
    main()
