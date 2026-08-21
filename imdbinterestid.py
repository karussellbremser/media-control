import re

def parseInterestID(idString):
    """Converts an IMDb interest id string (e.g. "in0000076") to its integer form (76)."""
    match = re.fullmatch(r"in(\d+)", idString)
    if not match:
        raise SyntaxError('bad format of IMDb interest id ' + idString)
    return int(match.group(1))

def formatInterestID(idInt):
    """Converts an integer interest id (76) back to its IMDb string form ("in0000076")."""
    return "in" + str(idInt).zfill(7)
