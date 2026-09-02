import os
import re
import subprocess

from exceptions import FFmpegError, LocalLibraryError, CroppingError

class ScrapeCropping:
    """Determines each locally-owned mediaVersion's actual (top, bottom, left, right) cropping --
    pixel counts for the black bars around its actual content -- either from a manual cropping.txt
    override sitting alongside the media files (see __parseOverrideFile), or by auto-detecting it
    via ffmpeg's cropdetect filter, sampled in several bursts spread across the runtime and reduced
    to one confident answer (see __deriveCropping) -- or raising CroppingError if the bursts don't
    actually support one, rather than silently guessing. Only ever called for files belonging to
    titles that are both newly added this sync run and survived the scrape budget -- see main.py's
    syncLocal, same scope as ScrapeMediaInfo. Always run immediately after
    ScrapeMediaInfo.analyzeMediaVersion for the same file, so mediaVersion.duration/width/height are
    already known here -- no separate ffmpeg probe needed for them."""

    def __init__(self, ffmpeg_path, burst_frame_count, runtime_percentages, cluster_tolerance,
                 symmetry_tolerance, minimum_cluster_size, windowboxing_tolerance, minimum_deviation):
        self.ffmpeg_path = ffmpeg_path
        self.burst_frame_count = burst_frame_count
        self.runtime_percentages = runtime_percentages
        self.cluster_tolerance = cluster_tolerance
        self.symmetry_tolerance = symmetry_tolerance
        self.minimum_cluster_size = minimum_cluster_size
        self.windowboxing_tolerance = windowboxing_tolerance
        self.minimum_deviation = minimum_deviation

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
                    for pct in self.runtime_percentages]
        mediaVersion.cropping = [self.__deriveCropping(readings, filepath)]

    def __runBurst(self, filepath, seekSeconds, width, height):
        """Runs one cropdetect burst seeked to seekSeconds and returns (top, bottom, left, right),
        derived from the last (i.e. most-accumulated, see cropdetect's reset=0 default) x1/x2/y1/y2
        reading it printed."""
        args = [self.ffmpeg_path, "-ss", str(seekSeconds), "-i", filepath, "-vf", "cropdetect",
                 "-frames:v", str(self.burst_frame_count), "-f", "null", "-"]
        result = subprocess.run(args, capture_output=True, text=True)

        matches = re.findall(r"x1:(\d+) x2:(\d+) y1:(\d+) y2:(\d+)", result.stderr)
        if not matches:
            raise FFmpegError("no cropdetect reading found for " + filepath + " at t=" + str(seekSeconds) + "s" +
                               (" (ffmpeg exited with code " + str(result.returncode) + ")" if result.returncode != 0 else ""))
        x1, x2, y1, y2 = (int(v) for v in matches[-1])
        return y1, (height - 1) - y2, x1, (width - 1) - x2

    def __deriveCropping(self, readings, filepath):
        """Reduces a list of (top, bottom, left, right) burst readings to one confident cropping
        result, or raises CroppingError rather than guessing when the bursts don't support one.

        1. Clusters the readings (see __clusterReadings) and takes the cluster with the smallest
           total border as the hypothesis -- its per-dimension minimum, safe to take now that
           clustering has already confirmed those readings represent the same underlying crop
           (unlike a global per-side minimum across all bursts, which could silently mix readings
           from genuinely different states together).
        2. Rejects the hypothesis outright if it doesn't look like a plausible crop on its own:
           meaningful bars on both axes at once (windowboxing), or asymmetric top/bottom or
           left/right.
        3. Rejects it if anything outside its cluster detected less cropping on any dimension (an
           expected detection error only ever means *more* incidental black in one frame, never
           less -- less black than the accepted result means something structurally different was
           actually visible there), or if any other cluster looks like a real, repeated alternate
           aspect ratio rather than a one-off glitch or noise -- enough mutually-agreeing members,
           roughly symmetric itself (a real alternate crop is symmetric; an asymmetric repeated
           reading is more likely a persistent artifact -- a watermark, boom mic, etc. -- than a
           second aspect ratio), and different enough from the hypothesis to be a meaningful
           difference rather than noise that happened to land just past cluster_tolerance."""
        clusters = self.__clusterReadings(readings)
        hypothesisCluster = min(clusters, key=lambda c: sum(self.__clusterRepresentative(c)))
        hypothesis = self.__clusterRepresentative(hypothesisCluster)

        self.__validateHypothesisShape(hypothesis, filepath)
        self.__validateAgainstOtherClusters(hypothesis, clusters, hypothesisCluster, filepath)

        return hypothesis

    def __clusterReadings(self, readings):
        """Groups readings where every dimension is within cluster_tolerance of the cluster's own
        running per-dimension minimum. Processed smallest-total-first, so each cluster naturally
        gets seeded by its own least-noisy (most trustworthy) member rather than an arbitrary one."""
        clusters = []
        for reading in sorted(readings, key=sum):
            for cluster in clusters:
                representative = self.__clusterRepresentative(cluster)
                if all(abs(reading[i] - representative[i]) <= self.cluster_tolerance for i in range(4)):
                    cluster.append(reading)
                    break
            else:
                clusters.append([reading])
        return clusters

    def __clusterRepresentative(self, cluster):
        return tuple(min(reading[i] for reading in cluster) for i in range(4))

    def __isSymmetric(self, reading):
        top, bottom, left, right = reading
        return abs(top - bottom) <= self.symmetry_tolerance and abs(left - right) <= self.symmetry_tolerance

    def __validateHypothesisShape(self, hypothesis, filepath):
        top, bottom, left, right = hypothesis
        hasVerticalBar = top > self.windowboxing_tolerance or bottom > self.windowboxing_tolerance
        hasHorizontalBar = left > self.windowboxing_tolerance or right > self.windowboxing_tolerance
        if hasVerticalBar and hasHorizontalBar:
            raise CroppingError("detected cropping has meaningful bars on both axes (top=" + str(top) +
                                 " bottom=" + str(bottom) + " left=" + str(left) + " right=" + str(right) +
                                 ") for " + filepath + " -- looks like windowboxed or otherwise unusual " +
                                 "content, needs a manual cropping.txt override")
        if not self.__isSymmetric(hypothesis):
            raise CroppingError("detected cropping is not symmetric (top=" + str(top) + " bottom=" + str(bottom) +
                                 " left=" + str(left) + " right=" + str(right) + ") for " + filepath +
                                 " -- needs a manual cropping.txt override")

    def __validateAgainstOtherClusters(self, hypothesis, clusters, hypothesisCluster, filepath):
        for cluster in clusters:
            if cluster is hypothesisCluster:
                continue
            for reading in cluster:
                if any(reading[i] < hypothesis[i] - self.cluster_tolerance for i in range(4)):
                    raise CroppingError("a burst detected less cropping than the accepted result (" + str(reading) +
                                         " vs accepted " + str(hypothesis) + ") for " + filepath +
                                         " -- needs a manual cropping.txt override")
            representative = self.__clusterRepresentative(cluster)
            isMeaningfullyDifferent = any(abs(representative[i] - hypothesis[i]) > self.minimum_deviation for i in range(4))
            if len(cluster) >= self.minimum_cluster_size and self.__isSymmetric(representative) and isMeaningfullyDifferent:
                raise CroppingError("a repeated alternate cropping (" + str(representative) +
                                     ", seen " + str(len(cluster)) + " times) was detected alongside the accepted " +
                                     "one (" + str(hypothesis) + ") for " + filepath + " -- this looks like " +
                                     "genuinely variable aspect ratio content, needs a manual cropping.txt override")

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
