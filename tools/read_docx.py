#!/usr/bin/env python3
"""
read_docx.py - docx 기획서에서 텍스트와 이미지를 순서대로 뽑아낸다.

docx 는 XML 을 담은 zip 이라 파이썬 표준 라이브러리만으로 읽을 수 있다.
(pandoc / LibreOffice / python-docx 전부 불필요)

핵심은 '순서'다. "주인공은 이렇게 생겼으면 좋겠어" 다음에 그림이 오면
그 그림이 어느 문장에 붙은 건지 알아야 하므로, 문단과 이미지를
문서에 나온 순서 그대로 출력한다.

사용:
    python tools/read_docx.py 기획서.docx
    python tools/read_docx.py 기획서.docx --out-dir tools/_docx
"""
import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "v": "urn:schemas-microsoft-com:vml",
}

W = f"{{{NS['w']}}}"
A = f"{{{NS['a']}}}"
R = f"{{{NS['r']}}}"
V = f"{{{NS['v']}}}"


def load_rels(z):
    """관계 ID -> 대상 파일 경로 (이미지 참조를 실제 파일로 잇는다)"""
    rels = {}
    try:
        root = ET.fromstring(z.read("word/_rels/document.xml.rels"))
    except KeyError:
        return rels
    for rel in root.findall("rel:Relationship", NS):
        rels[rel.get("Id")] = rel.get("Target")
    return rels


def para_style(p):
    """문단 스타일 이름 (Heading1 등)"""
    ppr = p.find(f"{W}pPr")
    if ppr is None:
        return None
    st = ppr.find(f"{W}pStyle")
    return st.get(f"{W}val") if st is not None else None


def is_list_item(p):
    ppr = p.find(f"{W}pPr")
    return ppr is not None and ppr.find(f"{W}numPr") is not None


def para_content(p, rels, media_map):
    """문단을 문서 순서대로 훑어 텍스트와 이미지를 함께 수집한다."""
    parts = []
    text_buf = []

    for el in p.iter():
        tag = el.tag
        # w:delText(삭제된 텍스트)는 일부러 제외 — w:t 만 잡는다
        if tag == f"{W}t":
            text_buf.append(el.text or "")
        elif tag == f"{W}tab":
            text_buf.append("\t")
        elif tag == f"{W}br":
            text_buf.append("\n")
        elif tag == f"{A}blip":
            rid = el.get(f"{R}embed") or el.get(f"{R}link")
            name = media_map.get(rels.get(rid, ""))
            if name:
                if text_buf:
                    parts.append(("text", "".join(text_buf)))
                    text_buf = []
                parts.append(("image", name))
        elif tag == f"{V}imagedata":  # 구형 워드 이미지
            rid = el.get(f"{R}id")
            name = media_map.get(rels.get(rid, ""))
            if name:
                if text_buf:
                    parts.append(("text", "".join(text_buf)))
                    text_buf = []
                parts.append(("image", name))

    if text_buf:
        parts.append(("text", "".join(text_buf)))
    return parts


def render_para(p, rels, media_map, out):
    parts = para_content(p, rels, media_map)
    if not parts:
        out.append("")
        return

    style = para_style(p) or ""
    m = re.match(r"(?:Heading|제목)\s*(\d)", style, re.I)
    prefix = ""
    if m:
        prefix = "#" * min(int(m.group(1)), 6) + " "
    elif is_list_item(p):
        prefix = "- "

    line = []
    for kind, val in parts:
        if kind == "text":
            line.append(val)
        else:
            line.append(f"\n[[이미지: {val}]]\n")

    text = "".join(line).strip()
    if text:
        out.append(prefix + text if prefix else text)


def render_table(tbl, rels, media_map, out):
    rows = tbl.findall(f"{W}tr")
    if not rows:
        return
    out.append("")
    for ri, tr in enumerate(rows):
        cells = []
        for tc in tr.findall(f"{W}tc"):
            buf = []
            for p in tc.findall(f"{W}p"):
                for kind, val in para_content(p, rels, media_map):
                    buf.append(val if kind == "text" else f"[[이미지: {val}]]")
            cells.append(" ".join(" ".join(buf).split()))
        out.append("| " + " | ".join(cells) + " |")
        if ri == 0:
            out.append("|" + "|".join([" --- "] * len(cells)) + "|")
    out.append("")


def main():
    # 윈도우 콘솔 기본 코드페이지(cp949)에서 한글이 깨지지 않도록
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    ap.add_argument("--out-dir", default=None,
                    help="추출물을 저장할 폴더 (기본: tools/_docx/<docx이름>/)")
    args = ap.parse_args()

    src = Path(args.docx)
    if not src.exists():
        print(f"파일을 찾을 수 없습니다: {src}", file=sys.stderr)
        return 2

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        # 기본값은 프로젝트 루트를 어지럽히지 않도록 tools/_docx/ 아래로
        out_dir = Path(__file__).resolve().parent / "_docx" / src.stem
    media_dir = out_dir / "media"
    if media_dir.exists():
        shutil.rmtree(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(src) as z:
        names = z.namelist()

        # 이미지 추출: zip 내부 경로 -> 저장한 파일명
        media_map = {}
        for n in names:
            if n.startswith("word/media/"):
                fname = Path(n).name
                (media_dir / fname).write_bytes(z.read(n))
                # 관계의 Target 은 "media/image1.png" 형태로 적힌다
                media_map[n[len("word/"):]] = fname
                media_map[n] = fname

        rels = load_rels(z)
        try:
            doc = ET.fromstring(z.read("word/document.xml"))
        except KeyError:
            print("word/document.xml 이 없습니다. 올바른 docx 가 맞습니까?", file=sys.stderr)
            return 2

    body = doc.find(f"{W}body")
    if body is None:
        print("문서 본문이 비어 있습니다.", file=sys.stderr)
        return 2

    out = []
    for child in body:
        if child.tag == f"{W}p":
            render_para(child, rels, media_map, out)
        elif child.tag == f"{W}tbl":
            render_table(child, rels, media_map, out)

    # 연속된 빈 줄 정리
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    md_path = out_dir / "본문.md"
    md_path.write_text(text, encoding="utf-8")

    imgs = sorted(media_dir.iterdir()) if media_dir.exists() else []
    print(f"=== 추출 완료: {src.name} ===")
    print(f"본문   : {md_path}  ({len(text)}자)")
    print(f"이미지 : {len(imgs)}개 -> {media_dir}")
    for p in imgs:
        print(f"   - {p.name}  ({p.stat().st_size:,} bytes)")
    print()
    print("=" * 70)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
