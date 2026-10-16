"""
savegame.py - saving and loading the player's progress (Member 4).

A saved game is a plain text file that looks like this:

    Whispers of the Forgotten Realms - saved game
    Format: 1
    Current location: VW05
    Journey: VW01, VW02, VW03, VW05
    Inventory: ITEM01, ITEM04
    Object locations:
    ITEM02: VW05
    ITEM03: VW10

  * Journey is every location entered, in order (repeat visits included), so it also
    records which locations have been visited. It always ends at the current location.
  * Inventory lists the objects being carried.
  * Object locations says where every OTHER object is lying.

So every object appears exactly once, and an object that has been taken or dropped is
simply recorded in its new place.

Loading never trusts the file. read_save() checks everything, reports EVERY problem in
plain English, and returns a state only if the file passed every check - so a damaged
file can never leave the game half-restored.
"""

import re
from pathlib import Path

from textparse import read_text

# "Whispers of the Forgotten Realms - saved game"   ->  group 1 = the world's title
HEADER_RE = re.compile(r"^(.*\S)\s*-\s*saved game\s*$", re.IGNORECASE)

# "Current location: VW05"   ->  group 1 = "Current location", group 2 = "VW05"
# ("Object locations:" matches too, with an empty group 2.)
ENTRY_RE = re.compile(r"^([A-Za-z][A-Za-z ]*?)\s*:\s*(.*)$")

# "ITEM02: VW05"   ->  group 1 = the object's code, group 2 = the location's code
OBJECT_LINE_RE = re.compile(r"^([^\s:]+)\s*:\s*([^\s:]+)$")

# Splits "VW01, VW02 ,VW03" into its codes.
LIST_SPLIT_RE = re.compile(r"\s*,\s*")

# A code we can safely write to a file and read back: letters, digits, "_" and "-".
SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")

FORMAT_VERSION = "1"
KNOWN_ENTRIES = ("format", "current location", "journey", "inventory")


class SaveError(Exception):
    """The game cannot be written to a file."""


class SavedState:
    """A saved game that has been read and fully checked, ready for Game.restore()."""

    def __init__(self, current, journey, inventory, placements):
        self.current = current          # the Location the player was in
        self.journey = journey          # list of Locations, in the order they were entered
        self.inventory = inventory      # list of Items being carried
        self.placements = placements    # list of (Item, Location) for every object NOT being carried


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def location_code(world, location):
    """The code to write for a location. Refuses anything that would not load back correctly."""
    code = location.internal_name
    if not SAFE_CODE_RE.match(code) or world.find_by_code(code) is not location:
        raise SaveError(f"The location '{location.name}' has no unique, usable code, "
                        f"so the game cannot be saved.")
    return code


def item_code(world, item):
    """The code to write for an object."""
    code = item.internal_name
    if not SAFE_CODE_RE.match(code) or world.find_item(code) is not item:
        raise SaveError(f"The object '{item.name}' has no unique, usable code, "
                        f"so the game cannot be saved.")
    return code


def format_save(game):
    """The text of a saved game for the game's current state."""
    world = game.world
    lines = [
        f"{world.title} - saved game",
        f"Format: {FORMAT_VERSION}",
        f"Current location: {location_code(world, game.current)}",
        "Journey: " + ", ".join(location_code(world, place) for place in game.journey),
        "Inventory: " + ", ".join(item_code(world, item) for item in game.inventory),
        "Object locations:",
    ]
    # Going through the locations in world order, and each location's objects in the order
    # they lie there, means loading puts everything back in exactly the same order.
    for location in world.locations.values():
        for item in location.items:
            lines.append(f"{item_code(world, item)}: {location_code(world, location)}")
    return "\n".join(lines) + "\n"


def write_save(game, path):
    """Save the game to `path`. Returns None if it worked, otherwise a message saying why not."""
    try:
        text = format_save(game)
        Path(path).write_text(text, encoding="utf-8")
    except SaveError as err:
        return str(err)
    except OSError as err:
        return f"The file could not be written ({err.strerror or err})."
    return None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def split_codes(text):
    """'VW01, VW02' -> ['VW01', 'VW02']  (stray empty entries, such as a trailing comma, are ignored)."""
    return [code for code in LIST_SPLIT_RE.split(text.strip()) if code]


def name_list(names, limit=6):
    """'A, B, C' - or 'A, B, C, D, E, F and 4 more' if there are a lot."""
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f" and {len(names) - limit} more"


def describe_bad_lines(bad_lines, hint=""):
    """Turn (line number, text) pairs into problem sentences.

    A few bad lines are listed one by one; a long run of them becomes ONE sentence, so
    it cannot bury the problems that matter.
    """
    if len(bad_lines) <= 3:
        return [f"Line {number} is not understood: '{text}'{hint}." for number, text in bad_lines]
    number, text = bad_lines[0]
    return [f"{len(bad_lines)} lines are not understood; the first is line {number}: '{text}'{hint}."]


