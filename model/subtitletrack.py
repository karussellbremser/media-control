class SubtitleTrack:
    """One subtitle track of a locally-owned mkv file, as reported by MediaInfo -- see
    ScrapeMediaInfo.analyzeMediaVersion. track_id is MediaInfo's own "ID" field (unique per file
    across all track types, not just subtitles -- video/audio/subtitle tracks share one id sequence)."""

    def __init__(self, track_id, format, language, title, default_track, forced_track):
        self.track_id = track_id
        self.format = format
        self.language = language
        self.title = title
        self.default_track = default_track
        self.forced_track = forced_track
