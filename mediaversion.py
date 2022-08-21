class MediaVersion:
    
    def __init__(self, filename, video_source, audio_source, dynhdr_source, version):
                
        self.filename = filename
        self.video_source = video_source
        self.audio_source = audio_source
        self.dynhdr_source = dynhdr_source
        self.version = version