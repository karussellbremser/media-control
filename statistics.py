import matplotlib.pyplot as plt

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
                avgRating.append(0)
                avgNumVotes.append(0)
        
        lists = [years, count, avgRating, avgNumVotes]
        if not all(len(lists[0]) == len(l) for l in lists[1:]):
            raise RuntimeError('error during statistics calculation')
        
        
        ax1 = plt.subplot(311, ylabel="media count")
        ax1.margins(x=0, y=0)
        plt.plot(years, count)
        plt.title("local media statistics")
        plt.xticks(years, rotation=90, fontsize=8)

        ax2 = plt.subplot(312, sharex=ax1, ylabel="average rating")
        ax2.margins(x=0, y=0)
        plt.plot(years, avgRating)
        plt.xticks(years, rotation=90, fontsize=8)

        ax3 = plt.subplot(313, sharex=ax1, xlabel="production year", ylabel="average vote count")
        ax3.margins(x=0, y=0)
        plt.plot(years, avgNumVotes)
        plt.xticks(years, rotation=90, fontsize=8)
        
        plt.show()
        
