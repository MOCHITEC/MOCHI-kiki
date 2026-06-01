"""
ナレーション音声 1 本 + PDF スライドから MP4 を組み立てる。

スライド境界の決定方法:
  1. articles/.../video/audio/timings.txt があれば、その時刻を使う (1 行 1 浮動小数、秒)
  2. なければ ffmpeg の silencedetect でスライド数 - 1 個の境界を自動検出

使い方:
  # 1. PowerPoint/Keynote から articles/.../video/mochi-kiki-demo-deck.pdf を最新化
  # 2. 1 本の通しナレーションを録音し articles/.../video/audio/narration.m4a に置く
  #    (スライド境界では 1〜2 秒の無音を入れて録音すると自動検出が効きやすい)
  # 3. python scripts/assemble_demo_video.py
  # 4. articles/.../video/mochi-kiki-demo-video.mp4 が出力される

オプション:
  --audio PATH        音声ファイル (デフォルト: video/audio/narration.m4a)
  --pdf PATH          PDF (デフォルト: video/mochi-kiki-demo-deck.pdf)
  --timings PATH      手動タイミング (デフォルト: video/audio/timings.txt)
  --out PATH          出力 MP4 (デフォルト: video/mochi-kiki-demo-video.mp4)
  --noise-db N        silencedetect の閾値 dB (デフォルト: -30)
  --min-silence N     無音判定の最小秒 (デフォルト: 0.6)
  --detect-only       境界検出して秒数だけ出力 (組み立てはしない)
  --fps N             出力 fps (デフォルト: 30)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
VIDEO_DIR = REPO_ROOT / "articles/mochi-kiki-teams-agent/video"

DEFAULT_AUDIO = VIDEO_DIR / "audio/narration.m4a"
DEFAULT_PDF = VIDEO_DIR / "mochi-kiki-demo-deck.pdf"
DEFAULT_TIMINGS = VIDEO_DIR / "audio/timings.txt"
DEFAULT_OUT = VIDEO_DIR / "mochi-kiki-demo-video.mp4"

# 1920×1080 を直接得るための pdftoppm dpi (10in × 5.625in @ 192dpi = 1920×1080)
PDF_DPI = 192
WIDTH, HEIGHT = 1920, 1080


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def get_audio_duration(audio: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio),
        ],
        text=True,
    )
    return float(out.strip())


def detect_silence_boundaries(
    audio: Path, n_boundaries: int, noise_db: float, min_silence: float
) -> List[float]:
    """
    ffmpeg silencedetect で無音区間を抽出。
    最も長い n_boundaries 個を境界候補として、中点をスライド境界の秒として返す。
    """
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats",
            "-i", str(audio),
            "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    starts: list[float] = []
    ends: list[float] = []
    for line in proc.stderr.splitlines():
        m = re.search(r"silence_start: ([\d.]+)", line)
        if m:
            starts.append(float(m.group(1)))
            continue
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m:
            ends.append(float(m.group(1)))

    pairs: list[Tuple[float, float]] = list(zip(starts, ends))
    if len(pairs) < n_boundaries:
        raise SystemExit(
            f"\nエラー: 検出した無音区間 {len(pairs)} 個 < 必要境界数 {n_boundaries}\n"
            f"  → 録音時にスライド間 1〜2 秒の無音を入れてください。\n"
            f"  → または --noise-db を上げる (-20 など)、--min-silence を下げる (0.4) など。\n"
            f"  → または手動タイミング {DEFAULT_TIMINGS} を作成してください (1 行 1 秒)。\n"
        )

    pairs.sort(key=lambda p: p[1] - p[0], reverse=True)
    chosen = pairs[:n_boundaries]
    boundaries = sorted((s + e) / 2 for s, e in chosen)
    return boundaries


def parse_timings(path: Path, expected_n: int) -> List[float]:
    raw = path.read_text(encoding="utf-8").strip().splitlines()
    values: list[float] = []
    for line in raw:
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        values.append(float(line))
    if len(values) != expected_n:
        raise SystemExit(
            f"\nエラー: timings.txt の有効行数 {len(values)} ≠ スライド数 {expected_n}\n"
            f"  → ファイル: {path}\n"
        )
    return values


def render_pdf(pdf: Path, out_dir: Path) -> List[Path]:
    run([
        "pdftoppm", "-png",
        "-rx", str(PDF_DPI), "-ry", str(PDF_DPI),
        str(pdf), str(out_dir / "slide"),
    ])
    return sorted(out_dir.glob("slide-*.png"))


def build_video(
    slide_pngs: List[Path],
    slide_starts: List[float],
    slide_ends: List[float],
    audio: Path,
    out: Path,
    work_dir: Path,
    fps: int,
) -> None:
    concat_lines: list[str] = []
    for png, s, e in zip(slide_pngs, slide_starts, slide_ends):
        duration = max(e - s, 0.1)
        concat_lines.append(f"file '{png.as_posix()}'")
        concat_lines.append(f"duration {duration:.3f}")
    # concat demuxer の仕様: 末尾は同じファイルをもう 1 度書く (duration なし)
    concat_lines.append(f"file '{slide_pngs[-1].as_posix()}'")

    concat_path = work_dir / "concat.txt"
    concat_path.write_text("\n".join(concat_lines), encoding="utf-8")

    out.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y", "-hide_banner",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-i", str(audio),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        # pdftoppm の丸め誤差で height=1081 になることがあるので 1920x1080 に強制
        "-vf", f"scale={WIDTH}:{HEIGHT}:flags=lanczos,fps={fps},format=yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(out),
    ])


def fmt_seconds(s: float) -> str:
    m = int(s // 60)
    sec = s - m * 60
    return f"{m:01d}:{sec:05.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="narration.m4a + PDF を MP4 に組み立てる",
    )
    parser.add_argument("--audio", default=str(DEFAULT_AUDIO))
    parser.add_argument("--pdf", default=str(DEFAULT_PDF))
    parser.add_argument("--timings", default=str(DEFAULT_TIMINGS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--noise-db", type=float, default=-30.0)
    parser.add_argument("--min-silence", type=float, default=0.6)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--detect-only", action="store_true",
        help="境界検出して秒数を出力するだけ (組み立てはしない)",
    )
    args = parser.parse_args()

    audio = Path(args.audio)
    pdf = Path(args.pdf)
    timings_path = Path(args.timings)
    out = Path(args.out)

    if not audio.exists():
        raise SystemExit(f"音声ファイルがありません: {audio}\n  → 録音して上記パスに置いてください。")
    if not pdf.exists():
        raise SystemExit(f"PDF がありません: {pdf}\n  → build_deck.js で先に生成してください。")

    duration = get_audio_duration(audio)
    print(f"音声長: {fmt_seconds(duration)} ({duration:.2f}s)")

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        print(f"PDF を {PDF_DPI}dpi で {WIDTH}×{HEIGHT} 相当に展開...")
        slide_pngs = render_pdf(pdf, tmp)
        n_slides = len(slide_pngs)
        print(f"スライド数: {n_slides}")

        if timings_path.exists():
            print(f"手動タイミングを使用: {timings_path}")
            slide_starts = parse_timings(timings_path, n_slides)
        else:
            print(f"無音検出 (noise={args.noise_db}dB, min={args.min_silence}s)...")
            boundaries = detect_silence_boundaries(
                audio, n_slides - 1, args.noise_db, args.min_silence
            )
            slide_starts = [0.0] + boundaries

        slide_ends = slide_starts[1:] + [duration]

        print("\n境界マップ:")
        print(f"  {'Slide':>6} {'Start':>9} {'End':>9} {'Dur':>7}")
        for i, (s, e) in enumerate(zip(slide_starts, slide_ends), start=1):
            print(f"  {i:>6} {fmt_seconds(s):>9} {fmt_seconds(e):>9} {e - s:>6.2f}s")

        if args.detect_only:
            print("\n--detect-only のため組み立てはスキップ。")
            return

        print("\n動画組み立て中 (ffmpeg)...")
        build_video(
            slide_pngs, slide_starts, slide_ends, audio, out, tmp, args.fps
        )

    print(f"\n✓ 完成: {out}")
    print(f"  サイズ: {out.stat().st_size / (1024 * 1024):.1f} MB")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\nエラー: コマンドが失敗しました ({e.cmd})", file=sys.stderr)
        sys.exit(1)
