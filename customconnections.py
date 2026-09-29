"""Parses and expands custom_connections.txt (see config.CUSTOM_CONNECTIONS_PATH) into the full set
of directional (source, target, connection_type_name) facts it implies. One line per real-world
relationship, using any of MediaConnection.connectionTypeList's 8 keywords as the relation word,
read as "source <relation> target ..." (subject-verb-object, so e.g. "tt1 spin_off_from tt2" means
tt1 is a spin-off from tt2). Reconciled against the DB at the end of every sync run (see main.py's
reconcileCustomConnections) -- this module only does the pure text-to-facts expansion, no DB access
and no notion of what's currently valid or already stored.
"""
import os

from mediaconnection import MediaConnection

# the reciprocal type for each of the 8 known connection types, or None if the type has no
# reciprocal -- version_of/alternate_language_version_of: IMDb doesn't track a reverse category for
# these either, and for a custom group the "reverse" is simply another edge of the same type, not a
# distinct one (see expandLine)
RECIPROCAL = {
    "follows": "followed_by", "followed_by": "follows",
    "remake_of": "remade_as", "remade_as": "remake_of",
    "spin_off": "spin_off_from", "spin_off_from": "spin_off",
    "version_of": None, "alternate_language_version_of": None,
}

# follows/followed_by: an ordered chain, closes over every pair (not just adjacent ones) -- an
# unowned intermediate title would otherwise permanently block visibility between the chain's
# endpoints, since each directional row activates independently on its own source's ownership (see
# main.py's reconcileCustomConnections)
CHAIN_TYPES = {"follows", "followed_by"}

# version_of/alternate_language_version_of: an unstructured, undirected group -- closes over the
# full clique (every pair, both directions, same type), since there's no direction within the group
GROUP_TYPES = {"version_of", "alternate_language_version_of"}

# remake_of/spin_off_from and their reverses: strictly 1:1, no chain/group concept -- exactly two
# ids per line
PAIR_ONLY_TYPES = set(MediaConnection.connectionTypeList) - CHAIN_TYPES - GROUP_TYPES


class CustomConnectionError(Exception):
    """Raised for one malformed/invalid line. Always caught and turned into a warning by the
    caller (parseFile), never allowed to propagate further -- a bad line is skipped, not a reason to
    abort the whole file or the sync, since the file is fully re-read and re-evaluated fresh every
    run anyway (see main.py's reconcileCustomConnections)."""


def parseLine(tokens, lineNumber):
    """tokens: the whitespace-split tokens of one line, e.g. ["tt0468569", "spin_off_from",
    "tt1234567"]. Returns (ids, relationType): ids is the list of imdb_id ints in order,
    relationType is the single relation keyword used throughout (mixing keywords within one line,
    or repeating the same id, is rejected). Raises CustomConnectionError on anything malformed."""
    if len(tokens) < 3 or len(tokens) % 2 == 0:
        raise CustomConnectionError("line " + str(lineNumber) + ": expected 'tt_id relation tt_id "
                                     "[relation tt_id ...]', got: " + " ".join(tokens))

    ids = []
    relations = []
    for i, token in enumerate(tokens):
        if i % 2 == 0:
            if not (token.startswith("tt") and token[2:].isdigit()):
                raise CustomConnectionError("line " + str(lineNumber) + ": '" + token + "' is not a valid imdb id")
            ids.append(int(token[2:]))
        else:
            if token not in MediaConnection.connectionTypeList:
                raise CustomConnectionError("line " + str(lineNumber) + ": unknown relation '" + token +
                                             "' (expected one of: " + ", ".join(MediaConnection.connectionTypeList) + ")")
            relations.append(token)

    if len(set(ids)) != len(ids):
        raise CustomConnectionError("line " + str(lineNumber) + ": the same id appears more than once: " + " ".join(tokens))

    if len(set(relations)) != 1:
        raise CustomConnectionError("line " + str(lineNumber) + ": a chain must use one consistent relation "
                                     "throughout, got: " + ", ".join(relations))
    relationType = relations[0]

    if relationType in PAIR_ONLY_TYPES and len(ids) != 2:
        raise CustomConnectionError("line " + str(lineNumber) + ": '" + relationType +
                                     "' only accepts exactly two ids, got " + str(len(ids)))

    return ids, relationType


