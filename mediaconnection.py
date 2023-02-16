class MediaConnection:
    
    connectionTypeList = ["follows", "followed_by", "remake_of", "remade_as", "spin_off", "spin_off_from", "version_of"]
    
    def __init__(self, foreignIMDbID, connectionType):
                
        self.foreignIMDbID = foreignIMDbID
        self.connectionType = connectionType

    def __str__(self):
        return str(self.foreignIMDbID) + " " + self.connectionType