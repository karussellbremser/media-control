class MediaConnection:
    
    def __init__(self, foreignIMDbID, connectionType):
                
        self.foreignIMDbID = foreignIMDbID
        self.connectionType = connectionType

    def __str__(self):
        return str(self.foreignIMDbID) + " " + self.connectionType