def read_save(world, path):
    """Read and check a saved game. Never raises, and never changes the game.

    Returns (state, problems). `problems` is a list of plain-English sentences, most
    important first; if it is empty, `state` is a SavedState that can be given to
    Game.restore(). Otherwise `state` is None.
    """
    try:
        text, notes = read_text(path)
    except (OSError, TypeError) as err:
        return None, [f"The file could not be read ({getattr(err, 'strerror', None) or err})."]

    # Number the non-blank lines so problems can say where they are.
    lines = [(number, line.strip())
             for number, line in enumerate(text.splitlines(), start=1) if line.strip()]
    if not lines:
        return None, notes + ["The file is empty."]
    if not HEADER_RE.match(lines[0][1]):
        return None, notes + ["This does not look like a saved game "
                              "(its first line should end with '- saved game')."]

    # Sort the remaining lines into "Name: value" entries and the object lines at the end.
    entries = {}            # lower-case entry name -> value text
    odd_lines = []          # (line number, text) of lines that are not "Name: value" at all
    entry_problems = []     # problems with individual entries
    object_lines = []       # (line number, text) for everything after "Object locations:"
    seen_object_section = False
    for number, line in lines[1:]:
        if seen_object_section:
            object_lines.append((number, line))
            continue
        match = ENTRY_RE.match(line)
        if not match:
            odd_lines.append((number, line))
            continue
        name, value = match.group(1).casefold(), match.group(2).strip()
        if name == "object locations":
            seen_object_section = True
            if value:
                entry_problems.append(f"Line {number}: 'Object locations:' should be on a line of its own.")
        elif name not in KNOWN_ENTRIES:
            entry_problems.append(f"Line {number}: '{match.group(1)}' is not a recognised entry.")
        elif name in entries:
            entry_problems.append(f"Line {number}: '{match.group(1)}' appears more than once.")
        else:
            entries[name] = value

    # --- Is anything missing? (reported first: it is usually the root cause) ---
    structure_problems = []
    missing = [label for label in ("Format", "Current location", "Journey", "Inventory")
               if label.casefold() not in entries]
    if not seen_object_section:
        missing.append("Object locations")
    if missing:
        structure_problems.append("The saved game is incomplete - missing: " + ", ".join(missing) + ".")
    if "format" in entries and entries["format"] != FORMAT_VERSION:
        structure_problems.append(f"The saved game uses format '{entries['format']}', "
                                  f"but this program reads format {FORMAT_VERSION}.")

    # --- Current location, journey, inventory ---
    content_problems = []
    current = None
    if "current location" in entries:
        current = world.find_by_code(entries["current location"])
        if current is None:
            content_problems.append(f"The current location '{entries['current location']}' "
                                    f"is not a location in this world.")

    journey = []
    journey_ok = False
    if "journey" in entries:
        codes = split_codes(entries["journey"])
        unknown = [code for code in codes if world.find_by_code(code) is None]
        if not codes:
            content_problems.append("The journey is empty (it should at least contain the starting location).")
        elif unknown:
            content_problems.append(f"The journey mentions places that are not in this world: {name_list(unknown)}.")
        else:
            journey = [world.find_by_code(code) for code in codes]
            journey_ok = True
    if journey_ok and current is not None and journey[-1] is not current:
        content_problems.append("The journey should end at the current location.")

    inventory = []
    if "inventory" in entries:
        for code in split_codes(entries["inventory"]):
            item = world.find_item(code)
            if item is None:
                content_problems.append(f"The inventory mentions '{code}', which is not an object in this world.")
            elif item in inventory:
                content_problems.append(f"The inventory lists {item.name} more than once.")
            else:
                inventory.append(item)

    # --- Where every other object is lying ---
    object_problems = []
    bad_object_lines = []
    placements = []
    accounted_for = list(inventory)
    for number, line in object_lines:
        match = OBJECT_LINE_RE.match(line)
        if not match:
            bad_object_lines.append((number, line))
            continue
        item = world.find_item(match.group(1))
        location = world.find_by_code(match.group(2))
        if item is None:
            object_problems.append(f"Line {number}: '{match.group(1)}' is not an object in this world.")
        elif location is None:
            object_problems.append(f"Line {number}: '{match.group(2)}' is not a location in this world.")
        elif item in accounted_for:
            object_problems.append(f"Line {number}: {item.name} is recorded more than once.")
        else:
            accounted_for.append(item)
            placements.append((item, location))

    # Every object in the world must be somewhere.
    if seen_object_section:
        lost = [item.name for item in world.items.values() if item not in accounted_for]
        if lost:
            object_problems.append(f"The saved game does not say where these objects are: {name_list(lost)}.")

    problems = (notes + structure_problems + describe_bad_lines(odd_lines) + entry_problems
                + content_problems
                + describe_bad_lines(bad_object_lines, " (expected something like 'ITEM01: VW01')")
                + object_problems)
    if problems:
        return None, problems
    return SavedState(current, journey, inventory, placements), []
