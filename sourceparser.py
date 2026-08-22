from exceptions import LocalLibraryError
from mediasource import MediaSource

# all keyword/structural tokens are matched case-insensitively; only a web provider abbreviation
# (user-defined data, matched against config.WEB_PROVIDERS later) is kept verbatim
_BARE_TYPE_TOKENS = ("tv", "vhs", "hifivhs", "ld", "di", "kscape", "hddvd")
_DISC_TYPE_TOKENS = ("dvd", "br", "uhd")

def parseSourceString(raw_string):
    """Parses a 'src-...' source identifier (see scrapelocal.py's sources.txt/src-*.txt
    convention) into a list of MediaSource objects, one per leaf source. Does not validate
    source_type/web_provider against the database enums -- that happens when these are written
    to the database, same as titleType/connectionType elsewhere in this codebase. Raises
    LocalLibraryError on anything that doesn't parse."""

    if not raw_string.lower().startswith("src-"):
        raise LocalLibraryError("source string must start with 'src-': " + raw_string)

    tokens = raw_string[len("src-"):].split("-")
    if tokens == [""]:
        raise LocalLibraryError("empty source string: " + raw_string)

    tokensLower = [t.lower() for t in tokens]

    if tokensLower[:2] == ["hybrid", "dynhdrhybrid"]:
        roles = ["video_base", "video_dynhdr", "audio"]
        tokens = tokens[2:]
    elif tokensLower[:1] == ["dynhdrhybrid"]:
        roles = ["video_base", "video_dynhdr"]
        tokens = tokens[1:]
    elif tokensLower[:1] == ["hybrid"]:
        roles = ["video", "audio"]
        tokens = tokens[1:]
    else:
        roles = ["main"]

    try:
        return _parseRoles(tokens, roles)
    except LocalLibraryError as e:
        raise LocalLibraryError("could not parse source string '" + raw_string + "': " + str(e))

def _parseRoles(tokens, roles):
    """Parses tokens against a sequence of roles (in composition order), backtracking through
    fanres group-length choices as needed until some split consumes every token. Raises
    LocalLibraryError (from the deepest/last attempt) if no valid split exists."""

    if len(roles) == 0:
        if len(tokens) != 0:
            raise LocalLibraryError("unexpected trailing content: " + "-".join(tokens))
        return []

    role = roles[0]
    candidates = _parseSlotCandidates(tokens, role)

    lastError = None
    for sources, remaining in candidates:
        try:
            return sources + _parseRoles(remaining, roles[1:])
        except LocalLibraryError as e:
            lastError = e
            continue
    raise lastError

def _parseSlotCandidates(tokens, role):
    """Returns every possible way to parse one slot (a single leaf source, or a fanres group of
    N>=1 leaf sources) for the given role, as a list of (sources, remainingTokens) tuples,
    shortest fanres group first. A plain (non-fanres) slot always has exactly one candidate,
    since a single leaf source's extent is unambiguous once you start parsing it."""

    if tokens and tokens[0].lower() == "fanres":
        remaining = tokens[1:]
        candidates = []
        sources = []
        seq = 1
        while True:
            try:
                # a fanres member always takes its most greedy reading -- see
                # _parseLeafSourceCandidates for why a member can have more than one
                source, remaining = _parseLeafSourceCandidates(remaining, role, fanres=True, seq=seq)[0]
            except LocalLibraryError:
                break
            sources = sources + [source]
            candidates.append((list(sources), remaining))
            seq += 1
        if not candidates:
            raise LocalLibraryError("'fanres-' must be followed by at least one source")
        return candidates
    else:
        return [([source], remaining) for source, remaining in _parseLeafSourceCandidates(tokens, role, fanres=False, seq=1)]

