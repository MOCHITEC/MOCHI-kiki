"""
script.md のナレーションを Azure AI Speech (TTS) で合成して
articles/.../video/audio/narration.m4a を生成する。

事前準備:
  Azure Portal で「音声サービス (Speech Service)」リソースを作成し、
  キーとリージョンを環境変数に設定する。

    export AZURE_SPEECH_KEY=...                     # Speech リソースのキー
    export AZURE_SPEECH_REGION=japaneast            # 例: japaneast / eastus / etc.

使い方:
  python3 scripts/synthesize_narration.py            # デフォルト声 (Nanami)
  python3 scripts/synthesize_narration.py --voice ja-JP-KeitaNeural
  python3 scripts/synthesize_narration.py --rate "+5%"   # 話速 +5%
  python3 scripts/synthesize_narration.py --ssml-only    # SSML だけ確認 (API 呼ばない)

出力:
  articles/.../video/audio/narration.mp3
  articles/.../video/audio/narration.m4a   (assemble_demo_video.py のデフォルト入力)

コスト目安:
  Azure Neural TTS は $16 / 1M characters。3 分尺 (約 1500 字) で $0.024 ≒ 4 円程度。

声 (主な日本語ニューラル):
  ja-JP-NanamiNeural    女性  明瞭でデモナレ向き (推奨)
  ja-JP-KeitaNeural     男性  落ち着いた業務トーン
  ja-JP-AoiNeural       女性  若い・会話寄り
  ja-JP-DaichiNeural    男性  カジュアル
  ja-JP-MayuNeural      女性  温かい
  ja-JP-NaokiNeural     男性  しっかり
  ja-JP-ShioriNeural    女性  明るい
  完全リスト: https://learn.microsoft.com/azure/ai-services/speech-service/language-support
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
VIDEO_DIR = REPO_ROOT / "articles/mochi-kiki-teams-agent/video"
SCRIPT_MD = VIDEO_DIR / "script.md"
OUT_DIR = VIDEO_DIR / "audio"
OUT_MP3 = OUT_DIR / "narration.mp3"
OUT_M4A = OUT_DIR / "narration.m4a"

DEFAULT_VOICE = "ja-JP-NanamiNeural"
DEFAULT_RATE = "medium"
BREAK_BETWEEN_SLIDES_MS = 1500

# script.md に「BGM のみ」等でナレーションが無いスライド向けのフォールバック。
# silencedetect での境界検出のため、全 14 スライドに何らかの音声を必ず持たせる。
DEFAULT_NARRATIONS = {
    13: "使用した Microsoft 技術は、以上の通りです。",
}


def parse_script_md(path: Path) -> dict[int, str]:
    """script.md から各スライドの 1 つ目の引用ブロック (> ...) を抽出。"""
    text = path.read_text(encoding="utf-8")
    narrations: dict[int, str] = {}
    parts = re.split(r"\n###\s+Slide\s+(\d+)\s*/[^\n]*\n", text)
    # parts[0] = ヘッダー部、以降 (num, content) のペア
    for i in range(1, len(parts), 2):
        try:
            slide_num = int(parts[i])
        except ValueError:
            continue
        content = parts[i + 1] if i + 1 < len(parts) else ""
        m = re.search(r"^>\s*(.+?)(?:\n\n|\n---|\Z)", content, flags=re.MULTILINE | re.DOTALL)
        if not m:
            continue
        narration = m.group(1).strip()
        # 改行統合 & マークダウン装飾の除去
        narration = re.sub(r"\n\s*>\s*", " ", narration)
        narration = re.sub(r"\n+", " ", narration)
        narration = re.sub(r"\*\*([^*]+)\*\*", r"\1", narration)
        narration = re.sub(r"\*([^*]+)\*", r"\1", narration)
        narration = re.sub(r"`([^`]+)`", r"\1", narration)
        narrations[slide_num] = narration.strip()
    return narrations


def escape_xml(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def build_ssml(
    narrations: dict[int, str], voice: str, rate: str, break_ms: int
) -> str:
    parts = []
    slide_numbers = sorted(narrations.keys())
    for i, num in enumerate(slide_numbers):
        text = escape_xml(narrations[num])
        parts.append(f'<prosody rate="{rate}">{text}</prosody>')
        if i < len(slide_numbers) - 1:
            parts.append(f'<break time="{break_ms}ms"/>')
    inner = "".join(parts)
    return (
        '<speak version="1.0" '
        'xmlns="http://www.w3.org/2001/10/synthesis" '
        'xml:lang="ja-JP">'
        f'<voice name="{voice}">{inner}</voice>'
        '</speak>'
    )


def call_azure_tts(ssml: str, key: str, region: str) -> bytes:
    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-48khz-192kbitrate-mono-mp3",
        "User-Agent": "mochi-kiki-demo-narration",
    }
    response = requests.post(
        url, headers=headers, data=ssml.encode("utf-8"), timeout=120
    )
    if response.status_code != 200:
        raise SystemExit(
            f"\nエラー: Azure Speech API status={response.status_code}\n"
            f"  {response.text[:500]}\n"
            f"  → AZURE_SPEECH_KEY / AZURE_SPEECH_REGION の値を確認してください。\n"
        )
    return response.content


def convert_to_m4a(mp3_path: Path, m4a_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(mp3_path),
            "-c:a", "aac", "-b:a", "192k",
            str(m4a_path),
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Azure AI Speech でナレーションを TTS 合成する",
    )
    parser.add_argument(
        "--voice", default=DEFAULT_VOICE,
        help=f"音声 (デフォルト: {DEFAULT_VOICE})",
    )
    parser.add_argument(
        "--rate", default=DEFAULT_RATE,
        help='話速。"slow" / "medium" / "fast" / "+5%" / "-10%" など (デフォルト: medium)',
    )
    parser.add_argument(
        "--break-ms", type=int, default=BREAK_BETWEEN_SLIDES_MS,
        help=f"スライド間の無音 (ms)。assemble 側の silencedetect で境界に使う (デフォルト: {BREAK_BETWEEN_SLIDES_MS})",
    )
    parser.add_argument("--script", default=str(SCRIPT_MD))
    parser.add_argument("--out-mp3", default=str(OUT_MP3))
    parser.add_argument("--out-m4a", default=str(OUT_M4A))
    parser.add_argument(
        "--no-m4a", action="store_true",
        help="m4a への変換をスキップ (mp3 のみ出力)",
    )
    parser.add_argument(
        "--ssml-only", action="store_true",
        help="SSML を標準出力に出すだけ (API は呼ばない)",
    )
    args = parser.parse_args()

    script_path = Path(args.script)
    if not script_path.exists():
        raise SystemExit(f"script.md が見つかりません: {script_path}")

    print(f"script.md から narration を抽出: {script_path}")
    narrations = parse_script_md(script_path)
    for slide_num, default in DEFAULT_NARRATIONS.items():
        if slide_num not in narrations:
            narrations[slide_num] = default
            print(f"  Slide {slide_num}: デフォルトを適用 ({default})")

    if not narrations:
        raise SystemExit("ナレーション抽出に失敗しました (script.md の構造を確認してください)")

    print(f"抽出スライド数: {len(narrations)}")
    total_chars = 0
    for num in sorted(narrations.keys()):
        snippet = narrations[num][:40].replace("\n", " ")
        ellip = "…" if len(narrations[num]) > 40 else ""
        print(f"  Slide {num:>2}: ({len(narrations[num]):>3}字) {snippet}{ellip}")
        total_chars += len(narrations[num])
    cost_usd = total_chars * 16 / 1_000_000
    print(f"\n合計文字数: {total_chars}  /  推定コスト: ${cost_usd:.4f} (Neural TTS $16/1M chars)")

    ssml = build_ssml(narrations, args.voice, args.rate, args.break_ms)

    if args.ssml_only:
        print("\n--- SSML ---")
        print(ssml)
        return

    key = os.environ.get("AZURE_SPEECH_KEY", "").strip()
    region = os.environ.get("AZURE_SPEECH_REGION", "").strip()
    if not key or not region:
        raise SystemExit(
            "\nエラー: 環境変数 AZURE_SPEECH_KEY / AZURE_SPEECH_REGION が設定されていません。\n"
            "  export AZURE_SPEECH_KEY=...\n"
            "  export AZURE_SPEECH_REGION=japaneast\n"
        )

    print(f"\nAzure Speech API 呼び出し中 (voice={args.voice}, region={region})...")
    audio_bytes = call_azure_tts(ssml, key, region)

    out_mp3 = Path(args.out_mp3)
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    out_mp3.write_bytes(audio_bytes)
    print(f"✓ MP3 出力: {out_mp3} ({len(audio_bytes) / 1024:.1f} KB)")

    if not args.no_m4a:
        out_m4a = Path(args.out_m4a)
        convert_to_m4a(out_mp3, out_m4a)
        print(f"✓ M4A 出力: {out_m4a} ({out_m4a.stat().st_size / 1024:.1f} KB)")

    print("\n次のステップ:")
    print("  python3 scripts/assemble_demo_video.py")
    print(f"  → {VIDEO_DIR / 'mochi-kiki-demo-video.mp4'} が生成される")


if __name__ == "__main__":
    main()
