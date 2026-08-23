class Episode:
    """A locally-found episode of a series, before its IMDb id is confirmed. season_number/
    episode_number come from the local filename convention (see ScrapeLocal.__scrapeSingleSeason);
    mediaVersions is a list of MediaVersion, parsed exactly like a movie's (sources/versions.txt,
    same grammar). subdir is the season folder's real path (e.g. "SeriesName_2010_ttXXXXXXX/S01")
    -- kept as a literal string rather than reconstructed from season_number later, since
    zero-padding (S01 vs S1) can't be recovered from the parsed int alone.

    season_number/episode_number are None for an episode IMDb itself doesn't number (mirrors
    title.episode.tsv's "\\N" convention, see ScrapeIMDbOffline.parseTitleEpisode) -- locally, these
    live in the reserved S00 folder, named "seriesname_ttXXXXXXX.mkv" instead of the usual
    "seriesname_SxxEyy.mkv" (there's no number to encode), so imdb_id is already known directly
    rather than needing a season/episode lookup to resolve. For a normal numbered episode, imdb_id
    is None here and gets resolved later by cross-referencing title.episode.tsv against the parent
    series' own id."""

    def __init__(self, season_number, episode_number, mediaVersions, subdir, imdb_id=None, intended_order=None):
        self.season_number = season_number
        self.episode_number = episode_number
        self.mediaVersions = mediaVersions
        self.subdir = subdir
        self.imdb_id = imdb_id
        self.intended_order = intended_order # this episode's 1-indexed rank in its season's intended_order.txt, if any -- see ScrapeLocal.__scrapeSingleSeason

    def __str__(self):
        return "S" + str(self.season_number) + "E" + str(self.episode_number) + " " + str([str(v.source) for v in self.mediaVersions])