def _parseLeafSourceCandidates(tokens, role, fanres, seq):
    """Parses exactly one leaf source from the start of tokens, returning every plausible reading
    as a list of (MediaSource, remainingTokens) tuples, most-greedy first. Most source kinds are
    unambiguous and yield a single candidate; WEB-DL/WEBRip's optional trailing provider token is
    ambiguous whenever the token that follows could equally well belong to whatever comes next
    (e.g. in 'hybrid-WEB-DL-br-1', is 'br' the provider, or the start of the audio role's own
    source?), so both readings are offered here and _parseRoles backtracks into the second one if
    the greedy (provider-consumed) reading fails to let the rest of the source string parse.
    Raises LocalLibraryError if tokens doesn't start with a recognizable leaf source at all."""

    if len(tokens) == 0:
        raise LocalLibraryError("expected a source, found nothing")

    first = tokens[0]
    firstLower = first.lower()

    if firstLower in _DISC_TYPE_TOKENS:
        if len(tokens) < 2 or not tokens[1].isdigit():
            raise LocalLibraryError("expected a numeric disc id after '" + first + "-'")
        disc_id = int(tokens[1])
        rest = tokens[2:]
        disc_corrected = False
        if rest[:1] and rest[0].lower() == "corrected":
            disc_corrected = True
            rest = rest[1:]
        base_layer, downmixed, core, rest = _parseModifiers(rest)
        return [(MediaSource(role, firstLower, disc_id=disc_id, disc_corrected=disc_corrected,
                              base_layer=base_layer, downmixed=downmixed, core=core, fanres=fanres, seq=seq), rest)]

    if firstLower in _BARE_TYPE_TOKENS:
        rest = tokens[1:]
        base_layer, downmixed, core, rest = _parseModifiers(rest)
        return [(MediaSource(role, firstLower, base_layer=base_layer, downmixed=downmixed, core=core,
                              fanres=fanres, seq=seq), rest)]

    if firstLower == "web" and tokens[1:2] and tokens[1].lower() == "dl":
        return _parseWebLikeCandidates(tokens[2:], "web-dl", role, fanres, seq)

    if firstLower == "webrip":
        return _parseWebLikeCandidates(tokens[1:], "webrip", role, fanres, seq)

    raise LocalLibraryError("unrecognized source token '" + first + "'")

def _parseWebLikeCandidates(tokens, source_type, role, fanres, seq):
    """Returns the possible readings of a WEB-DL/WEBRip source's optional trailing provider token,
    greedy (provider consumed) first, falling back to a reading where the token is left alone for
    whatever comes next to consume."""
    candidates = []
    provider, restWithProvider = _parseOptionalProvider(tokens)
    if provider is not None:
        base_layer, downmixed, core, rest = _parseModifiers(restWithProvider)
        candidates.append((MediaSource(role, source_type, web_provider=provider, base_layer=base_layer,
                                        downmixed=downmixed, core=core, fanres=fanres, seq=seq), rest))
    base_layer, downmixed, core, rest = _parseModifiers(tokens)
    candidates.append((MediaSource(role, source_type, web_provider=None, base_layer=base_layer,
                                    downmixed=downmixed, core=core, fanres=fanres, seq=seq), rest))
    return candidates

def _parseModifiers(tokens):
    """Consumes the optional trailing -bl, -downmixed and -core modifiers, in that fixed order."""
    base_layer = False
    downmixed = False
    core = False
    if tokens[:1] and tokens[0].lower() == "bl":
        base_layer = True
        tokens = tokens[1:]
    if tokens[:1] and tokens[0].lower() == "downmixed":
        downmixed = True
        tokens = tokens[1:]
    if tokens[:1] and tokens[0].lower() == "core":
        core = True
        tokens = tokens[1:]
    return base_layer, downmixed, core, tokens

def _parseOptionalProvider(tokens):
    """A web provider abbreviation is a single token that isn't itself a -bl/-downmixed/-core
    modifier. Kept verbatim (not case-normalized) since it's user-defined data matched against
    config.WEB_PROVIDERS elsewhere, not a parser keyword."""
    if tokens and tokens[0].lower() not in ("bl", "downmixed", "core"):
        return tokens[0], tokens[1:]
    return None, tokens
