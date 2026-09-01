from sourceparser import parseSourceString

class MediaVersion:

    def __init__(self, filename, source, version):

        self.filename = filename
        self.source = source # raw "src-..." string, kept for reference alongside the parsed form
        self.version = version
        self.sources = parseSourceString(source) # list of MediaSource, one per leaf source

        # everything below is populated by ScrapeMediaInfo.analyzeMediaVersion, once this version's
        # file is about to be added to the DB (only ever run for newly-added, budget-surviving
        # titles -- see main.py's syncLocal); None/empty until then. Unless it's Kaleidescape-only
        # (see isKaleidescapeOnly): there's no local file for ScrapeMediaInfo to analyze, so all of
        # it just stays None -- duration/width/height are instead meant to come from a future online
        # Kaleidescape scraper, not yet implemented

        self.duration = None # General.Duration, rounded to whole seconds
        self.mediainfo_version = None # creatingLibrary.version

        # video -- a file has exactly one video track, so this lives directly on MediaVersion
        # rather than a separate one-to-one child table (see media_audio_tracks/media_subtitle_tracks
        # for the genuinely one-to-many track types)
        self.format = None
        self.format_profile = None
        self.format_level = None
        self.format_tier = None
        self.multiview_count = None
        self.multiview_layout = None
        self.hdr_format = None
        self.hdr_format_version = None
        self.hdr_format_profile = None
        self.hdr_format_level = None
        self.hdr_format_settings = None
        self.hdr_format_compression = None
        self.hdr_format_compatibility = None
        self.variable_bitrate = None # BitRate_Mode ("VBR"/"CBR") -- 1 = VBR, 0 = CBR
        self.bitrate = None
        self.bitrate_maximum = None
        self.width = None
        self.height = None
        self.stored_width = None
        self.stored_height = None
        self.sampled_width = None
        self.sampled_height = None
        self.pixel_aspect_ratio = None
        self.display_aspect_ratio = None
        self.variable_framerate = None # FrameRate_Mode ("VFR"/"CFR") -- 1 = VFR, 0 = CFR
        self.frame_rate = None
        self.frame_rate_num = None
        self.frame_rate_den = None
        self.color_space = None
        self.chroma_subsampling = None
        self.chroma_subsampling_position = None
        self.bit_depth = None
        self.interlaced = None # ScanType ("Interlaced"/"Progressive") -- 1 = interlaced, 0 = progressive
        self.language = None
        self.title = None
        self.color_description_present = None # MediaInfo's own field is "colour_description_present"
                                               # (British spelling); normalized to "color_" here for
                                               # consistency with color_space etc.
        self.color_range = None
        self.color_primaries = None
        self.transfer_characteristics = None
        self.matrix_coefficients = None
        self.mastering_display_color_primaries = None
        self.mastering_display_luminance_min = None
        self.mastering_display_luminance_max = None
        self.max_cll = None
        self.max_fall = None

        self.audioTracks = [] # list of AudioTrack
        self.subtitleTracks = [] # list of SubtitleTrack

        # (top, bottom, left, right) tuples, one per row this version gets in black_bars -- normally
        # just one (auto-detected or from a black_bars.txt override), more than one only for a
        # black_bars.txt override describing genuinely variable aspect ratio content (see
        # ScrapeBlackBars). Populated by ScrapeBlackBars.detectBlackBars alongside
        # ScrapeMediaInfo.analyzeMediaVersion above -- same newly-added/budget-surviving-only scope,
        # None/empty until then
        self.blackBars = []

    def isKaleidescapeOnly(self):
        """True if this version's main-role source is Kaleidescape -- i.e. there's no real local
        file to run MediaInfo on, just an empty placeholder (see ScrapeLocal's .kscape convention)."""
        mainSource = next((s for s in self.sources if s.role == "main"), None)
        return mainSource is not None and mainSource.source_type == "kscape"
