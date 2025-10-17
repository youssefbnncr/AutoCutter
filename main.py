#!/usr/bin/env python3
import os
import sys
import subprocess
import importlib.util
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from shutil import which


# ---------------------------
#  Ensure tqdm available
# ---------------------------
def ensure_pip():
    """Try to ensure pip is available."""
    try:
        import ensurepip

        ensurepip.bootstrap()
        print("✅ pip bootstrapped via ensurepip.")
    except Exception as e:
        print(f"❌ Could not bootstrap pip: {e}")
        sys.exit("Please install pip (e.g. sudo apt install python3-pip) and re-run.")


def ensure_package(package_name):
    """Install a package via pip if it's missing."""
    if importlib.util.find_spec(package_name) is None:
        print(f"📦 Installing missing dependency: {package_name} ...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", package_name]
            )
        except subprocess.CalledProcessError:
            print("⚠️ pip not available or failed to install. Trying ensurepip...")
            ensure_pip()
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", package_name]
            )


ensure_package("tqdm")
from tqdm import tqdm


# ---------------------------
#  Small helpers
# ---------------------------
def print_bold(msg):
    print(f"\n\033[1m{msg}\033[0m")


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def safe_int_input(prompt, default):
    v = input(prompt).strip()
    if v == "":
        return default
    try:
        return int(v)
    except ValueError:
        print(f"Invalid input; using default {default}")
        return default


def choose_file(files, description):
    if not files:
        print_bold(f"No {description} files found.")
        return None
    if len(files) == 1:
        print_bold(f"Found one {description}: {os.path.basename(files[0])}")
        return files[0]
    print_bold(f"Multiple {description} files found:")
    for i, f in enumerate(files, 1):
        print(f"{i}. {os.path.basename(f)}")
    while True:
        try:
            sel = int(input(f"Select a {description} [1-{len(files)}]: ").strip()) - 1
            if 0 <= sel < len(files):
                return files[sel]
        except Exception:
            pass
        print("Invalid choice, try again.")


def check_ffmpeg_presence():
    if which("ffmpeg") is None or which("ffprobe") is None:
        print_bold("❌ ffmpeg/ffprobe not found in PATH.")
        print("Please install ffmpeg (e.g. sudo apt install ffmpeg) and re-run.")
        sys.exit(1)


def get_video_duration(path):
    """Return float seconds or None."""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if r.returncode != 0:
            return None
        return float(r.stdout.strip())
    except Exception:
        return None


def ffmpeg_has_encoder(name):
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return name in r.stdout
    except Exception:
        return False


# ---------------------------
#  Render worker
# ---------------------------
def render_segment(segment_info):
    """
    segment_info:
    (segment_index, duration, main_video, bg_video, music_file, output_path,
     codec, use_audio_loudnorm, log_dir)
    """
    (
        segment,
        duration,
        main_video,
        bg_video,
        music_file,
        output_path,
        codec,
        use_loudnorm,
        log_dir,
    ) = segment_info
    start_time = segment * duration

    # build command:
    # loop main 1 time (so always available) and loop music infinitely
    cmd = [
        "ffmpeg",
        "-y",
        # main video (loop shortly to ensure source covers clip)
        "-stream_loop",
        "1",
        "-i",
        main_video,
        # background (we will -ss relative to bg later using filter trim)
        "-ss",
        str(start_time),
        "-t",
        str(duration),
        "-i",
        bg_video,
        # music loop
        "-stream_loop",
        "-1",
        "-i",
        music_file,
        # filter complex: trim main to duration, process bg to portrait and overlay
        "-filter_complex",
        (
            f"[0:v]trim=duration={duration},setpts=PTS-STARTPTS,format=rgba[main];"
            f"[1:v]trim=duration={duration},setpts=PTS-STARTPTS,crop=ih*9/16:ih,scale=1080:1920[bg];"
            "[bg][main]overlay=(W-w)/2:(H-h)/2:shortest=1[v]"
        ),
        "-map",
        "[v]",
        # map audio from music (input index 2)
        "-map",
        "2:a",
        "-t",
        str(duration),
        "-c:v",
        codec,
        "-b:v",
        "3500k",
        "-pix_fmt",
        "yuv420p",
    ]

    # audio normalization (optional)
    if use_loudnorm:
        # apply loudnorm on output audio
        cmd += ["-af", "loudnorm=I=-16:LRA=11:TP=-1.5"]
        # set aac audio codec
        cmd += ["-c:a", "aac"]
    else:
        # simple aac encode
        cmd += ["-c:a", "aac"]

    cmd += [output_path]

    # prepare per-clip log file
    clip_name = os.path.basename(output_path)
    log_path = os.path.join(log_dir, f"{clip_name}.log")
    try:
        with open(log_path, "w", encoding="utf-8") as logf:
            logf.write("COMMAND:\n" + " ".join(cmd) + "\n\n")
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            logf.write(proc.stdout)
            if proc.returncode != 0:
                # return last 20 lines of log for summary
                tail = "\n".join(proc.stdout.splitlines()[-20:])
                return f"❌ {clip_name} failed (log: {log_path}). Last lines:\n{tail}"
            return f"✅ {clip_name} rendered (log: {log_path})"
    except Exception as e:
        return f"❌ {clip_name} failed to run ffmpeg: {e}"


