import json
import os
import subprocess

from audiotrack import AudioTrack
from subtitletrack import SubtitleTrack
from exceptions import LocalLibraryError, MediaInfoError
from verbosity import printAlways

class ScrapeMediaInfo:
    """Runs the MediaInfo CLI over locally-owned mkv files and populates a MediaVersion's technical
    metadata (duration, mediainfo_version, video fields, audio/subtitle tracks) from its JSON
    output. Only ever called for files belonging to titles that are both newly added this sync run
    and survived the scrape budget -- see main.py's syncLocal."""

    def __init__(self, mediainfo_path):
        self.mediainfo_path = mediainfo_path

    def analyzeMediaVersion(self, mediaDir, subdir, mediaVersion):
        filepath = os.path.join(mediaDir, subdir, mediaVersion.filename)
        if not os.path.isfile(filepath):
            raise LocalLibraryError("file not found for MediaInfo analysis: " + filepath)

        result = subprocess.run([self.mediainfo_path, "--Output=JSON", filepath], capture_output=True, text=True)
        if result.returncode != 0:
            raise MediaInfoError("MediaInfo exited with code " + str(result.returncode) + " for " + filepath + ": " + result.stderr.strip())

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise MediaInfoError("MediaInfo produced malformed JSON for " + filepath + ": " + str(e))

        mediainfo_version = data.get("creatingLibrary", {}).get("version")
        if not mediainfo_version:
            raise MediaInfoError("MediaInfo JSON missing creatingLibrary.version for " + filepath)
        mediaVersion.mediainfo_version = mediainfo_version

        tracks = data.get("media", {}).get("track", [])
        generalTracks = [t for t in tracks if t.get("@type") == "General"]
        videoTracks = [t for t in tracks if t.get("@type") == "Video"]
        audioTracks = [t for t in tracks if t.get("@type") == "Audio"]
        textTracks = [t for t in tracks if t.get("@type") == "Text"]

        if len(generalTracks) != 1:
            raise MediaInfoError("expected exactly one General track for " + filepath + ", found " + str(len(generalTracks)))
        if len(videoTracks) != 1:
            raise MediaInfoError("expected exactly one Video track for " + filepath + ", found " + str(len(videoTracks)))

        general = generalTracks[0]
        video = videoTracks[0]

        generalDuration = float(self.__require(general, "Duration", filepath))
        videoDuration = float(self.__require(video, "Duration", filepath))
        if generalDuration - videoDuration > 2:
            raise LocalLibraryError("General.Duration (" + str(generalDuration) + "s) exceeds Video.Duration (" +
                                     str(videoDuration) + "s) by more than 2 seconds for " + filepath)

        for audioTrackData in audioTracks:
            audioDuration = float(self.__require(audioTrackData, "Duration", filepath))
            if videoDuration - audioDuration > 2:
                printAlways("WARNING: Video.Duration (" + str(videoDuration) + "s) exceeds Audio.Duration (" +
                      str(audioDuration) + "s) by more than 2 seconds for " + filepath +
                      " (audio track ID " + str(audioTrackData.get("ID")) + ")")

        mediaVersion.duration = round(generalDuration)

        mediaVersion.format = self.__require(video, "Format", filepath)
        mediaVersion.format_profile = video.get("Format_Profile")
        mediaVersion.format_level = video.get("Format_Level")
        mediaVersion.format_tier = video.get("Format_Tier")
        mediaVersion.multiview_count = self.__int_or_none(video.get("MultiView_Count"))
        mediaVersion.multiview_layout = video.get("MultiView_Layout")
        mediaVersion.hdr_format = video.get("HDR_Format")
        mediaVersion.hdr_format_version = video.get("HDR_Format_Version")
        mediaVersion.hdr_format_profile = video.get("HDR_Format_Profile")
        mediaVersion.hdr_format_level = video.get("HDR_Format_Level")
        mediaVersion.hdr_format_settings = video.get("HDR_Format_Settings")
        mediaVersion.hdr_format_compression = video.get("HDR_Format_Compression")
        mediaVersion.hdr_format_compatibility = video.get("HDR_Format_Compatibility")
        mediaVersion.variable_bitrate = self.__parseEnum(video.get("BitRate_Mode"), {"VBR": 1, "CBR": 0}, "BitRate_Mode", filepath)
        mediaVersion.bitrate = self.__int_or_none(video.get("BitRate"))
        mediaVersion.bitrate_maximum = self.__int_or_none(video.get("BitRate_Maximum"))
        mediaVersion.width = int(self.__require(video, "Width", filepath))
        mediaVersion.height = int(self.__require(video, "Height", filepath))
        mediaVersion.stored_width = self.__int_or_none(video.get("Stored_Width"))
        mediaVersion.stored_height = self.__int_or_none(video.get("Stored_Height"))
        mediaVersion.sampled_width = self.__int_or_none(video.get("Sampled_Width"))
        mediaVersion.sampled_height = self.__int_or_none(video.get("Sampled_Height"))
        mediaVersion.pixel_aspect_ratio = self.__float_or_none(video.get("PixelAspectRatio"))
        mediaVersion.display_aspect_ratio = self.__float_or_none(video.get("DisplayAspectRatio"))
        mediaVersion.variable_framerate = self.__parseEnum(video.get("FrameRate_Mode"), {"VFR": 1, "CFR": 0}, "FrameRate_Mode", filepath)
        mediaVersion.frame_rate = self.__float_or_none(video.get("FrameRate"))
        mediaVersion.frame_rate_num = self.__int_or_none(video.get("FrameRate_Num"))
        mediaVersion.frame_rate_den = self.__int_or_none(video.get("FrameRate_Den"))
        mediaVersion.color_space = video.get("ColorSpace")
        mediaVersion.chroma_subsampling = video.get("ChromaSubsampling")
        mediaVersion.chroma_subsampling_position = video.get("ChromaSubsampling_Position")
        mediaVersion.bit_depth = self.__int_or_none(video.get("BitDepth"))
        mediaVersion.scan_type = video.get("ScanType")
        mediaVersion.language = video.get("Language")
        mediaVersion.title = video.get("Title")
        mediaVersion.color_description_present = self.__parseEnum(video.get("colour_description_present"), {"Yes": 1, "No": 0}, "colour_description_present", filepath)
        mediaVersion.color_range = video.get("colour_range")
        mediaVersion.color_primaries = video.get("colour_primaries")
        mediaVersion.transfer_characteristics = video.get("transfer_characteristics")
        mediaVersion.matrix_coefficients = video.get("matrix_coefficients")
        mediaVersion.mastering_display_color_primaries = video.get("MasteringDisplay_ColorPrimaries")
        mediaVersion.mastering_display_luminance_min = self.__float_or_none(video.get("MasteringDisplay_Luminance_Min"))
        mediaVersion.mastering_display_luminance_max = self.__int_or_none(video.get("MasteringDisplay_Luminance_Max"))
        mediaVersion.max_cll = self.__int_or_none(video.get("MaxCLL"))
        mediaVersion.max_fall = self.__int_or_none(video.get("MaxFALL"))

        mediaVersion.audioTracks = [self.__buildAudioTrack(t, filepath) for t in audioTracks]
        mediaVersion.subtitleTracks = [self.__buildSubtitleTrack(t, filepath) for t in textTracks]

    def __buildAudioTrack(self, track, filepath):
        return AudioTrack(
            track_id=int(self.__require(track, "ID", filepath)),
            format=self.__require(track, "Format", filepath),
            format_commercial=track.get("Format_Commercial_IfAny"),
            format_settings_mode=track.get("Format_Settings_Mode"),
            format_additional_features=track.get("Format_AdditionalFeatures"),
            matrix_format=track.get("Matrix_Format"),
            variable_bitrate=self.__parseEnum(track.get("BitRate_Mode"), {"VBR": 1, "CBR": 0}, "BitRate_Mode", filepath),
            bitrate=self.__int_or_none(track.get("BitRate")),
            bitrate_maximum=self.__int_or_none(track.get("BitRate_Maximum")),
            channels=self.__int_or_none(track.get("Channels")),
            matrix_channels=self.__int_or_none(track.get("Matrix_Channels")), # unverified key name -- no real
                                                                               # matrixed-audio example seen yet
            channel_positions=track.get("ChannelPositions"),
            matrix_channel_positions=track.get("Matrix_ChannelPositions"),
            channel_layout=track.get("ChannelLayout"),
            sampling_rate=self.__int_or_none(track.get("SamplingRate")),
            bit_depth=self.__int_or_none(track.get("BitDepth")),
            lossless=self.__parseEnum(track.get("Compression_Mode"), {"Lossless": 1, "Lossy": 0}, "Compression_Mode", filepath),
            language=self.__require(track, "Language", filepath),
            title=track.get("Title"),
            default_track=self.__parseEnum(self.__require(track, "Default", filepath), {"Yes": 1, "No": 0}, "Default", filepath),
        )

    def __buildSubtitleTrack(self, track, filepath):
        return SubtitleTrack(
            track_id=int(self.__require(track, "ID", filepath)),
            format=self.__require(track, "Format", filepath),
            language=self.__require(track, "Language", filepath),
            title=track.get("Title"),
            default_track=self.__parseEnum(self.__require(track, "Default", filepath), {"Yes": 1, "No": 0}, "Default", filepath),
            forced_track=self.__parseEnum(self.__require(track, "Forced", filepath), {"Yes": 1, "No": 0}, "Forced", filepath),
        )

    def __require(self, track, key, filepath):
        value = track.get(key)
        if value is None:
            raise MediaInfoError("MediaInfo JSON missing required field '" + key + "' for " + filepath)
        return value

    def __int_or_none(self, value):
        return int(value) if value is not None else None

    def __float_or_none(self, value):
        return float(value) if value is not None else None

    def __parseEnum(self, value, mapping, fieldName, filepath):
        if value is None:
            return None
        if value not in mapping:
            raise MediaInfoError("unexpected " + fieldName + " value '" + value + "' for " + filepath)
        return mapping[value]
