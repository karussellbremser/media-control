from sourceparser import parseSourceString

class MediaVersion:

    def __init__(self, filename, source, version):

        self.filename = filename
        self.source = source # raw "src-..." string, kept for reference alongside the parsed form
        self.version = version
        self.sources = parseSourceString(source) # list of MediaSource, one per leaf source
