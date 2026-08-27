class Person:

    def __init__(self, imdbIDInt, name=None):
        self.imdb_id = imdbIDInt
        # placeholder until ScrapeIMDbOffline.parsePeople resolves the authoritative name.basics.tsv
        # name -- stays as this scraped-from-the-credits-page name if the person turns out to be
        # missing from the dataset (see parsePeople's docstring)
        self.name = name
        self.birth_year = None
        self.death_year = None

    def __str__(self):
        return self.getIDString() + " " + str(self.name) + " " + str(self.birth_year) + " " + str(self.death_year)

    def getIDString(self):
        return "nm" + str(self.imdb_id).zfill(7)
