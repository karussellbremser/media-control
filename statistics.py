import matplotlib.pyplot as plt
import numpy
from media import Media

class Statistics:
    
    def __init__(self, db):
                
        self.db = db
        
    def printYearlyAverages(self):
        with self.db.conn:
            self.db.c.execute("SELECT startYear, COUNT(*), AVG(rating_mul10), AVG(numVotes) FROM media WHERE subdir IS NOT NULL GROUP BY startYear ORDER BY startYear")
            dbResult = self.db.c.fetchall()
        
        dataDict = {}
        for yearData in dbResult:
            dataDict[yearData[0]] = [yearData[1], yearData[2], yearData[3]]
        
        yearList = list(dataDict.keys())
        yearList.sort()
        years = []
        count = []
        avgRating = []
        avgNumVotes = []
        
        # fill in years without media
        for year in range(yearList[0], yearList[-1] + 1):
            years.append(year)
            if year in dataDict:
                count.append(dataDict[year][0])
                avgRating.append(dataDict[year][1])
                avgNumVotes.append(dataDict[year][2])
            else:
                count.append(0)
                avgRating.append(numpy.nan)
                avgNumVotes.append(numpy.nan)
        
        lists = [years, count, avgRating, avgNumVotes]
        if not all(len(lists[0]) == len(l) for l in lists[1:]):
            raise RuntimeError('error during statistics calculation')
        
        
        ax1 = plt.subplot(311, ylabel="media count")
        ax1.margins(x=0, y=0)
        plt.plot(years, count, marker='.')
        plt.title("local media statistics")
        plt.xticks(years, rotation=90, fontsize=8)

        ax2 = plt.subplot(312, sharex=ax1, ylabel="average rating")
        ax2.margins(x=0, y=0)
        plt.plot(years, avgRating, marker='.')
        plt.xticks(years, rotation=90, fontsize=8)

        ax3 = plt.subplot(313, sharex=ax1, xlabel="production year", ylabel="average vote count")
        ax3.margins(x=0, y=0)
        plt.plot(years, avgNumVotes, marker='.')
        plt.xticks(years, rotation=90, fontsize=8)
        
        plt.show()
    
    def analyzeMediaConnections(self):
        
        movieDict = self.db.getAllMovieObjects()
        
        groupList = []
        
        with self.db.conn:
            while len(movieDict) != 0:
                currentGroup = mediaGroup()
                currentIDQueue = []
                
                currentImdbID = list(movieDict.keys())[0]
                currentIDQueue.append(currentImdbID)
            
                while len(currentIDQueue) != 0:
                    currentImdbID = currentIDQueue.pop(0)
                    currentMedium = movieDict[currentImdbID]
                    currentGroup.addMedium(currentMedium)
                    del movieDict[currentImdbID]
                    
                    for x in currentMedium.mediaConnections:
                        y = x.foreignIMDbID
                        if y not in currentIDQueue and y not in currentGroup.imbdIDList:
                            currentIDQueue.append(y)
                    
                    self.db.c.execute("SELECT imdb_id FROM mediaConnections WHERE foreign_imdb_id=?", (currentImdbID,))
                    dbResult = self.db.c.fetchall()
                    for x in dbResult:
                        y = x[0]
                        if y not in currentIDQueue and y not in currentGroup.imbdIDList:
                            currentIDQueue.append(y)
                
                if currentGroup.mediaCount > 1:
                    groupList.append(currentGroup)
        
        groupList.sort(key=lambda group: group.localPercentage, reverse=True)
        for group in groupList:
            print(group)

class mediaGroup:
    
    def __init__(self):
        self.mediaList = []
        self.imbdIDList = []
        self.mediaCount = 0
        self.localMediaCount = 0
        self.localPercentage = None
        self.mainMedium = None
    
    def __str__(self):
        return str(self.mediaCount) + " items, " + str(self.localPercentage) + "% local, " + self.mainMedium.originalTitle
    
    def addMedium(self, medium):
        self.mediaList.append(medium)
        self.imbdIDList.append(medium.imdb_id)
        self.mediaCount += 1
        if medium.subdir != None:
            self.localMediaCount += 1
        self.localPercentage = (self.localMediaCount / self.mediaCount) * 100
        if self.mainMedium == None or self.mainMedium.numVotes == None or (medium.numVotes != None and medium.numVotes > self.mainMedium.numVotes):
            self.mainMedium = medium
    
    

