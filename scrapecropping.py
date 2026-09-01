import os
import re
import subprocess

from exceptions import FFmpegError, LocalLibraryError

class ScrapeCropping:
    """Determines each locally-owned mediaVersion's actual (top, bottom, left, right) cropping --
    pixel counts for the black bars around its actual content -- either from a manual cropping.txt
    override sitting alongside the media files (see __parseOverrideFile), or by auto-detecting them
    via ffmpeg's cropdetect filter, sampled in several bursts spread across the runtime and combined
    by taking the least black border found on each side independently (a first-pass aggregation, to
    be refined later). Only ever called for files belonging to titles that are both newly added this
    sync run and survived the scrape budget -- see main.py's syncLocal, same scope as
    ScrapeMediaInfo. Always run immediately after ScrapeMediaInfo.analyzeMediaVersion for the same
    file, so mediaVersion.duration/width/height are already known here -- no separate ffmpeg probe
    needed for them."""

    BURST_FRAME_COUNT = 200
    RUNTIME_PERCENTAGES = [5, 10, 15, 20, 25, 30, 40, 50, 70, 85]

    def __init__(self, ffmpeg_path):
        self.ffmpeg_path = ffmpeg_path

    def detectCropping(self, mediaDir, subdir, mediaVersion):
        """Sets mediaVersion.cropping to a list of (top, bottom, left, right) tuples -- normally
        just one, more than one only when a cropping.txt override supplies several (genuinely
        variable aspect ratio content, e.g. IMAX-expansion scenes)."""
        overridePath = os.path.join(mediaDir, subdir, "cropping.txt")
        if os.path.isfile(overridePath):
            overrides = self.__parseOverrideFile(overridePath)
            if mediaVersion.filename in overrides:
                mediaVersion.cropping = overrides[mediaVersion.filename]
                return
            if "OTHER" in overrides:
                mediaVersion.cropping = overrides["OTHER"]
                return

        filepath = os.path.join(mediaDir, subdir, mediaVersion.filename)
        readings = [self.__runBurst(filepath, mediaVersion.duration * pct / 100, mediaVersion.width, mediaVersion.height)
                    for pct in self.RUNTIME_PERCENTAGES]
        top = min(r[0] for r in readings)
        bottom = min(r[1] for r in readings)
        left = min(r[2] for r in readings)
        right = min(r[3] for r in readings)
        mediaVersion.cropping = [(top, bottom, left, right)]

    def __runBurst(self, filepath, seekSeconds, width, height):
        """Runs one cropdetect burst seeked to seekSeconds and returns (top, bottom, left, right),
        derived from the last (i.e. most-accumulated, see cropdetect's reset=0 default) x1/x2/y1/y2
        reading it printed."""
        args = [self.ffmpeg_path, "-ss", str(seekSeconds), "-i", filepath, "-vf", "cropdetect",
                 "-frames:v", str(self.BURST_FRAME_COUNT), "-f", "null", "-"]
        result = subprocess.run(args, capture_output=True, text=True)

        matches = re.findall(r"x1:(\d+) x2:(\d+) y1:(\d+) y2:(\d+)", result.stderr)
        if not matches:
            raise FFmpegError("no cropdetect reading found for " + filepath + " at t=" + str(seekSeconds) + "s" +
                               (" (ffmpeg exited with code " + str(result.returncode) + ")" if result.returncode != 0 else ""))
        x1, x2, y1, y2 = (int(v) for v in matches[-1])
        return y1, (height - 1) - y2, x1, (width - 1) - x2

    def __parseOverrideFile(self, filepath):
        """Returns {key: [(top, bottom, left, right), ...]} -- key is either a real filename or the
        literal "OTHER" (an explicit "OTHER:" line and a bare, colon-less line are equivalent; both
        accumulate into the same "OTHER" bucket, which applies to any file not explicitly keyed).
        Repeating the same key across multiple lines accumulates additional rows for that key rather
        than overwriting the previous one -- that's how a variable-aspect-ratio file ends up with
        more than one row."""
        with open(filepath, "r", encoding="utf8") as f:
            lines = f.read().splitlines()
        if len(lines) == 0:
            raise LocalLibraryError("empty cropping.txt: " + filepath)

        result = {}
        for line in lines:
            if line == "":
                raise LocalLibraryError("blank line in " + filepath)
            if ':' in line:
                key, _, valuePart = line.partition(':')
            else:
                key, valuePart = "OTHER", line
            values = valuePart.split(',')
            if len(values) != 4:
                raise LocalLibraryError("expected 4 comma-separated values (top,bottom,left,right) in " + filepath + ": " + line)
            try:
                top, bottom, left, right = (int(v) for v in values)
            except ValueError:
                raise LocalLibraryError("non-integer value in " + filepath + ": " + line)
            result.setdefault(key, []).append((top, bottom, left, right))
        return result
