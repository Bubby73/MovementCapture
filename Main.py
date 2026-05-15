import cv2
import argparse
import sys
import os
import shutil
import subprocess
import tempfile
 
 
def parse_args():
    parser = argparse.ArgumentParser(description="Motion-only video display")
    parser.add_argument(
        "--source",
        default="0",
        help="Camera index (0, 1, ...) or path to a video file"
    )
    parser.add_argument(
        "--export",
        nargs="?",
        const="processed_output.mp4",
        default=None,
        help="Export the processed video to a file. Optionally provide an output path."
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=4,
        help="Pixel difference threshold (1–255, default 4). Lower = more sensitive."
    )
    return parser.parse_args()
 
 
def open_source(source_str):
    """Try to open source as an integer (camera) first, then as a file path."""
    try:
        return cv2.VideoCapture(int(source_str))
    except ValueError:
        return cv2.VideoCapture(source_str)
 

def reencode_with_ffmpeg(src_path):
    """Re-encode the given video file using ffmpeg to H.264 (libx264).
    Replaces the source file on success. Skips if ffmpeg isn't available.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found; skipping re-encode.")
        return False

    dirn = os.path.dirname(src_path) or "."
    try:
        fd, tmp = tempfile.mkstemp(suffix=".mp4", dir=dirn)
        os.close(fd)
    except Exception:
        tmp = src_path + ".reencoded.mp4"

    cmd = [
        ffmpeg,
        "-y",
        "-i",
        src_path,
        "-c:v",
        "libx264",
        "-crf",
        "23",
        "-preset",
        "medium",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        tmp,
    ]

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except Exception as e:
        print(f"ffmpeg run failed: {e}")
        if os.path.exists(tmp) and tmp != src_path:
            try:
                os.remove(tmp)
            except Exception:
                pass
        return False

    if proc.returncode == 0:
        try:
            os.replace(tmp, src_path)
        except Exception:
            print("Re-encode succeeded but failed to replace original file.")
            return False
        print(f"Re-encoded and replaced: {src_path}")
        return True
    else:
        print("ffmpeg re-encode failed:")
        print(proc.stderr)
        if os.path.exists(tmp) and tmp != src_path:
            try:
                os.remove(tmp)
            except Exception:
                pass
        return False

 
def main():
    args = parse_args()
    threshold = max(1, min(254, args.threshold))
    use_blur = True
    use_dilate = False
    filter_enabled = True
    invert_filter = False
    display_modes = ["colour", "white", "greyscale"]
    display_mode_index = 0
 
    cap = open_source(args.source)
    if not cap.isOpened():
        print(f"Error: could not open source '{args.source}'")
        sys.exit(1)
 
    export_path = args.export
    writer = None
    export_ready = False
    export_fps = cap.get(cv2.CAP_PROP_FPS)
    if not export_fps or export_fps <= 0:
        export_fps = 30.0
    export_size = (
        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    )
    if export_size[0] > 0 and export_size[1] > 0:
        export_ready = True
    elif export_path:
        print("Warning: could not determine video size for export")

    prev_gray = None

    # Determine screen size for dynamic scaling of the preview window.
    try:
        import ctypes
        user32 = ctypes.windll.user32
        screen_width = user32.GetSystemMetrics(0)
        screen_height = user32.GetSystemMetrics(1)
    except Exception:
        screen_width, screen_height = 1920, 1080
    screen_margin = 100  # leave room for taskbar/OS chrome
 
    print("Motion display running.")
    print("  Q/Esc  — quit")
    print("  +/-    — adjust sensitivity threshold")
    print("  B      — toggle blur (noise reduction)")
    print("  D      — toggle dilate (thicken motion)")
    print("  C      — cycle display mode (colour/white/greyscale)")
    print("  F      — toggle motion filter on/off")
    print("  I      — invert filter mask (motion/non-motion)")
    if export_path:
        print("  E      — start/stop export using the current live settings")
        print(f"  Export file: {export_path}")
 
    while True:
        ret, frame = cap.read()
        if not ret:
            # End of video file — loop back or exit
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            prev_gray = None
            continue
 
        # Convert to greyscale — diff only needs luminance
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
 
        if use_blur:
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
 
        if prev_gray is None:
            prev_gray = gray
            continue
 
        # Absolute per-pixel difference from previous frame
        diff = cv2.absdiff(prev_gray, gray)
 
        # Threshold: pixels that changed enough become white, rest black
        _, motion_mask = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
 
        if use_dilate:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            motion_mask = cv2.dilate(motion_mask, kernel, iterations=1)

        active_mask = cv2.bitwise_not(motion_mask) if invert_filter else motion_mask
 
        # Render output using selected display mode, or bypass filtering.
        mode = display_modes[display_mode_index]
        if filter_enabled:
            if mode == "colour":
                output = cv2.bitwise_and(frame, frame, mask=active_mask)
            elif mode == "white":
                output = cv2.cvtColor(active_mask, cv2.COLOR_GRAY2BGR)
            else:  # greyscale
                motion_gray = cv2.bitwise_and(gray, gray, mask=active_mask)
                output = cv2.cvtColor(motion_gray, cv2.COLOR_GRAY2BGR)
        else:
            output = frame.copy()
 
        # Overlay threshold value on screen (on original-resolution output)
        status = (
            f"Threshold: {threshold}  Blur: {'on' if use_blur else 'off'}  "
            f"Dilate: {'on' if use_dilate else 'off'}  "
            f"Filter: {'on' if filter_enabled else 'off'}  "
            f"Invert: {'on' if invert_filter else 'off'}  Mode: {mode}  "
            f"Export: {'on' if writer is not None else 'off'}"
        )
        cv2.putText(output, status, (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1, cv2.LINE_AA)

        # Write original-resolution frame to file if exporting
        if writer is not None:
            writer.write(output)

        # Compute scale for display only (don't affect exported frame)
        h, w = output.shape[:2]
        max_w = screen_width
        max_h = max(100, screen_height - screen_margin)
        scale = min(1.0, max_w / float(w), max_h / float(h))
        if scale < 1.0:
            disp_w = int(w * scale)
            disp_h = int(h * scale)
            display_frame = cv2.resize(output, (disp_w, disp_h), interpolation=cv2.INTER_AREA)
        else:
            display_frame = output

        cv2.imshow("Motion Only (Q to quit)", display_frame)
 
        prev_gray = gray
 
        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):  # Q or Esc
            break
        elif key in (ord('+'), ord('=')):
            threshold = min(254, threshold + 2)
        elif key == ord('-'):
            threshold = max(1, threshold - 2)
        elif key == ord('b'):
            use_blur = not use_blur
            prev_gray = None  # reset so a blur change doesn't cause a flash
        elif key == ord('d'):
            use_dilate = not use_dilate
        elif key in (ord('c'), ord('C')):
            display_mode_index = (display_mode_index + 1) % len(display_modes)
        elif key in (ord('f'), ord('F')):
            filter_enabled = not filter_enabled
        elif key in (ord('i'), ord('I')):
            invert_filter = not invert_filter
        elif key in (ord('e'), ord('E')) and export_path:
            if writer is None:
                if not export_ready:
                    print("Warning: export is not available because the video size could not be determined.")
                else:
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(export_path, fourcc, export_fps, export_size)
                    if writer.isOpened():
                        print(f"Export started: {export_path}")
                    else:
                        print(f"Warning: could not open export file '{export_path}'")
                        writer = None
            else:
                writer.release()
                writer = None
                print("Export stopped.")
                if export_path:
                    reencode_with_ffmpeg(export_path)
 
    cap.release()
    if writer is not None:
        writer.release()
        if export_path:
            reencode_with_ffmpeg(export_path)
    cv2.destroyAllWindows()
    print("Done.")
 
 
if __name__ == "__main__":
    main()
