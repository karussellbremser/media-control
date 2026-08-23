class Episode:
    """A locally-found episode of a series, before its IMDb id is known. season_number/episode_number
    come from the local filename convention (see ScrapeLocal.__scrapeSingleSeason); mediaVersions is
    a list of MediaVersion, parsed exactly like a movie's (sources/versions.txt, same grammar).
    Resolved to a real imdb_id later by cross-referencing title.episode.tsv against the parent
    series' own id."""

    def __init__(self, season_number, episode_number, mediaVersions):
        self.season_number = season_number
        self.episode_number = episode_number
        self.mediaVersions = mediaVersions

    def __str__(self):
        return "S" + str(self.season_number) + "E" + str(self.episode_number) + " " + str([str(v.source) for v in self.mediaVersions])
