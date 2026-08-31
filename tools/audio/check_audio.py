#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
하늘다람쥐 오디오 수치 검증기.

사운드 담당자는 소리를 들을 수 없다. 그래서 산출물을 다시 읽어 수치로만 판정한다.
.ogg 는 ffmpeg 로 디코드해서 '최종적으로 게임이 듣게 될 파형'을 본다
(vorbis 는 손실 압축이라 인코드 전 파형으로 판정하면 의미가 없다).

검사 항목
  - 길이 / 샘플레이트 / 채널 / 비트깊이 / 파일 크기
  - 피크, RMS (dBFS), DC 오프셋
  - 클리핑 샘플 수
  - 시작·끝 샘플이 0 근처인가 (원샷의 '툭' 방지)
  - 루프 파일: 이음매 불연속. |x[N-1]-x[0]| 를 이웃 샘플 차분 RMS 와 비교한다.
    비율이 1 근처면 이음매가 신호의 평소 변화량과 구분되지 않는다 = 안 들린다.
  - 영점 교차율 -> 대략의 음역 확인

  python tools/audio/check_audio.py     # 실패하면 종료 코드 1
"""

import array
import math
import os
import subprocess
import sys
import tempfile
import wave

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
AUD = os.path.join(ROOT, "assets", "audio")

# (상대경로, 루프인가, 기대 채널 수, 목표 RMS dBFS, 허용 오차 dB)
TARGETS = [
    ("ambience/amb_winter_forest.ogg", True, 2, -26.0, 2.0),
    ("player/sfx_glide_wind.ogg", True, 2, -20.0, 2.0),
    ("player/sfx_jump.wav", False, 1, None, None),
    ("player/sfx_land_snow.wav", False, 1, None, None),
    ("player/footstep/sfx_footstep_snow_01.wav", False, 1, None, None),
    ("player/footstep/sfx_footstep_snow_02.wav", False, 1, None, None),
    ("player/footstep/sfx_footstep_snow_03.wav", False, 1, None, None),
    ("player/footstep/sfx_footstep_snow_04.wav", False, 1, None, None),
]

# 원샷 음량은 100 ms 슬라이딩 창 RMS 의 최댓값으로 판정한다.
# 파일 전체 RMS 는 감쇠 꼬리 길이에 좌우돼 서로 다른 길이의 효과음을 비교할 수 없다.
# (경로: 목표 dBFS, 허용 오차 dB)
ONESHOT_LOUDNESS = {
    "player/sfx_jump.wav": (-16.0, 1.0),
    "player/sfx_land_snow.wav": (-15.5, 1.0),
    "player/footstep/sfx_footstep_snow_01.wav": (-23.9, 1.0),
    "player/footstep/sfx_footstep_snow_02.wav": (-22.9, 1.0),
    "player/footstep/sfx_footstep_snow_03.wav": (-24.4, 1.0),
    "player/footstep/sfx_footstep_snow_04.wav": (-22.6, 1.0),
}
LOUD_WIN_MS = 100.0


def dbfs(x):
    return float("-inf") if x <= 1e-12 else 20.0 * math.log10(x)


def read_wav(path):
    with wave.open(path, "rb") as w:
        nch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise RuntimeError("16bit 가 아니다: %s (%d byte)" % (path, sw))
    all_s = array.array("h")
    all_s.frombytes(raw)
    chans = [array.array("h", all_s[c::nch]) for c in range(nch)]
    return sr, nch, sw, n, chans


def load(path):
    """wav 는 그대로, ogg 는 ffmpeg 로 디코드해서 읽는다."""
    if path.lower().endswith(".wav"):
        return read_wav(path)
    tmp = os.path.join(tempfile.gettempdir(), "fs_audio_check.wav")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                        "-c:a", "pcm_s16le", tmp], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 디코드 실패: %s" % (r.stderr or r.stdout))
    try:
        return read_wav(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def stats(ch):
    n = len(ch)
    pk = 0
    acc = 0.0
    dc = 0.0
    clip = 0
    zc = 0
    prev = ch[0]
    for v in ch:
        a = v if v >= 0 else -v
        if a > pk:
            pk = a
        acc += float(v) * v
        dc += v
        if a >= 32767:
            clip += 1
        if (v >= 0) != (prev >= 0):
            zc += 1
        prev = v
    return {
        "peak": pk / 32768.0,
        "rms": math.sqrt(acc / n) / 32768.0,
        "dc": (dc / n) / 32768.0,
        "clip": clip,
        "zcr": zc / (n / 44100.0) if n else 0.0,
    }


def loudness(ch, win_ms=LOUD_WIN_MS):
    """100 ms 슬라이딩 창 RMS 의 최댓값과 그 창이 시작되는 시각."""
    n = len(ch)
    w = min(n, int(44100 * win_ms / 1000.0))
    acc = 0.0
    for i in range(w):
        acc += float(ch[i]) * ch[i]
    best, at = acc, 0
    for i in range(w, n):
        acc += float(ch[i]) * ch[i] - float(ch[i - w]) * ch[i - w]
        if acc > best:
            best, at = acc, i - w + 1
    return math.sqrt(best / w) / 32768.0, at / 44100.0


def tail_len(ch):
    """피크 대비 -40 dB 를 넘는 마지막 샘플까지의 길이 (실질 재생 길이)."""
    pk = max(abs(v) for v in ch) or 1
    thr = pk * (10.0 ** (-40.0 / 20.0))
    for i in range(len(ch) - 1, -1, -1):
        if abs(ch[i]) > thr:
            return (i + 1) / 44100.0
    return 0.0


def neighbor_delta_rms(ch, sample=200000):
    """이웃 샘플 사이 차분의 RMS. 이음매 불연속의 '기준자'."""
    n = len(ch)
    step = max(1, n // sample)
    acc = 0.0
    cnt = 0
    for i in range(0, n - 1, step):
        d = float(ch[i + 1] - ch[i])
        acc += d * d
        cnt += 1
    return math.sqrt(acc / cnt) if cnt else 0.0


def main():
    fails = []
    warns = []
    print("=" * 78)
    print("하늘다람쥐 오디오 수치 검증  (귀로 들은 것이 아니라 파형을 잰 결과다)")
    print("=" * 78)

    for rel, is_loop, exp_ch, tgt_rms, tol in TARGETS:
        path = os.path.join(AUD, rel.replace("/", os.sep))
        print("\n■ %s" % rel)
        if not os.path.exists(path):
            fails.append("%s : 파일 없음" % rel)
            print("   [실패] 파일이 없다")
            continue
        size = os.path.getsize(path)
        sr, nch, sw, n, chans = load(path)
        dur = n / float(sr)
        print("   포맷    : %d Hz / %d ch / %d bit / %.3f s / %s"
              % (sr, nch, sw * 8, dur, "%.1f KB" % (size / 1024.0)))

        if size < 1024:
            fails.append("%s : 파일 크기가 비정상 (%d B)" % (rel, size))
        if sr != 44100:
            fails.append("%s : 샘플레이트 %d" % (rel, sr))
        if nch != exp_ch:
            fails.append("%s : 채널 %d (기대 %d)" % (rel, nch, exp_ch))

        agg_peak = 0.0
        agg_rms_sq = 0.0
        for c, ch in enumerate(chans):
            st = stats(ch)
            agg_peak = max(agg_peak, st["peak"])
            agg_rms_sq += st["rms"] ** 2
            print("   ch%d     : peak %6.2f dBFS | RMS %6.2f dBFS | DC %+.5f | 클리핑 %d | 영점교차 %.0f/s"
                  % (c, dbfs(st["peak"]), dbfs(st["rms"]), st["dc"], st["clip"], st["zcr"]))
            if st["clip"] > 0:
                fails.append("%s ch%d : 클리핑 %d 샘플" % (rel, c, st["clip"]))
            if st["rms"] < 10.0 / 32768.0:
                fails.append("%s ch%d : 사실상 무음 (RMS %.1f dBFS)" % (rel, c, dbfs(st["rms"])))
            if st["peak"] > 10.0 ** (-1.0 / 20.0):
                fails.append("%s ch%d : 헤드룸 부족 (peak %.2f dBFS)" % (rel, c, dbfs(st["peak"])))
            if abs(st["dc"]) > 0.01:
                warns.append("%s ch%d : DC 오프셋 %+.4f" % (rel, c, st["dc"]))

        total_rms = math.sqrt(agg_rms_sq / nch)
        if tgt_rms is not None:
            d = dbfs(total_rms) - tgt_rms
            ok = abs(d) <= tol
            print("   레벨    : 전체 RMS %.2f dBFS (목표 %.1f, 편차 %+.2f dB) %s"
                  % (dbfs(total_rms), tgt_rms, d, "OK" if ok else "벗어남"))
            if not ok:
                fails.append("%s : RMS 목표 이탈 %+.2f dB" % (rel, d))

        if rel in ONESHOT_LOUDNESS:
            tr, tt = ONESHOT_LOUDNESS[rel]
            ld, at = loudness(chans[0])
            d = dbfs(ld) - tr
            ok = abs(d) <= tt
            print("   음량    : 100ms 창 최대 RMS %.2f dBFS @%.3f s (목표 %.1f, 편차 %+.2f dB) %s"
                  % (dbfs(ld), at, tr, d, "OK" if ok else "벗어남"))
            print("   여유    : 실질 길이 %.3f s | 크레스트 %.2f dB"
                  % (tail_len(chans[0]), dbfs(agg_peak) - dbfs(ld)))
            if not ok:
                fails.append("%s : 음량 목표 이탈 %+.2f dB" % (rel, d))

        # 시작/끝 샘플 - 원샷이 0 에서 시작해 0 으로 끝나는가
        for c, ch in enumerate(chans):
            first, last = ch[0], ch[-1]
            nd = neighbor_delta_rms(ch)
            if is_loop:
                seam = abs(float(last) - float(first))
                ratio = seam / nd if nd > 0 else 999.0
                verdict = "이음매 없음" if ratio <= 3.0 else ("주의" if ratio <= 6.0 else "이음매 들림")
                print("   ch%d 루프: 첫 %+6d / 끝 %+6d | 이음매 점프 %.1f LSB | 이웃 차분 RMS %.1f LSB"
                      "  -> 비율 %.2f  %s" % (c, first, last, seam, nd, ratio, verdict))
                if ratio > 6.0:
                    fails.append("%s ch%d : 루프 이음매 불연속 (비율 %.2f)" % (rel, c, ratio))
                elif ratio > 3.0:
                    warns.append("%s ch%d : 루프 이음매 비율 %.2f" % (rel, c, ratio))
            else:
                pk = max(abs(v) for v in ch) or 1
                fe = abs(first) / pk
                le = abs(last) / pk
                print("   ch%d 가장자리: 첫 %+d (피크의 %.3f%%) / 끝 %+d (%.3f%%)"
                      % (c, first, fe * 100.0, last, le * 100.0))
                if fe > 0.01 or le > 0.01:
                    fails.append("%s ch%d : 가장자리가 0 이 아니다 -> 클릭 위험" % (rel, c))

    print("\n" + "=" * 78)
    for w in warns:
        print("[주의] %s" % w)
    if fails:
        for f in fails:
            print("[실패] %s" % f)
        print("결과: 실패 %d 건" % len(fails))
        return 1
    print("결과: 통과 - 수치상 문제 없음")
    print("주의: 이것은 파형 측정 결과일 뿐이다. 실제로 어떻게 들리는지는 사람이 들어봐야 한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
