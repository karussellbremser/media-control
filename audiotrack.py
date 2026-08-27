class AudioTrack:
    """One audio track of a locally-owned mkv file, as reported by MediaInfo -- see
    ScrapeMediaInfo.analyzeMediaVersion. track_id is MediaInfo's own "ID" field (unique per file
    across all track types, not just audio -- video/audio/subtitle tracks share one id sequence)."""

    def __init__(self, track_id, format, format_commercial, format_settings_mode,
                 format_additional_features, matrix_format, variable_bitrate, bitrate,
                 bitrate_maximum, channels, matrix_channels, channel_positions,
                 matrix_channel_positions, channel_layout, sampling_rate, bit_depth, lossless,
                 language, title, default_track):
        self.track_id = track_id
        self.format = format
        self.format_commercial = format_commercial
        self.format_settings_mode = format_settings_mode
        self.format_additional_features = format_additional_features
        self.matrix_format = matrix_format
        self.variable_bitrate = variable_bitrate # MediaInfo's BitRate_Mode ("VBR"/"CBR") -- 1 = VBR, 0 = CBR
        self.bitrate = bitrate
        self.bitrate_maximum = bitrate_maximum
        self.channels = channels
        self.matrix_channels = matrix_channels
        self.channel_positions = channel_positions
        self.matrix_channel_positions = matrix_channel_positions
        self.channel_layout = channel_layout
        self.sampling_rate = sampling_rate
        self.bit_depth = bit_depth
        self.lossless = lossless # MediaInfo's Compression_Mode ("Lossless"/"Lossy") -- 1 = lossless, 0 = lossy
        self.language = language
        self.title = title
        self.default_track = default_track
