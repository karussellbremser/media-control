class MediaConnection:

    connectionTypeList = ["follows", "followed_by", "remake_of", "remade_as", "spin_off", "spin_off_from", "version_of", "alternate_language_version_of"]

    def __init__(self, foreign_imdb_id, connection_type):

        self.foreign_imdb_id = foreign_imdb_id
        self.connection_type = connection_type

    def __str__(self):
        return str(self.foreign_imdb_id) + " " + self.connection_type