# ---------------------------
#  Main flow
# ---------------------------
def main():
    check_ffmpeg_presence()

    # folders
    folders = {
        "main": "main",
        "background": "background",
        "music": "music",
        "rendered": "rendered",
    }
    for p in folders.values():
        ensure_dir(p)

    # choose main video
    main_candidates = [
        os.path.join(folders["main"], f)
        for f in os.listdir(folders["main"])
        if f.lower().endswith((".mp4", ".mov", ".mkv"))
    ]
    main_video = choose_file(main_candidates, "main video") or sys.exit(
        "❌ No main video found in ./main"
    )

    # choose music
    music_candidates = [
        os.path.join(folders["music"], f)
        for f in os.listdir(folders["music"])
        if f.lower().endswith((".mp3", ".wav", ".aac", ".m4a"))
    ]
    music_file = choose_file(music_candidates, "music file") or sys.exit(
        "❌ No music found in ./music"
    )

    # background videos
    background_candidates = [
        os.path.join(folders["background"], f)
        for f in os.listdir(folders["background"])
        if f.lower().endswith((".mp4", ".mov", ".mkv"))
    ]
    if not background_candidates:
        sys.exit("❌ No background videos found in ./background")

    # session folder
    session_name = datetime.now().strftime("session_%Y-%m-%d_%H-%M-%S")
    session_dir = os.path.join(folders["rendered"], session_name)
    ensure_dir(session_dir)
    log_dir = os.path.join(session_dir, "logs")
    ensure_dir(log_dir)
    print_bold(f"🗂️  Session folder created: {session_dir}")

    # detect main duration
    main_duration = get_video_duration(main_video)
    if main_duration is None:
        sys.exit("❌ Could not detect main video duration.")
    print_bold(f"Detected main video duration: {round(main_duration, 2)} seconds")

    desired_duration = safe_int_input(
        f"Enter desired clip length in seconds (default {int(main_duration)}): ",
        int(main_duration),
    )
    print_bold(f"Each clip will be {desired_duration} seconds long")

    # parallelism
    default_workers = max(1, os.cpu_count() or 2)
    workers = safe_int_input(
        f"Number of parallel workers (default {default_workers}): ", default_workers
    )
    workers = max(1, min(workers, (os.cpu_count() or default_workers)))

    # GPU option detection
    have_nvenc = ffmpeg_has_encoder("h264_nvenc")
    use_gpu = False
    if have_nvenc:
        use_gpu = (
            input("h264_nvenc encoder detected. Use GPU encoding? (y/N): ")
            .strip()
            .lower()
            == "y"
        )
    else:
        if (
            input("Use GPU encoding (nvenc)? (recommended 'N' if uncertain) (y/N): ")
            .strip()
            .lower()
            == "y"
        ):
            print("⚠️ NVENC encoder not detected in ffmpeg; falling back to CPU x264.")
    codec = "h264_nvenc" if use_gpu and have_nvenc else "libx264"

    # audio normalization
    use_loudnorm = (
        input("Apply audio normalization (loudnorm)? (y/N): ").strip().lower() == "y"
    )

    # make_all mode
    make_all = (
        input("Make all possible clips for each background video? (y/N): ")
        .strip()
        .lower()
        == "y"
    )

    # build tasks
    tasks = []
    for bg in background_candidates:
        bg_dur = get_video_duration(bg)
        if bg_dur is None:
            print_bold(f"⚠️ Skipping {bg}: duration unreadable")
            continue
        max_segments = int(bg_dur // desired_duration)
        if max_segments <= 0:
            print_bold(
                f"⚠️ {os.path.basename(bg)} is shorter than desired clip length; skipping"
            )
            continue
        print_bold(f"{os.path.basename(bg)} → {max_segments} available segments")
        if make_all:
            count = max_segments
        else:
            count = safe_int_input(
                f"How many clips to render from {os.path.basename(bg)} (max {max_segments}, default {max_segments}): ",
                max_segments,
            )
            count = max(0, min(count, max_segments))
        for seg in range(count):
            outname = f"{os.path.splitext(os.path.basename(bg))[0]}_{desired_duration}s_clip{seg + 1:02d}.mp4"
            outpath = os.path.join(session_dir, outname)
            tasks.append(
                (
                    seg,
                    desired_duration,
                    main_video,
                    bg,
                    music_file,
                    outpath,
                    codec,
                    use_loudnorm,
                    log_dir,
                )
            )

    if not tasks:
        sys.exit("❌ No clips selected for rendering. Exiting.")

    # render in parallel with overall tqdm progress
    print_bold(
        f"🚀 Starting rendering with {workers} worker(s). Codec: {codec}. Loudnorm: {use_loudnorm}"
    )
    results = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(render_segment, t) for t in tasks]
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Rendering progress",
            unit="clip",
        ):
            try:
                results.append(future.result())
            except Exception as e:
                results.append(f"❌ Worker exception: {e}")

    # write summary
    summary_file = os.path.join(session_dir, "summary.txt")
    with open(summary_file, "w", encoding="utf-8") as sf:
        sf.write(f"Session: {session_name}\n")
        sf.write(
            f"Main video: {main_video}\nMusic: {music_file}\nCodec: {codec}\nLoudnorm: {use_loudnorm}\n\n"
        )
        sf.write("Results:\n")
        for r in results:
            sf.write(r + "\n")

    print_bold("\n🎉 Rendering completed. Summary:")
    for r in results:
        print(r)

    print_bold(f"\n✅ All outputs in: {session_dir}")
    print(f"📝 Summary saved: {summary_file}")

    # optional merge
    if input("Merge all rendered clips into one file? (y/N): ").strip().lower() == "y":
        concat_list = os.path.join(session_dir, "concat.txt")
        # list only mp4 files in session_dir (sorted)
        mp4s = sorted(
            [f for f in os.listdir(session_dir) if f.lower().endswith(".mp4")]
        )
        if not mp4s:
            print("No mp4 clips found to merge.")
        else:
            with open(concat_list, "w", encoding="utf-8") as cf:
                for m in mp4s:
                    cf.write(f"file '{os.path.join(session_dir, m)}'\n")
            merged = os.path.join(session_dir, "final_merged.mp4")
            print_bold("Merging clips (ffmpeg concat)... this may take a while.")
            merge_cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list,
                "-c",
                "copy",
                merged,
            ]
            mproc = subprocess.run(
                merge_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            if mproc.returncode != 0:
                print_bold(f"❌ Merge failed. See ffmpeg output below:\n{mproc.stdout}")
            else:
                print_bold(f"✅ Merged file created: {merged}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")
        sys.exit(1)
