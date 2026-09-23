# 批量转写 downloads/audio/*.m4a -> downloads/txt/<bvid>.txt (可断点续跑)
# 进度写 downloads/transcribe.log; 完成时写 downloads/transcribe.done
# 用法: batch_transcribe.py [model] [out_dir_name]   如: batch_transcribe.py medium txt_medium
import os, sys, time, glob, subprocess, tempfile, json

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
BASE = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE, "downloads", "audio")
MODEL = sys.argv[1] if len(sys.argv) > 1 else "small"
OUT_NAME = sys.argv[2] if len(sys.argv) > 2 else "txt"
TXT_DIR = os.path.join(BASE, "downloads", OUT_NAME)
LOG = os.path.join(BASE, "downloads", f"transcribe_{OUT_NAME}.log")
DONE_FILE = os.path.join(BASE, "downloads", f"transcribe_{OUT_NAME}.done")
os.makedirs(TXT_DIR, exist_ok=True)

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def main():
    model_size = sys.argv[1] if len(sys.argv) > 1 else "small"
    files = sorted(glob.glob(os.path.join(AUDIO_DIR, "*.m4a")))
    todo = [f for f in files if not os.path.exists(os.path.join(TXT_DIR, os.path.basename(f).replace(".m4a", ".txt")))]
    log(f"total={len(files)} todo={len(todo)} model={MODEL} out={OUT_NAME}")
    if not todo:
        open(DONE_FILE, "w").write("done")
        return

    log("loading model...")
    from faster_whisper import WhisperModel
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    log("model loaded")

    wav = os.path.join(tempfile.gettempdir(), "taoge_batch_16k.wav")
    t0 = time.time()
    for i, audio in enumerate(todo):
        bvid = os.path.basename(audio).replace(".m4a", "")
        try:
            subprocess.run(["ffmpeg", "-y", "-i", audio, "-ar", "16000", "-ac", "1", "-f", "wav", wav],
                           check=True, capture_output=True)
            segments, info = model.transcribe(
                wav, language="zh", beam_size=5, vad_filter=True,
                initial_prompt="以下是A股股市复盘口播内容,涉及股票名称、板块、涨跌幅、涨停、跌停、换手率。")
            lines = [s.text.strip() for s in segments if s.text.strip()]
            with open(os.path.join(TXT_DIR, bvid + ".txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            el = time.time() - t0
            log(f"{i+1}/{len(todo)} {bvid} ok chars={sum(len(x) for x in lines)} dur={info.duration:.0f}s elapsed={el/60:.1f}min")
        except Exception as e:
            log(f"{i+1}/{len(todo)} {bvid} FAIL {e}")
    open(DONE_FILE, "w").write("done")
    log("ALL DONE")

if __name__ == "__main__":
    main()
