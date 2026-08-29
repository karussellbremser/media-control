import sqlite3
from media import Media
from mediaversion import MediaVersion
from mediaconnection import MediaConnection
from person import Person
from credit import Credit
from exceptions import LocalLibraryError, OfflineDatasetError

class DBControl:

    def __init__(self, dbLocation):
        """Initialize db class variables"""
        self.conn = sqlite3.connect(dbLocation)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.c = self.conn.cursor()

    def close(self):
        """close sqlite3 connection"""
        self.conn.close()

    def createMediaDB(self):
        with self.conn:
            # media table holds both media present in library and those only linked by IMDb connections. differentiator if medium is actually present is subdir not being NULL.
            # covers movies, series, and episodes alike. subdir is not UNIQUE: an episode's subdir is
            # its season folder's path, shared by every sibling episode in that season (see
            # ScrapeLocal.__scrapeSingleSeries) -- ownership is per-episode via imdb_id, not subdir.
            # season_number/episode_number/series_imdb_id are only ever set for episodes (titleType
            # in Media.episodeTitleTypes); NULL there means IMDb has no season/episode number for
            # this episode (never conflated with a real number -- see ScrapeIMDbOffline.parseTitleEpisode).
            # intended_order is also episode-only, but purely local data (a season's optional
            # intended_order.txt, see ScrapeLocal.__scrapeSingleSeason) rather than IMDb-sourced --
            # so unlike season_number/episode_number it's cleared on light-remove, same as
            # language_id/media_interests (see removeSingleMedia)
            self.c.execute("""CREATE TABLE media (
            imdb_id integer NOT NULL,
            title_type_id integer NOT NULL,
            originalTitle text NOT NULL,
            primaryTitle text NOT NULL,
            startYear integer NOT NULL,
            endYear integer,
            rating_mul10 integer,
            numVotes integer,
            releaseMonth integer,
            releaseDay integer,
            subdir text,
            language_id integer NOT NULL DEFAULT 0,
            plotSummary text,
            season_number integer,
            episode_number integer,
            series_imdb_id integer,
            intended_order integer,
            PRIMARY KEY (imdb_id),
            FOREIGN KEY (title_type_id)
                REFERENCES title_type_enum (title_type_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,
            FOREIGN KEY (language_id)
                REFERENCES language_enum (imdb_interest_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,
            FOREIGN KEY (series_imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            )""")

            # media_interests holds both standard genres and IMDb "interests" (subgenres), differentiated in interest_enum
            # only populated for locally-owned media (subdir NOT NULL); referenced-only media have no entries here.
            # imdb_interest_id is stored as the integer form of IMDb's "inXXXXXXX" id (see imdbinterestid.py)
            self.c.execute("""CREATE TABLE media_interests (
            imdb_id integer NOT NULL,
            imdb_interest_id integer NOT NULL,
            PRIMARY KEY (imdb_id, imdb_interest_id),
            FOREIGN KEY (imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
            FOREIGN KEY (imdb_interest_id)
                REFERENCES interest_enum (imdb_interest_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            )""")

            # keyed by the integer form of IMDb's own interest id (e.g. "in0000076" -> 76).
            # parent_imdb_interest_id is NULL for standard genres and always set for subgenre "interests".
            # populated dynamically as new interests are discovered during online scraping, not pre-seeded.
            self.c.execute("""CREATE TABLE interest_enum (
            imdb_interest_id integer NOT NULL,
            name text NOT NULL,
            description text NOT NULL,
            parent_imdb_interest_id integer,
            PRIMARY KEY (imdb_interest_id),
            FOREIGN KEY (parent_imdb_interest_id)
                REFERENCES interest_enum (imdb_interest_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            )""")

            # lookup for IMDb interests that turned out to be languages rather than genres/subgenres
            # (e.g. "German"), keyed by the integer form of IMDb's interest id. Referenced by
            # media.language_id; also serves as a cache to avoid re-classifying an already-known language.
            self.c.execute("""CREATE TABLE language_enum (
            imdb_interest_id integer NOT NULL,
            name text NOT NULL UNIQUE,
            description text NOT NULL,
            PRIMARY KEY (imdb_interest_id)
            )""")
            # English has no IMDb interest id of its own (confirmed absent from IMDb's full interest
            # directory) since it's the unmarked default -- 0 is used as a reserved id here, since
            # real IMDb interest ids (in\d+) are always 1 or greater and can never collide with it
            self.c.execute("INSERT INTO language_enum VALUES (?, ?, ?)", (0, "English", "English-language cinema encompasses a vast and influential body of filmmaking, from Hollywood's genre-defining blockbusters to British drama and independent voices across the English-speaking world. It has driven major innovations in visual effects, narrative structure, and global distribution, shaping how audiences everywhere experience film. Its reach and influence remain unmatched, setting trends that ripple through the international film industry."))

            self.c.execute("""CREATE TABLE title_type_enum (
            title_type_id integer NOT NULL,
            title_type_name text NOT NULL UNIQUE,
            PRIMARY KEY (title_type_id)
            )""")
            i = 1
            for titleType in Media.movieTitleTypes + Media.seriesTitleTypes + Media.episodeTitleTypes:
                self.c.execute("INSERT INTO title_type_enum VALUES (?, ?)", (i, titleType))
                i += 1

            # video-track fields (format/width/height/HDR/etc.) live directly on this table rather
            # than a separate one-to-one child table, since a file has exactly one video track --
            # unlike audio/subtitles (media_audio_tracks/media_subtitle_tracks below), which are
            # genuinely one-to-many and need their own tables. All of it is populated by
            # ScrapeMediaInfo.analyzeMediaVersion, only ever for a title newly added this sync run.
            self.c.execute("""CREATE TABLE media_versions (
            imdb_id integer NOT NULL,
            filename text NOT NULL,
            source text NOT NULL,
            version text,
            duration integer NOT NULL,
            mediainfo_version text,
            format text,
            format_profile text,
            format_level text,
            format_tier text,
            multiview_count integer,
            multiview_layout text,
            hdr_format text,
            hdr_format_version text,
            hdr_format_profile text,
            hdr_format_level text,
            hdr_format_settings text,
            hdr_format_compression text,
            hdr_format_compatibility text,
            variable_bitrate integer,
            bitrate integer,
            bitrate_maximum integer,
            width integer NOT NULL,
            height integer NOT NULL,
            stored_width integer,
            stored_height integer,
            sampled_width integer,
            sampled_height integer,
            pixel_aspect_ratio real,
            display_aspect_ratio real,
            variable_framerate integer,
            frame_rate real,
            frame_rate_num integer,
            frame_rate_den integer,
            color_space text,
            chroma_subsampling text,
            chroma_subsampling_position text,
            bit_depth integer,
            interlaced integer,
            language text,
            title text,
            color_description_present integer,
            color_range text,
            color_primaries text,
            transfer_characteristics text,
            matrix_coefficients text,
            mastering_display_color_primaries text,
            mastering_display_luminance_min real,
            mastering_display_luminance_max integer,
            max_cll integer,
            max_fall integer,
            PRIMARY KEY (imdb_id, filename),
            UNIQUE (imdb_id, version),
            FOREIGN KEY (imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            )""")

            # genuinely one-to-many track types (unlike video, see media_versions above) -- one row
            # per audio/subtitle track, keyed by MediaInfo's own "ID" field (unique per file across
            # all track types, not just this one)
            self.c.execute("""CREATE TABLE media_audio_tracks (
            imdb_id integer NOT NULL,
            filename text NOT NULL,
            track_id integer NOT NULL,
            format text NOT NULL,
            format_commercial text,
            format_settings_mode text,
            format_additional_features text,
            matrix_format text,
            variable_bitrate integer,
            bitrate integer,
            bitrate_maximum integer,
            channels integer,
            matrix_channels integer,
            channel_positions text,
            matrix_channel_positions text,
            channel_layout text,
            sampling_rate integer,
            bit_depth integer,
            lossless integer,
            language text NOT NULL,
            title text,
            default_track integer NOT NULL,
            PRIMARY KEY (imdb_id, filename, track_id),
            FOREIGN KEY (imdb_id, filename)
                REFERENCES media_versions (imdb_id, filename)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            )""")

            self.c.execute("""CREATE TABLE media_subtitle_tracks (
            imdb_id integer NOT NULL,
            filename text NOT NULL,
            track_id integer NOT NULL,
            format text NOT NULL,
            language text NOT NULL,
            title text,
            default_track integer NOT NULL,
            forced_track integer NOT NULL,
            PRIMARY KEY (imdb_id, filename, track_id),
            FOREIGN KEY (imdb_id, filename)
                REFERENCES media_versions (imdb_id, filename)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            )""")

            # fixed, pre-seeded classification of physical/digital media a mediaVersion's source(s)
            # can come from (see Media.source_type_list)
            self.c.execute("""CREATE TABLE source_type_enum (
            source_type_id integer NOT NULL,
            source_type_name text NOT NULL UNIQUE,
            PRIMARY KEY (source_type_id)
            )""")
            i = 1
            for source_type in Media.source_type_list:
                self.c.execute("INSERT INTO source_type_enum VALUES (?, ?)", (i, source_type))
                i += 1

            # fixed, pre-seeded structural role a single leaf source plays within a mediaVersion's
            # overall source description (see Media.source_role_list)
            self.c.execute("""CREATE TABLE source_role_enum (
            role_id integer NOT NULL,
            role_name text NOT NULL UNIQUE,
            PRIMARY KEY (role_id)
            )""")
            i = 1
            for source_role in Media.source_role_list:
                self.c.execute("INSERT INTO source_role_enum VALUES (?, ?)", (i, source_role))
                i += 1

            # web download providers (e.g. "AMZN" -> "Amazon"), sourced from config.WEB_PROVIDERS.
            # Not pre-seeded here; kept in sync additively on every sync instead (see
            # syncWebProvidersFromConfig), so the enum -- not config -- is the actual source of
            # truth: removing a provider from config only stops it being re-affirmed, it doesn't
            # remove it or anything that already references it. web_provider_id is a plain SQLite
            # rowid (we mint these ourselves, unlike interest/language ids which come from IMDb)
            self.c.execute("""CREATE TABLE source_web_provider_enum (
            web_provider_id INTEGER PRIMARY KEY,
            abbreviation text NOT NULL UNIQUE,
            full_name text NOT NULL
            )""")

            # the leaf source(s) that make up a single mediaVersion's provenance. A version with a
            # single plain source has one row (role=main). hybrid/dynhdrhybrid/combined splits use
            # the video/audio/video_base/video_dynhdr roles, one row each. fanres allows more than
            # one row per role (seq disambiguates them), since a fan restoration can blend an
            # arbitrary number of sources for the same role.
            self.c.execute("""CREATE TABLE media_version_sources (
            imdb_id integer NOT NULL,
            filename text NOT NULL,
            role_id integer NOT NULL,
            seq integer NOT NULL,
            source_type_id integer NOT NULL,
            disc_id integer,
            disc_corrected integer,
            kaleidescape_id text,
            web_provider_id integer,
            base_layer integer,
            downmixed integer,
            core integer,
            fanres integer,
            PRIMARY KEY (imdb_id, filename, role_id, seq),
            FOREIGN KEY (imdb_id, filename)
                REFERENCES media_versions (imdb_id, filename)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
            FOREIGN KEY (role_id)
                REFERENCES source_role_enum (role_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,
            FOREIGN KEY (source_type_id)
                REFERENCES source_type_enum (source_type_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,
            FOREIGN KEY (web_provider_id)
                REFERENCES source_web_provider_enum (web_provider_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            )""")

            self.c.execute("""CREATE TABLE media_connections (
            imdb_id integer NOT NULL,
            foreign_imdb_id integer NOT NULL,
            connection_type_id integer NOT NULL,
            PRIMARY KEY (imdb_id, foreign_imdb_id, connection_type_id),
            FOREIGN KEY (imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
            FOREIGN KEY (foreign_imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,
            FOREIGN KEY (connection_type_id)
                REFERENCES connection_type_enum (connection_type_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            )""")

            self.c.execute("""CREATE TABLE connection_type_enum (
            connection_type_id integer NOT NULL,
            connection_type_name text NOT NULL UNIQUE,
            PRIMARY KEY (connection_type_id)
            )""")
            i = 1
            for connection_type in MediaConnection.connectionTypeList:
                self.c.execute("INSERT INTO connection_type_enum VALUES (?, ?)", (i, connection_type))
                i += 1

            # imdb ids deemed not worth cataloguing at all (e.g. an amateur/fan production) -- must
            # never appear in the DB in any form, mainly to keep media_connections free of entries
            # not worth surfacing; kept in sync (non-additively) from config.IGNORED_IDS_PATH (see
            # syncIgnoredAndWontaddIDs/enforceIgnoredAndWontaddIDs)
            self.c.execute("""CREATE TABLE ignored_ids (
            imdb_id integer NOT NULL,
            PRIMARY KEY (imdb_id)
            )""")

            # imdb ids whose existence in the DB is honored (may reside as referenced-only media, or
            # -- for a series specifically, see enforceIgnoredAndWontaddIDs -- even be partially
            # locally owned), but that aren't worth the effort of chasing down locally; mainly used
            # to keep a to-be-added list generated from the DB free of entries not worth adding.
            # Kept in sync (non-additively) from config.WONTADD_IDS_PATH
            self.c.execute("""CREATE TABLE wontadd_ids (
            imdb_id integer NOT NULL,
            PRIMARY KEY (imdb_id)
            )""")

            # imdb interest ids already known to be franchise-type (e.g. "Evil Dead") -- these are
            # deliberately never attached to any medium or added to interest_enum itself (that
            # relationship is already covered via media_connections/MediaConnection); this table
            # exists purely so a franchise doesn't need to be re-classified (an extra IMDb page
            # visit) on every future sync. Populated additively as new ones are discovered, see
            # ScrapeIMDbOnline.__classifyChips / DBControl.ensureFranchiseInterestExists
            self.c.execute("""CREATE TABLE franchise_interest_ids (
            imdb_interest_id integer NOT NULL,
            PRIMARY KEY (imdb_interest_id)
            )""")

            # people credited (director/writer/actor) on locally-owned media, keyed by the integer
            # form of IMDb's own "nmXXXXXXX" person id. name/birth_year/death_year come from the
            # offline name.basics.tsv dataset (see ScrapeIMDbOffline.parsePeople/refreshPeople), not
            # from the credits scrape itself -- name starts out as whatever was scraped from the
            # credits page and is only overwritten once/if parsePeople resolves the real dataset
            # row (see Person). A person only stays here as long as at least one credits row still
            # references them (see DBControl.__pruneOrphanedPeople).
            self.c.execute("""CREATE TABLE people (
            imdb_id integer NOT NULL,
            name text NOT NULL,
            birth_year integer,
            death_year integer,
            PRIMARY KEY (imdb_id)
            )""")

            self.c.execute("""CREATE TABLE credit_role_enum (
            credit_role_id integer NOT NULL,
            credit_role_name text NOT NULL UNIQUE,
            PRIMARY KEY (credit_role_id)
            )""")
            i = 1
            for credit_role in Credit.creditRoleList:
                self.c.execute("INSERT INTO credit_role_enum VALUES (?, ?)", (i, credit_role))
                i += 1

            # director/writer/actor credits, scraped from a locally-owned medium's own fullcredits
            # page (see ScrapeIMDbOnline.scrapeFullCredits) -- only ever populated for locally-owned
            # media (subdir NOT NULL), including episodes (unlike media_interests, which skips
            # episodes entirely). ordering is one running sequence per medium, in the page's own
            # order (director(s), then writer(s), then actor(s)) -- not scoped per role, so it
            # doubles as a natural, always-unique primary key alongside imdb_id (a person can
            # legitimately appear more than once for the same medium, e.g. a director who also
            # acts, or an actor playing a dual role under two separate cast entries).
            self.c.execute("""CREATE TABLE credits (
            imdb_id integer NOT NULL,
            ordering integer NOT NULL,
            person_id integer NOT NULL,
            credit_role_id integer NOT NULL,
            credit_details text,
            PRIMARY KEY (imdb_id, ordering),
            FOREIGN KEY (imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
            FOREIGN KEY (person_id)
                REFERENCES people (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,
            FOREIGN KEY (credit_role_id)
                REFERENCES credit_role_enum (credit_role_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            )""")

    def addSingleMediaWoConnections(self, thisMedia):
        if not isinstance(thisMedia, Media):
            raise TypeError('no media object')
        with self.conn:
            self.c.execute("SELECT originalTitle, subdir FROM media WHERE imdb_id = ?", (thisMedia.imdb_id,)) # need to get originalTitle as well, as otherwise no NULL subdirs will be returned
            data = self.c.fetchall()
            if len(data) == 0:
                self.c.execute("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (thisMedia.imdb_id, self.__getTitleTypeIDByTitleTypeName(thisMedia.titleType), thisMedia.originalTitle, thisMedia.primaryTitle, thisMedia.startYear, thisMedia.endYear, thisMedia.rating_mul10, thisMedia.numVotes, thisMedia.releaseMonth, thisMedia.releaseDay, thisMedia.subdir, thisMedia.language_id, thisMedia.plotSummary, thisMedia.season_number, thisMedia.episode_number, thisMedia.series_imdb_id, thisMedia.intended_order))
            elif data[0][1] == None:
                self.c.execute("UPDATE media SET title_type_id=?, originalTitle=?, primaryTitle=?, startYear=?, endYear=?, rating_mul10=?, numVotes=?, releaseMonth=?, releaseDay=?, subdir=?, language_id=?, plotSummary=?, season_number=?, episode_number=?, series_imdb_id=?, intended_order=? WHERE imdb_id=?", (self.__getTitleTypeIDByTitleTypeName(thisMedia.titleType), thisMedia.originalTitle, thisMedia.primaryTitle, thisMedia.startYear, thisMedia.endYear, thisMedia.rating_mul10, thisMedia.numVotes, thisMedia.releaseMonth, thisMedia.releaseDay, thisMedia.subdir, thisMedia.language_id, thisMedia.plotSummary, thisMedia.season_number, thisMedia.episode_number, thisMedia.series_imdb_id, thisMedia.intended_order, thisMedia.imdb_id))
            else:
                raise RuntimeError('already existing media object supposed to be newly added: ' + data[0][0])
            for imdb_interest_id in thisMedia.interests:
                self.c.execute("INSERT INTO media_interests VALUES (?, ?)", (thisMedia.imdb_id, imdb_interest_id))
            for mediaVersion in thisMedia.mediaVersions:
                # built from explicit column/value lists (rather than a hardcoded run of "?"
                # placeholders, as elsewhere in this file) since this table is wide enough that
                # miscounting placeholders by hand would be an easy, silent mistake
                versionColumns = [
                    "imdb_id", "filename", "source", "version", "duration", "mediainfo_version",
                    "format", "format_profile", "format_level", "format_tier",
                    "multiview_count", "multiview_layout",
                    "hdr_format", "hdr_format_version", "hdr_format_profile", "hdr_format_level",
                    "hdr_format_settings", "hdr_format_compression", "hdr_format_compatibility",
                    "variable_bitrate", "bitrate", "bitrate_maximum",
                    "width", "height", "stored_width", "stored_height", "sampled_width", "sampled_height",
                    "pixel_aspect_ratio", "display_aspect_ratio",
                    "variable_framerate", "frame_rate", "frame_rate_num", "frame_rate_den",
                    "color_space", "chroma_subsampling", "chroma_subsampling_position", "bit_depth", "interlaced",
                    "language", "title",
                    "color_description_present", "color_range", "color_primaries",
                    "transfer_characteristics", "matrix_coefficients",
                    "mastering_display_color_primaries", "mastering_display_luminance_min",
                    "mastering_display_luminance_max", "max_cll", "max_fall",
                ]
                versionValues = [
                    thisMedia.imdb_id, mediaVersion.filename, mediaVersion.source, mediaVersion.version,
                    mediaVersion.duration, mediaVersion.mediainfo_version,
                    mediaVersion.format, mediaVersion.format_profile, mediaVersion.format_level, mediaVersion.format_tier,
                    mediaVersion.multiview_count, mediaVersion.multiview_layout,
                    mediaVersion.hdr_format, mediaVersion.hdr_format_version, mediaVersion.hdr_format_profile, mediaVersion.hdr_format_level,
                    mediaVersion.hdr_format_settings, mediaVersion.hdr_format_compression, mediaVersion.hdr_format_compatibility,
                    mediaVersion.variable_bitrate, mediaVersion.bitrate, mediaVersion.bitrate_maximum,
                    mediaVersion.width, mediaVersion.height, mediaVersion.stored_width, mediaVersion.stored_height, mediaVersion.sampled_width, mediaVersion.sampled_height,
                    mediaVersion.pixel_aspect_ratio, mediaVersion.display_aspect_ratio,
                    mediaVersion.variable_framerate, mediaVersion.frame_rate, mediaVersion.frame_rate_num, mediaVersion.frame_rate_den,
                    mediaVersion.color_space, mediaVersion.chroma_subsampling, mediaVersion.chroma_subsampling_position, mediaVersion.bit_depth, mediaVersion.interlaced,
                    mediaVersion.language, mediaVersion.title,
                    mediaVersion.color_description_present, mediaVersion.color_range, mediaVersion.color_primaries,
                    mediaVersion.transfer_characteristics, mediaVersion.matrix_coefficients,
                    mediaVersion.mastering_display_color_primaries, mediaVersion.mastering_display_luminance_min,
                    mediaVersion.mastering_display_luminance_max, mediaVersion.max_cll, mediaVersion.max_fall,
                ]
                self.c.execute(
                    "INSERT INTO media_versions (" + ", ".join(versionColumns) + ") VALUES (" + ", ".join("?" for _ in versionColumns) + ")",
                    versionValues
                )
                for source in mediaVersion.sources:
                    self.c.execute("INSERT INTO media_version_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                        thisMedia.imdb_id,
                        mediaVersion.filename,
                        self.__getSourceRoleIDByName(source.role),
                        source.seq,
                        self.__getSourceTypeIDByName(source.source_type),
                        source.disc_id,
                        int(source.disc_corrected),
                        source.kaleidescape_id,
                        self.__getWebProviderIDByAbbreviation(source.web_provider) if source.web_provider is not None else None,
                        int(source.base_layer),
                        int(source.downmixed),
                        int(source.core),
                        int(source.fanres),
                    ))
                for audioTrack in mediaVersion.audioTracks:
                    self.c.execute("""INSERT INTO media_audio_tracks (
                        imdb_id, filename, track_id, format, format_commercial, format_settings_mode,
                        format_additional_features, matrix_format, variable_bitrate, bitrate, bitrate_maximum,
                        channels, matrix_channels, channel_positions, matrix_channel_positions, channel_layout,
                        sampling_rate, bit_depth, lossless, language, title, default_track
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                        thisMedia.imdb_id, mediaVersion.filename, audioTrack.track_id, audioTrack.format,
                        audioTrack.format_commercial, audioTrack.format_settings_mode,
                        audioTrack.format_additional_features, audioTrack.matrix_format, audioTrack.variable_bitrate,
                        audioTrack.bitrate, audioTrack.bitrate_maximum,
                        audioTrack.channels, audioTrack.matrix_channels, audioTrack.channel_positions,
                        audioTrack.matrix_channel_positions, audioTrack.channel_layout,
                        audioTrack.sampling_rate, audioTrack.bit_depth, audioTrack.lossless, audioTrack.language,
                        audioTrack.title, audioTrack.default_track,
                    ))
                for subtitleTrack in mediaVersion.subtitleTracks:
                    self.c.execute("""INSERT INTO media_subtitle_tracks (
                        imdb_id, filename, track_id, format, language, title, default_track, forced_track
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                        thisMedia.imdb_id, mediaVersion.filename, subtitleTrack.track_id, subtitleTrack.format,
                        subtitleTrack.language, subtitleTrack.title, subtitleTrack.default_track, subtitleTrack.forced_track,
                    ))

    def addSingleMediaConnections(self, thisMedia):
        if not isinstance(thisMedia, Media):
            raise TypeError('no media object')
        with self.conn:
            for mediaConnection in thisMedia.mediaConnections:
                self.c.execute("INSERT INTO media_connections VALUES (?, ?, ?)", (thisMedia.imdb_id, mediaConnection.foreignIMDbID, self.__getConnectionTypeIDByConnectionTypeName(mediaConnection.connectionType)))

    def addSingleMediaCredits(self, thisMedia):
        # unlike media_connections, a credit only ever references thisMedia.imdb_id itself (never
        # another medium), so -- as long as every credited person's row already exists in people,
        # which addMultipleMedia guarantees by calling this only after main.py has persisted new
        # people -- this has no cross-medium ordering dependency the way addSingleMediaConnections does.
        if not isinstance(thisMedia, Media):
            raise TypeError('no media object')
        with self.conn:
            for credit in thisMedia.credits:
                self.c.execute("INSERT INTO credits VALUES (?, ?, ?, ?, ?)", (thisMedia.imdb_id, credit.ordering, credit.person_id, self.__getCreditRoleIDByCreditRoleName(credit.creditRole), credit.creditDetails))

    def addMultipleMedia(self, mediaDict): # media, connections and credits must be separated, so that foreign constraints are always fulfilled during db entry
        # a series must exist before any of its episodes are inserted (series_imdb_id's FK); the
        # caller's dict order doesn't guarantee this -- a referenced-only episode of a brand-new
        # series can end up ordered before that series' own stub entry (its stub is only appended
        # once the episode is found to need it). Sorting movies/series (series_imdb_id is None)
        # ahead of episodes here guarantees the dependency regardless of insertion order.
        for x in sorted(mediaDict.values(), key=lambda m: m.series_imdb_id is not None):
            self.addSingleMediaWoConnections(x)
        for x in mediaDict.values():
            self.addSingleMediaConnections(x)
        for x in mediaDict.values():
            self.addSingleMediaCredits(x)

    def removeMultipleMedia(self, removedDict):
        for x in removedDict.values():
            self.removeSingleMedia(x)

    def removeSingleMedia(self, mediumToRemove):
        with self.conn:
            #1. remove all media_versions of mediumToRemove
            self.c.execute("DELETE FROM media_versions WHERE imdb_id=?", (mediumToRemove.imdb_id,))

            #2. remove and save all connections FROM mediumToRemove to list referencesToRemove
            self.c.execute("SELECT imdb_id, foreign_imdb_id FROM media_connections WHERE imdb_id=?", (mediumToRemove.imdb_id,))
            referencesToRemove = self.c.fetchall()
            self.c.execute("DELETE FROM media_connections WHERE imdb_id=?", (mediumToRemove.imdb_id,))

            #3. check whether there are any connections TO mediumToRemove
            self.c.execute("SELECT * FROM media_connections WHERE foreign_imdb_id=?", (mediumToRemove.imdb_id,))
            remainingConnections = self.c.fetchall()

            # a series can't be safely deleted while it still has an episode that's owned or
            # referenced (series_imdb_id's FK requires the series row to exist); clean up any
            # no-longer-needed episodes first (no-op if mediumToRemove isn't a series), and treat
            # the series as still-referenced if any episode remains afterward
            seriesHasNeededEpisodes = not self.__removeUnneededSeriesEpisodes(mediumToRemove.imdb_id)

            # capture mediumToRemove's current interests, language and credited people before
            # they're removed, so anything left with no remaining attachments afterward can be pruned
            self.c.execute("SELECT imdb_interest_id FROM media_interests WHERE imdb_id=?", (mediumToRemove.imdb_id,))
            affectedInterestIDs = [row[0] for row in self.c.fetchall()]
            self.c.execute("SELECT language_id FROM media WHERE imdb_id=?", (mediumToRemove.imdb_id,))
            affectedLanguageIDs = [row[0] for row in self.c.fetchall()]
            self.c.execute("SELECT person_id FROM credits WHERE imdb_id=?", (mediumToRemove.imdb_id,))
            affectedPersonIDs = [row[0] for row in self.c.fetchall()]

            #3a. if yes: only "light-remove" mediumToRemove (remove subdir, interests, credits,
            # intended episode order, manually-entered release day/month, and reset language to the
            # default; these are only valid for locally-owned media -- intended_order and
            # releaseMonth/Day in particular are purely local data (release day/month are only ever
            # entered manually, see Media.__init__), unlike season_number/episode_number/
            # series_imdb_id which come from IMDb and stay valid regardless of ownership)
            if len(remainingConnections) != 0 or seriesHasNeededEpisodes:
                print("Removing " + mediumToRemove.originalTitle + " from DB as local medium (still being referenced)")
                self.c.execute("UPDATE media SET subdir = NULL, language_id = 0, intended_order = NULL, releaseMonth = NULL, releaseDay = NULL WHERE imdb_id=?", (mediumToRemove.imdb_id,))
                self.c.execute("DELETE FROM media_interests WHERE imdb_id=?", (mediumToRemove.imdb_id,))
                self.c.execute("DELETE FROM credits WHERE imdb_id=?", (mediumToRemove.imdb_id,))

            #3b. if no: remove media entry (media_interests/credits rows are removed via ON DELETE CASCADE)
            else:
                print("Removing " + mediumToRemove.originalTitle + " from DB")
                self.c.execute("DELETE FROM media WHERE imdb_id=?", (mediumToRemove.imdb_id,))

            self.__pruneOrphanedInterests(affectedInterestIDs)
            self.__pruneOrphanedLanguages(affectedLanguageIDs)
            self.__pruneOrphanedPeople(affectedPersonIDs)

            # if mediumToRemove was itself an episode, its parent series might now be orphaned
            if mediumToRemove.series_imdb_id is not None:
                self.__pruneOrphanedSeries([mediumToRemove.series_imdb_id])

            #4. for all x in list referencesToRemove:
            for x in referencesToRemove:

                #4a. if x not in db table media or if subdir NOT EMPTY: continue
                self.c.execute("SELECT imdb_id, originalTitle, subdir FROM media WHERE imdb_id=?", (x[1],))
                mediumData = self.c.fetchall()
                if len(mediumData) == 0 or mediumData[0][2] != None:
                    continue

                #4b. check whether there are any connections TO x
                self.c.execute("SELECT * FROM media_connections WHERE foreign_imdb_id=?", (x[1],))
                remainingConnections = self.c.fetchall()

                #4b1. if yes: continue
                if len(remainingConnections) != 0:
                    continue

                #4b2. if no: remove media entry (media_interests rows are removed via ON DELETE CASCADE)
                else:
                    print("Removing referenced medium " + mediumData[0][1] + " from DB")
                    self.c.execute("DELETE FROM media WHERE imdb_id=?", (x[1],))

    def removeVanishedEpisode(self, episodeMedium):
        """Removes an episode that a fresh title.episode.tsv scan no longer lists at all (e.g. an
        announced season got cancelled) -- called only for a non-owned episode; an owned one raises
        before ever reaching this. Unlike removeSingleMedia's light-remove, this raises
        OfflineDatasetError if anything still references the episode: IMDb itself no longer
        considers it to exist, so anything in our DB still pointing at it is a genuine
        inconsistency to surface, not something to quietly preserve as a stub."""
        with self.conn:
            self.c.execute("SELECT * FROM media_connections WHERE foreign_imdb_id=?", (episodeMedium.imdb_id,))
            if len(self.c.fetchall()) != 0:
                raise OfflineDatasetError("episode " + episodeMedium.getIDString() + " (" + str(episodeMedium.originalTitle) +
                                           ") is no longer listed in title.episode.tsv, but is still referenced by other media")
            print("Removing episode " + str(episodeMedium.originalTitle) + " from DB (no longer listed in title.episode.tsv)")
            self.c.execute("DELETE FROM media_connections WHERE imdb_id=?", (episodeMedium.imdb_id,))
            self.c.execute("DELETE FROM media WHERE imdb_id=?", (episodeMedium.imdb_id,))
            if episodeMedium.series_imdb_id is not None:
                self.__pruneOrphanedSeries([episodeMedium.series_imdb_id])

    def refreshRatings(self, mediaDict):
        with self.conn:
            for imdbID, media in mediaDict.items():
                self.c.execute("UPDATE media SET rating_mul10=?, numVotes=? WHERE imdb_id=?", (media.rating_mul10, media.numVotes, imdbID))

    def refreshTitleBasics(self, mediaDict):
        """Writes back the fields ScrapeIMDbOffline.refreshTitleBasics may have updated in place --
        titleType, primaryTitle, originalTitle, endYear. startYear is deliberately not included: it's
        never allowed to change during a refresh (refreshTitleBasics raises before this would ever
        see a differing value), so there's nothing for it to write back."""
        with self.conn:
            for imdbID, media in mediaDict.items():
                self.c.execute("UPDATE media SET title_type_id=?, originalTitle=?, primaryTitle=?, endYear=? WHERE imdb_id=?",
                                (self.__getTitleTypeIDByTitleTypeName(media.titleType), media.originalTitle, media.primaryTitle, media.endYear, imdbID))

    def refreshPeople(self, peopleDict):
        """Writes back name/birth_year/death_year for every Person in peopleDict -- the people
        analogue of refreshTitleBasics, paired with ScrapeIMDbOffline.refreshPeople."""
        with self.conn:
            for imdbID, person in peopleDict.items():
                self.c.execute("UPDATE people SET name=?, birth_year=?, death_year=? WHERE imdb_id=?",
                                (person.name, person.birth_year, person.death_year, imdbID))

    def getAllMediaIDs(self):
        with self.conn:
            self.c.execute("SELECT imdb_id FROM media")
            return(self.c.fetchall())

    def getAllLocallyOwnedMediaIDs(self):
        """Like getAllMediaIDs, but only ids that are genuinely locally owned (subdir IS NOT NULL)
        right now -- unlike getAllMediaIDs, a referenced-only stub row doesn't count. Used where
        "does a row exist" isn't a strong enough test, e.g. main.py's readySeries check: a series
        can end up with a bare referenced-only stub row mid-sync (see step 9's connection-target
        fallback) despite being locally owned, and shouldn't be mistaken for actually being ready."""
        with self.conn:
            self.c.execute("SELECT imdb_id FROM media WHERE subdir IS NOT NULL")
            return(self.c.fetchall())

    def getDictWithImdbIDs(self):
        dbResult = self.getAllMediaIDs()
        resultDict = {}
        for entry in dbResult:
            resultDict[entry[0]] = Media(None, None, entry[0])
        return(resultDict)

    def getAllKnownInterestIDs(self):
        """Set of all IMDb interest ids already present in interest_enum (both genres and subgenres)."""
        with self.conn:
            self.c.execute("SELECT imdb_interest_id FROM interest_enum")
            return set(row[0] for row in self.c.fetchall())

    def getAllKnownPseudoGenreIDs(self):
        """Name -> imdb_interest_id map of already-known pseudo-genres: synthetic, negative ids
        minted for an IMDb taxonomy category (e.g. "Seasonal") that groups subgenres without being
        a real, individually taggable interest itself -- see ScrapeIMDbOnline.__classifyChips.
        Real genres/subgenres always have a positive id, so this can't collide with them."""
        with self.conn:
            self.c.execute("SELECT name, imdb_interest_id FROM interest_enum WHERE imdb_interest_id < 0")
            return {row[0]: row[1] for row in self.c.fetchall()}

    def getMediaIDsWithInterests(self):
        """Set of imdb_ids that already have at least one media_interests row."""
        with self.conn:
            self.c.execute("SELECT DISTINCT imdb_id FROM media_interests")
            return set(row[0] for row in self.c.fetchall())

    def ensureInterestExists(self, imdb_interest_id, name, description, parent_imdb_interest_id=None):
        """Insert a newly-discovered interest (genre or subgenre) into interest_enum if not already known."""
        with self.conn:
            self.c.execute("INSERT OR IGNORE INTO interest_enum VALUES (?, ?, ?, ?)", (imdb_interest_id, name, description, parent_imdb_interest_id))

    def getAllKnownLanguageIDs(self):
        """Set of all IMDb interest ids already known to be languages (in language_enum)."""
        with self.conn:
            self.c.execute("SELECT imdb_interest_id FROM language_enum")
            return set(row[0] for row in self.c.fetchall())

    def getNonEnglishLocallyOwnedMovieIDs(self):
        """Set of imdb_ids for locally-owned movies (subdir IS NOT NULL, title_type_name in
        Media.movieTitleTypes -- i.e. not a series or episode) whose DB-recorded language_id is
        not English (id 0). Queries the DB directly rather than trusting a freshly-rescanned Media
        object's in-memory language_id, which defaults to English for any title not newly scraped
        this run. Used by main.py's cover-backfill step to give non-English movies the same
        manual-only cover treatment as series."""
        with self.conn:
            self.c.execute("""SELECT m.imdb_id FROM media m
                JOIN title_type_enum tt ON m.title_type_id = tt.title_type_id
                WHERE m.subdir IS NOT NULL AND m.language_id != 0
                AND tt.title_type_name IN (""" + ",".join("?" for _ in Media.movieTitleTypes) + ")",
                tuple(Media.movieTitleTypes))
            return set(row[0] for row in self.c.fetchall())

    def ensureLanguageExists(self, imdb_interest_id, name, description):
        """Insert a newly-discovered language interest into language_enum if not already known."""
        with self.conn:
            self.c.execute("INSERT OR IGNORE INTO language_enum VALUES (?, ?, ?)", (imdb_interest_id, name, description))

    def getAllKnownPersonIDs(self):
        """Set of all person imdb_ids already present in people."""
        with self.conn:
            self.c.execute("SELECT imdb_id FROM people")
            return set(row[0] for row in self.c.fetchall())

    def ensurePersonExists(self, person):
        """Insert a newly-discovered person into people if not already known. Takes a Person object
        (rather than plain fields, unlike ensureInterestExists/ensureLanguageExists) since a person
        always carries all three fields together, resolved as a unit by
        ScrapeIMDbOffline.parsePeople before this is ever called."""
        with self.conn:
            self.c.execute("INSERT OR IGNORE INTO people VALUES (?, ?, ?, ?)", (person.imdb_id, person.name, person.birth_year, person.death_year))

    def getAllPersonObjects(self):
        """All people currently in the DB, as {imdb_id: Person} -- used by refreshTitleData to
        refresh name/birth_year/death_year against the current name.basics.tsv."""
        with self.conn:
            self.c.execute("SELECT imdb_id, name, birth_year, death_year FROM people")
            result = {}
            for imdb_id, name, birth_year, death_year in self.c.fetchall():
                person = Person(imdb_id, name)
                person.birth_year = birth_year
                person.death_year = death_year
                result[imdb_id] = person
            return result

    def getAllKnownFranchiseIDs(self):
        """Set of all IMDb interest ids already known to be franchise-type (in franchise_interest_ids
        -- see ScrapeIMDbOnline.__classifyChips)."""
        with self.conn:
            self.c.execute("SELECT imdb_interest_id FROM franchise_interest_ids")
            return set(row[0] for row in self.c.fetchall())

    def ensureFranchiseInterestExists(self, imdb_interest_id):
        """Records a newly-discovered franchise-type interest id into franchise_interest_ids if not
        already known, so it's skipped without re-classification on future syncs."""
        with self.conn:
            self.c.execute("INSERT OR IGNORE INTO franchise_interest_ids VALUES (?)", (imdb_interest_id,))

    def syncWebProvidersFromConfig(self, web_providers):
        """Additively syncs source_web_provider_enum from a {abbreviation: full_name} dict (see
        config.WEB_PROVIDERS). Only ever inserts; never updates or removes an existing row, so the
        enum -- not config -- remains the actual source of truth (see createMediaDB's comment on
        this table). Meant to be called on every sync."""
        with self.conn:
            for abbreviation, full_name in web_providers.items():
                self.c.execute("INSERT OR IGNORE INTO source_web_provider_enum (abbreviation, full_name) VALUES (?, ?)", (abbreviation, full_name))

    def checkWebProvidersKnown(self, mediaDict):
        """Raises LocalLibraryError listing every web provider abbreviation referenced by
        mediaDict's local sources that isn't (yet) in source_web_provider_enum. Meant to be called
        right after the local scan and syncWebProvidersFromConfig, before any online scraping --
        this only depends on locally-scraped source strings, so there's no reason to only discover
        a config.ini gap at DB-write time, after a full sync's worth of scraping already ran."""
        usedAbbreviations = set()
        for medium in mediaDict.values():
            for mediaVersion in medium.mediaVersions:
                for source in mediaVersion.sources:
                    if source.web_provider is not None:
                        usedAbbreviations.add(source.web_provider)
        with self.conn:
            self.c.execute("SELECT abbreviation FROM source_web_provider_enum")
            knownAbbreviations = {row[0] for row in self.c.fetchall()}
        missing = usedAbbreviations - knownAbbreviations
        if missing:
            raise LocalLibraryError("unknown web provider abbreviation(s) " + ", ".join(sorted(missing)) +
                                     " -- add them to config.ini's [web_providers] section and sync again")

    def syncIgnoredAndWontaddIDs(self, ignored_ids, wontadd_ids):
        """Non-additively syncs ignored_ids/wontadd_ids from the given sets of imdb ids (see
        config.IGNORED_IDS_PATH/WONTADD_IDS_PATH) -- unlike syncWebProvidersFromConfig, removing
        an id from the source list actually removes it here, since these lists are meant to be
        fully user-editable. Meant to be called on every sync, before enforceIgnoredAndWontaddIDs."""
        with self.conn:
            self.c.execute("DELETE FROM ignored_ids")
            self.c.executemany("INSERT INTO ignored_ids VALUES (?)", [(imdb_id,) for imdb_id in ignored_ids])
            self.c.execute("DELETE FROM wontadd_ids")
            self.c.executemany("INSERT INTO wontadd_ids VALUES (?)", [(imdb_id,) for imdb_id in wontadd_ids])

    def enforceIgnoredAndWontaddIDs(self):
        """Enforces ignored_ids/wontadd_ids against the current DB state: raises LocalLibraryError
        if any locally-owned medium's id is on ignored_ids (this list is about whether a title
        deserves to exist in the DB at all -- never allowed to be locally owned, regardless of
        type), or on wontadd_ids while not being a series (wontadd_ids is about local-ownership
        effort, not worthiness of existing in the DB -- honoring a title's existence but declining
        to chase it down locally; for a series specifically this only ever means "no more episodes
        of this series are planned to be added", not a blanket ban -- an already- or newly-owned
        episode is fine, and the rest still get cataloged as referenced-only stubs like any other
        partially-owned series, same as if the series weren't on the list at all; wontadd here only
        keeps such a series' still-unowned episodes out of any to-be-added list generated from the
        DB). Also removes any referenced-only medium whose id is on ignored_ids -- fully, regardless
        of what still references it, unlike removeSingleMedia's "light-remove" (which exists for
        media that merely stopped being locally owned, not for media that must never be in the DB
        at all). Meant to be called right after syncIgnoredAndWontaddIDs, at the very start of every
        sync (before any local scanning/scraping) -- this reconciles drift left over from a list
        edited since the last sync. New violations introduced during the rest of the sync itself are
        instead caught on the go: newly-added local media are checked right after the local scan,
        and newly-discovered referenced ids on ignored_ids are simply never added in the first place,
        so nothing new for this method to clean up accumulates by the end."""
        with self.conn:
            self.c.execute("""SELECT m.imdb_id, m.originalTitle FROM media m
                JOIN title_type_enum tt ON m.title_type_id = tt.title_type_id
                WHERE m.subdir IS NOT NULL
                AND (
                    m.imdb_id IN (SELECT imdb_id FROM ignored_ids)
                    OR (m.imdb_id IN (SELECT imdb_id FROM wontadd_ids)
                        AND tt.title_type_name NOT IN (""" + ",".join("?" for _ in Media.seriesTitleTypes) + """))
                )""", tuple(Media.seriesTitleTypes))
            violatingLocal = self.c.fetchall()
        if violatingLocal:
            raise LocalLibraryError("locally-owned media found on the ignored/wontadd list(s): " +
                                     ", ".join(row[1] + " (tt" + str(row[0]).zfill(7) + ")" for row in violatingLocal))

        with self.conn:
            self.c.execute("""SELECT imdb_id, originalTitle, series_imdb_id FROM media WHERE subdir IS NULL
                AND imdb_id IN (SELECT imdb_id FROM ignored_ids)""")
            referencedIgnored = self.c.fetchall()
            for imdb_id, originalTitle, series_imdb_id in referencedIgnored:
                print("Removing referenced medium " + originalTitle + " from DB (now on ignored list)")
                self.c.execute("SELECT imdb_interest_id FROM media_interests WHERE imdb_id=?", (imdb_id,))
                affectedInterestIDs = [row[0] for row in self.c.fetchall()]
                self.c.execute("SELECT language_id FROM media WHERE imdb_id=?", (imdb_id,))
                affectedLanguageIDs = [row[0] for row in self.c.fetchall()]
                self.c.execute("SELECT person_id FROM credits WHERE imdb_id=?", (imdb_id,))
                affectedPersonIDs = [row[0] for row in self.c.fetchall()]

                # an ignored series must go regardless of any episode still needing it -- unlike
                # normal removal, "ignored" means gone no matter what, so its episodes are forced
                # out too (no-op if imdb_id isn't a series)
                self.c.execute("SELECT imdb_id FROM media WHERE series_imdb_id=?", (imdb_id,))
                for (episode_id,) in self.c.fetchall():
                    self.c.execute("DELETE FROM media_connections WHERE imdb_id=? OR foreign_imdb_id=?", (episode_id, episode_id))
                    self.c.execute("DELETE FROM media WHERE imdb_id=?", (episode_id,))

                self.c.execute("DELETE FROM media_connections WHERE imdb_id=? OR foreign_imdb_id=?", (imdb_id, imdb_id))
                self.c.execute("DELETE FROM media WHERE imdb_id=?", (imdb_id,))
                self.__pruneOrphanedInterests(affectedInterestIDs)
                self.__pruneOrphanedLanguages(affectedLanguageIDs)
                self.__pruneOrphanedPeople(affectedPersonIDs)

                # if imdb_id was itself an episode, its parent series might now be orphaned
                if series_imdb_id is not None:
                    self.__pruneOrphanedSeries([series_imdb_id])

    def __pruneOrphanedInterests(self, imdb_interest_ids):
        """Removes any of the given interests (genre or subgenre) from interest_enum once they're
        no longer attached to any medium (media_interests) AND no longer have any subgenre
        depending on them as a parent. The second condition is always true for subgenres (nothing
        is ever a subgenre's child in this two-level taxonomy), so it only meaningfully restricts
        genres: a genre survives as long as it's either directly used, or still has a live
        subgenre under it. When a subgenre is pruned, its parent genre is re-checked too, since
        losing that subgenre may make the parent newly eligible."""
        idsToCheck = list(imdb_interest_ids)
        while idsToCheck:
            imdb_interest_id = idsToCheck.pop()

            self.c.execute("SELECT parent_imdb_interest_id FROM interest_enum WHERE imdb_interest_id = ?", (imdb_interest_id,))
            row = self.c.fetchone()
            if row is None:
                continue # already pruned (e.g. via an earlier id in this same batch), or never existed
            parent_id = row[0]

            self.c.execute("""
                DELETE FROM interest_enum
                WHERE imdb_interest_id = ?
                AND NOT EXISTS (SELECT 1 FROM media_interests WHERE imdb_interest_id = ?)
                AND NOT EXISTS (SELECT 1 FROM interest_enum WHERE parent_imdb_interest_id = ?)
            """, (imdb_interest_id, imdb_interest_id, imdb_interest_id))

            if self.c.rowcount > 0 and parent_id is not None:
                idsToCheck.append(parent_id)

    def __pruneOrphanedLanguages(self, imdb_interest_ids):
        """Removes any of the given languages from language_enum once no medium uses them anymore.
        English (id 0) is never pruned, since it's the permanent default media.language_id falls
        back to (and is required to exist by that column's foreign key)."""
        for imdb_interest_id in imdb_interest_ids:
            if imdb_interest_id == 0:
                continue
            self.c.execute("""
                DELETE FROM language_enum
                WHERE imdb_interest_id = ?
                AND NOT EXISTS (SELECT 1 FROM media WHERE language_id = ?)
            """, (imdb_interest_id, imdb_interest_id))

    def __pruneOrphanedPeople(self, person_ids):
        """Removes any of the given people from people once no credits row references them anymore
        -- the credits/people analogue of __pruneOrphanedInterests/__pruneOrphanedLanguages."""
        for person_id in person_ids:
            self.c.execute("""
                DELETE FROM people
                WHERE imdb_id = ?
                AND NOT EXISTS (SELECT 1 FROM credits WHERE person_id = ?)
            """, (person_id, person_id))

    def __removeUnneededSeriesEpisodes(self, series_imdb_id):
        """Removes every episode of the given series that's neither locally owned nor referenced by
        anything else (media_connections). Returns True if none remain afterward -- i.e. the series
        itself has no more reason to exist because of its episodes -- or False if at least one is
        still needed, in which case the series must survive too (series_imdb_id's FK requires the
        series row to exist as long as any episode points at it). A no-op, returning True, for a
        medium that isn't a series (nothing ever has series_imdb_id pointing at a movie/episode)."""
        self.c.execute("SELECT imdb_id, originalTitle, subdir FROM media WHERE series_imdb_id=?", (series_imdb_id,))
        episodes = self.c.fetchall()
        anyStillNeeded = False
        for episode_id, episode_title, episode_subdir in episodes:
            if episode_subdir is not None:
                anyStillNeeded = True
                continue
            self.c.execute("SELECT * FROM media_connections WHERE foreign_imdb_id=?", (episode_id,))
            if len(self.c.fetchall()) != 0:
                anyStillNeeded = True
                continue
            print("Removing episode " + str(episode_title) + " from DB (no longer needed)")
            self.c.execute("DELETE FROM media_connections WHERE imdb_id=? OR foreign_imdb_id=?", (episode_id, episode_id))
            self.c.execute("DELETE FROM media WHERE imdb_id=?", (episode_id,))
        return not anyStillNeeded

    def __pruneOrphanedSeries(self, series_imdb_ids):
        """Removes any of the given series once it's no longer locally owned, no longer referenced
        by anything else, and has no episode still depending on it either (via
        __removeUnneededSeriesEpisodes) -- the series/episode analogue of __pruneOrphanedInterests's
        genre/subgenre shape. Unlike that one, no further cascading re-check is needed here: a
        series has no "parent" of its own to affect once it's gone."""
        for series_imdb_id in series_imdb_ids:
            self.c.execute("SELECT subdir, originalTitle FROM media WHERE imdb_id=?", (series_imdb_id,))
            row = self.c.fetchone()
            if row is None or row[0] is not None:
                continue # already removed, never existed, or still locally owned
            self.c.execute("SELECT * FROM media_connections WHERE foreign_imdb_id=?", (series_imdb_id,))
            if len(self.c.fetchall()) != 0:
                continue # still referenced by something else
            if not self.__removeUnneededSeriesEpisodes(series_imdb_id):
                continue # still has a needed episode
            print("Removing series " + str(row[1]) + " from DB (no longer needed)")
            self.c.execute("DELETE FROM media_connections WHERE imdb_id=? OR foreign_imdb_id=?", (series_imdb_id, series_imdb_id))
            self.c.execute("DELETE FROM media WHERE imdb_id=?", (series_imdb_id,))

    def __getTitleTypeIDByTitleTypeName(self, title_type_name):
        with self.conn:
            self.c.execute("SELECT title_type_id FROM title_type_enum WHERE title_type_name=?", (title_type_name,))
            title_type_id = self.c.fetchone()
            if not title_type_id or not title_type_id[0]:
                raise RuntimeError('unknown titleType ' + title_type_name)
            return(title_type_id[0])

    def __getTitleTypeNameByTitleTypeID(self, title_type_id):
        with self.conn:
            self.c.execute("SELECT title_type_name FROM title_type_enum WHERE title_type_id=?", (title_type_id,))
            title_type_name = self.c.fetchone()
            if not title_type_name or not title_type_name[0]:
                raise RuntimeError('unknown titleType ID ' + str(title_type_id))
            return(title_type_name[0])

    def __getConnectionTypeIDByConnectionTypeName(self, connectionType_name):
        with self.conn:
            self.c.execute("SELECT connection_type_id FROM connection_type_enum WHERE connection_type_name=?", (connectionType_name,))
            connection_type_id = self.c.fetchone()
            if not connection_type_id or not connection_type_id[0]:
                raise RuntimeError('unknown connection type ' + connectionType_name)
            return(connection_type_id[0])

    def __getConnectionTypeNameByConnectionTypeID(self, connectionType_id):
        with self.conn:
            self.c.execute("SELECT connection_type_name FROM connection_type_enum WHERE connection_type_id=?", (connectionType_id,))
            connection_type_name = self.c.fetchone()
            if not connection_type_name or not connection_type_name[0]:
                raise RuntimeError('unknown connection type ' + str(connectionType_id))
            return(connection_type_name[0])

    def __getCreditRoleIDByCreditRoleName(self, credit_role_name):
        # credit_role_name always comes from Credit.creditRoleList, which is what seeds this enum,
        # so a miss here means the two have drifted -- an internal bug, not bad local data
        with self.conn:
            self.c.execute("SELECT credit_role_id FROM credit_role_enum WHERE credit_role_name=?", (credit_role_name,))
            credit_role_id = self.c.fetchone()
            if not credit_role_id:
                raise RuntimeError('unknown credit role ' + credit_role_name)
            return(credit_role_id[0])

    def __getSourceTypeIDByName(self, source_type_name):
        # source_type_name always comes from Media.source_type_list, which is what seeds this
        # enum, so a miss here means the two have drifted -- an internal bug, not bad local data
        with self.conn:
            self.c.execute("SELECT source_type_id FROM source_type_enum WHERE source_type_name=?", (source_type_name,))
            source_type_id = self.c.fetchone()
            if not source_type_id:
                raise RuntimeError('unknown source type ' + source_type_name)
            return(source_type_id[0])

    def __getSourceRoleIDByName(self, role_name):
        # role_name always comes from Media.source_role_list, which is what seeds this enum, so
        # a miss here means the two have drifted -- an internal bug, not bad local data
        with self.conn:
            self.c.execute("SELECT role_id FROM source_role_enum WHERE role_name=?", (role_name,))
            role_id = self.c.fetchone()
            if not role_id:
                raise RuntimeError('unknown source role ' + role_name)
            return(role_id[0])

    def __getWebProviderIDByAbbreviation(self, abbreviation):
        # unlike the two lookups above, a miss here is a genuine local-data problem: the source
        # string references a web provider abbreviation not present in source_web_provider_enum
        # (and therefore not in config.ini's [web_providers] section either, at least not as of
        # the last sync -- see DBControl.syncWebProvidersFromConfig)
        with self.conn:
            self.c.execute("SELECT web_provider_id FROM source_web_provider_enum WHERE abbreviation=?", (abbreviation,))
            web_provider_id = self.c.fetchone()
            if not web_provider_id:
                raise LocalLibraryError("unknown web provider abbreviation '" + abbreviation + "' -- add it to config.ini's [web_providers] section and sync again")
            return(web_provider_id[0])

    def determineNewlyAddedMedia(self, mediaDict):
        newlyAddedDict = {}
        with self.conn:
            for medium in mediaDict.values():
                self.c.execute("SELECT originalTitle, subdir FROM media WHERE imdb_id = ?", (medium.imdb_id,)) # need to get originalTitle as well, as otherwise no NULL subdirs will be returned
                data = self.c.fetchall()
                if len(data) == 0 or data[0][1] == None:
                    newlyAddedDict[medium.imdb_id] = medium
        return newlyAddedDict

    def determineLocallyRemovedMedia(self, mediaDict):
        removedDict = {}
        with self.conn:
            self.c.execute("SELECT imdb_id, originalTitle, series_imdb_id FROM media WHERE media.subdir IS NOT NULL")
            data = self.c.fetchall()
            for db_medium in data:
                if db_medium[0] not in mediaDict:
                    removedMedium = Media(None, None, db_medium[0])
                    removedMedium.originalTitle = db_medium[1]
                    removedMedium.series_imdb_id = db_medium[2]
                    removedDict[removedMedium.imdb_id] = removedMedium
        return removedDict

    def getReferencedOnlyMedia(self):
        with self.conn:
            self.c.execute("SELECT originalTitle, startYear, rating_mul10, numVotes FROM media WHERE subdir IS NULL ORDER BY numVotes DESC")
            return(self.c.fetchall())

    def __getMovieObjectFromDBRow(self, dbRow):
        # imdb_id, title_type_id, originalTitle, primaryTitle, startYear, endYear, rating_mul10, numVotes, releaseMonth, releaseDay, subdir, language_id, plotSummary, season_number, episode_number, series_imdb_id, intended_order
        mediaObject = Media(None, None, dbRow[0])
        mediaObject.originalTitle = dbRow[2]
        mediaObject.primaryTitle = dbRow[3]
        mediaObject.startYear = dbRow[4]
        mediaObject.endYear = dbRow[5]
        mediaObject.rating_mul10 = dbRow[6]
        mediaObject.numVotes = dbRow[7]
        mediaObject.releaseMonth = dbRow[8]
        mediaObject.releaseDay = dbRow[9]
        mediaObject.subdir = dbRow[10]
        mediaObject.language_id = dbRow[11]
        mediaObject.plotSummary = dbRow[12]
        mediaObject.season_number = dbRow[13]
        mediaObject.episode_number = dbRow[14]
        mediaObject.series_imdb_id = dbRow[15]
        mediaObject.intended_order = dbRow[16]
        mediaObject.titleType = self.__getTitleTypeNameByTitleTypeID(dbRow[1])
        mediaObject.interests = self.__getInterestIDList(dbRow[0])
        mediaObject.mediaVersions = self.__getMediaVersionList(dbRow[0])
        mediaObject.mediaConnections = self.__getMediaConnectionsList(dbRow[0])
        return mediaObject

    def __getInterestIDList(self, imdbID):
        with self.conn:
            self.c.execute("SELECT imdb_interest_id FROM media_interests WHERE imdb_id=?", (imdbID,))
            return [row[0] for row in self.c.fetchall()]

    def __getMediaVersionList(self, imdbID):
        with self.conn:
            self.c.execute("SELECT * FROM media_versions WHERE imdb_id=?", (imdbID,))
            dbResult = self.c.fetchall()
            resultList = []
            for mediaVersionRow in dbResult:
                resultList.append(MediaVersion(mediaVersionRow[1], mediaVersionRow[2], mediaVersionRow[3]))
            return resultList

    def __getMediaConnectionsList(self, imdbID):
        with self.conn:
            self.c.execute("SELECT * FROM media_connections WHERE imdb_id=?", (imdbID,))
            dbResult = self.c.fetchall()
            resultList = []
            for mediaConnectionRow in dbResult:
                resultList.append(MediaConnection(mediaConnectionRow[1], self.__getConnectionTypeNameByConnectionTypeID(mediaConnectionRow[2])))
            return resultList

    def getAllMovieObjects(self):
        resultDict = {}
        with self.conn:
            self.c.execute("SELECT * FROM media")
            dbResult = self.c.fetchall()
            for dbRow in dbResult:
                resultDict[dbRow[0]] = self.__getMovieObjectFromDBRow(dbRow)
        return resultDict
