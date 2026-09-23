# 用 faster-whisper 转写 B 站视频音频 (m4a -> 16k wav -> text)
# 用法: transcribe.py <audio.m4a> [--model small] [--out <txt路径>]
import argparse, os, subprocess, sys, tempfile

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--model", default="small")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    # 国内网络: 模型走 hf-mirror
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    wav = os.path.join(tempfile.gettempdir(), "taoge_asr_16k.wav")
    subprocess.run(["ffmpeg", "-y", "-i", args.audio, "-ar", "16000", "-ac", "1", "-f", "wav", wav],
                   check=True, capture_output=True)

    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(wav, language="zh", beam_size=5, vad_filter=True,
                                      initial_prompt="以下是A股股市复盘口播内容,涉及股票名称、板块、涨跌幅。")
    lines = []
    for seg in segments:
        line = seg.text.strip()
        if line:
            lines.append(line)
        print(f"[{seg.start:7.1f}s] {line}", flush=True)

    text = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"\nsaved: {args.out} ({len(text)} chars)", file=sys.stderr)

if __name__ == "__main__":
    main()
