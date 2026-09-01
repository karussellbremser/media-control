class LocalLibraryError(Exception):
    """The local media folder doesn't match the expected naming/content conventions."""
    pass

class OfflineDatasetError(Exception):
    """The IMDb offline dataset helper DB (see ScrapeIMDbOffline.updateIMDbOfflineDB) is missing,
    or contains something unexpected, or is inconsistent with locally-known data."""
    pass

class ScrapingError(Exception):
    """An IMDb page didn't have the DOM structure the scraper expects, or its content
    was inconsistent with locally-known data."""
    pass

class MediaInfoError(Exception):
    """The MediaInfo CLI tool's own output didn't have the structure/content expected
    (bad exit code, malformed JSON, wrong track count, missing required field, unrecognized
    enum value). A missing media file is a LocalLibraryError instead -- that's a local-library
    problem, not a MediaInfo-tool problem."""
    pass

class FFmpegError(Exception):
    """The ffmpeg CLI tool's own output didn't have the structure/content expected (bad exit
    code, no cropdetect reading found in its output). A malformed cropping.txt override is a
    LocalLibraryError instead -- that's a local-library problem, not an ffmpeg-tool problem."""
    pass