def expandLine(ids, relationType):
    """Returns the full set of (source, target, connection_type_name) facts this one parsed line
    implies -- see CHAIN_TYPES/GROUP_TYPES/PAIR_ONLY_TYPES above for which expansion applies."""
    facts = set()

    def addPairWithReciprocal(a, b, relType):
        facts.add((a, b, relType))
        reciprocal = RECIPROCAL[relType]
        if reciprocal is not None:
            facts.add((b, a, reciprocal))

    if relationType in GROUP_TYPES:
        for a in ids:
            for b in ids:
                if a != b:
                    facts.add((a, b, relationType))
    else:
        # PAIR_ONLY_TYPES (len(ids) == 2, enforced in parseLine) and CHAIN_TYPES (full transitive
        # closure: every i < j pair, not just adjacent ones -- ids[i] is always earlier/original/
        # whatever relationType means for every later ids[j], not just its immediate neighbor)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                addPairWithReciprocal(ids[i], ids[j], relationType)

    return facts


# the two 1:1 pair families that can directly contradict each other -- follows/followed_by is
# handled separately below (transitive, needs graph reachability, not just a direct-pair lookup)
PAIR_FAMILIES = [frozenset({"remake_of", "remade_as"}), frozenset({"spin_off", "spin_off_from"})]


def normalizeFollowsEdge(imdb_id, foreign_imdb_id, connection_type_name):
    """Normalizes one follows/followed_by row into an (earlier, later) pair in a single
    chronological-order direction, so both types share one graph representation."""
    if connection_type_name == "follows":
        return (foreign_imdb_id, imdb_id)  # imdb_id follows foreign_imdb_id -> foreign is earlier
    return (imdb_id, foreign_imdb_id)  # followed_by: imdb_id followed_by foreign_imdb_id -> imdb_id is earlier


def buildFollowsGraph(edges):
    """edges: iterable of (imdb_id, foreign_imdb_id, connection_type_name) tuples, already filtered
    to follows/followed_by. Returns an adjacency dict {earlier_id: {later_id, ...}}."""
    graph = {}
    for imdb_id, foreign_imdb_id, connection_type_name in edges:
        earlier, later = normalizeFollowsEdge(imdb_id, foreign_imdb_id, connection_type_name)
        graph.setdefault(earlier, set()).add(later)
    return graph


def addFollowsEdge(graph, earlier, later):
    graph.setdefault(earlier, set()).add(later)


def _isReachable(graph, start, target):
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        if node == target:
            return True
        for neighbor in graph.get(node, ()):
            if neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return False


def wouldCreateFollowsCycle(graph, earlier, later):
    """Would adding an edge earlier->later close a cycle -- i.e. is `earlier` already reachable FROM
    `later` via some existing path (later already established as preceding earlier)? A direct
    reversal (the exact opposite edge already there) is just the length-1 special case of this."""
    return _isReachable(graph, later, earlier)


def wouldContradictPairEdge(existingEdges, imdb_id, foreign_imdb_id, connection_type_name):
    """existingEdges: {(imdb_id, foreign_imdb_id, connection_type_name)} already on record for the
    relevant 1:1 pair family (see PAIR_FAMILIES). True if the opposite direction/meaning for this
    exact pair is already there -- e.g. about to add (a,b,remake_of), but (b,a,remake_of) [reversed]
    or (a,b,remade_as) [reciprocal type, same pair] already exists."""
    reciprocal = RECIPROCAL[connection_type_name]
    return ((foreign_imdb_id, imdb_id, connection_type_name) in existingEdges or
            (imdb_id, foreign_imdb_id, reciprocal) in existingEdges)


def parseFile(path, warn):
    """Reads path (a custom_connections.txt-formatted file) and returns the union of every valid
    line's expandLine() result, as a set of (source, target, connection_type_name) tuples. A '#'
    starts a comment, either on its own line or trailing after a relationship -- everything from '#'
    onward on a line is discarded before parsing. A missing file is treated as empty, same
    convention as main.py's readIDList. Any malformed line is passed to warn(message) and skipped
    entirely -- never raises, so one bad line never blocks every other line in the file."""
    if not os.path.exists(path):
        return set()

    facts = set()
    with open(path, "r") as f:
        for lineNumber, line in enumerate(f, 1):
            tokens = line.split("#", 1)[0].split()
            if not tokens:
                continue
            try:
                ids, relationType = parseLine(tokens, lineNumber)
                facts |= expandLine(ids, relationType)
            except CustomConnectionError as e:
                warn(str(e))
    return facts
