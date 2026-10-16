"""
world.py - data model and file parser for the virtual world.

Member 1: the Location / Exit / World classes, and a parser that builds them
from the Markdown world file using regular expressions.

Member 2: matching picture files to locations (attach_images), and reporting
problems in the data or the pictures instead of crashing.

No Markdown library is used. The line-splitting helpers shared with the items
file live in textparse.py; the patterns specific to the world file are here.
"""

import os
import re
from pathlib import Path

from textparse import read_text, split_blocks, read_fields, one_line


class WorldFileError(Exception):
    """The world file could not be opened, or it contains no usable locations."""


# ---------------------------------------------------------------------------
# Regular expressions specific to the world file and the picture folder
# ---------------------------------------------------------------------------

# "`EAST` → Mossy Path"   ->  group 1 = "EAST", group 2 = "Mossy Path"
# In the supplied file several exits share ONE line:
#     - `EAST` → Mossy Path - `SOUTH` → Sunlit Glade
# so a destination name ends at the next " - " (the bullet separator) or at the end of the line.
# (This assumes no location name contains a spaced hyphen, which is true of the supplied file.)
# The arrow may be the "→" character or the plain-text "->".
EXIT_RE = re.compile(r"`(\w+)`[ \t]*(?:→|->)[ \t]*(.+?)(?=\s+-\s+|$)", re.MULTILINE)

# Whitespace, bullet dashes and asterisks. After the exits we understood are cut out of the
# Exits text, this strips what is left of the bullets so that only genuine junk remains.
NOISE_RE = re.compile(r"[\s\-*\u2022]+")

# "VW01_Forest_Gate.png"   ->  group 1 = "VW01" (the location's code),
#                              group 2 = "Forest_Gate", group 3 = "png"
# A file whose name does not start with a code (such as a contact sheet) does not match at all.
IMAGE_NAME_RE = re.compile(r"^([A-Za-z]+\d+)_(.+)\.(\w+)$")

# Anything that is not a letter or digit. Used to compare "Forest_Gate" with "Forest Gate".
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# The picture types Tkinter can show on its own (no extra libraries), and the first
# bytes of a genuine file of each type.
IMAGE_SIGNATURES = {"png": b"\x89PNG\r\n\x1a\n", "gif": b"GIF8"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class Exit:
    """One way out of a location: a direction and the NAME of the place it leads to."""

    def __init__(self, direction, target_name):
        self.direction = direction.upper()   # "EAST", "UP", ...
        self.target_name = target_name       # "Mossy Path"

    def __repr__(self):
        return f"Exit({self.direction} -> {self.target_name})"


class Location:
    """One place in the world."""

    def __init__(self, name, internal_name="", description="", region=None):
        self.name = name                    # "Forest Gate"
        self.internal_name = internal_name  # "VW01"
        self.description = description
        self.region = region                # "Verdant Woods"

        # A LIST of Exit objects, not a dictionary keyed by direction: five
        # locations in the supplied file have two exits in the same direction
        # (e.g. Hidden Spring has two WEST exits), and a dictionary would
        # silently throw one of them away.
        self.exits = []

        # The objects currently lying in this location (Item objects, see items.py).
        self.items = []

        # Set by attach_images(): the picture file for this location, or None, with a
        # plain-English reason (shown in the window) whenever there is no usable picture.
        self.image_path = None
        self.image_problem = "No picture file was found for this location."

    def __repr__(self):
        return f"Location({self.name!r}, {self.internal_name!r}, {len(self.exits)} exits)"


class World:
    """All the locations and objects, plus any problems noticed while loading them."""

    def __init__(self, title="Virtual World"):
        self.title = title
        self.locations = {}   # normalised name -> Location (a dict remembers insertion order)
        self.by_code = {}     # lower-cased Internal Name ("vw01") -> Location
        self.items = {}       # lower-cased Internal Name ("item01") -> Item (filled by items.load_items)
        self.regions = []     # region names, in file order
        self.warnings = []    # plain-English descriptions of problems found while loading

    @staticmethod
    def key(name):
        """Normalise a name for lookups: ignore capitalisation, extra spaces and curly apostrophes."""
        return " ".join(name.replace("\u2019", "'").split()).casefold()

    def add_location(self, location):
        """Store a location under its normalised name (and under its code, if it has one)."""
        self.locations[self.key(location.name)] = location
        if location.internal_name:
            self.by_code.setdefault(location.internal_name.casefold(), location)   # first one wins

    def find(self, name):
        """Return the Location with this name, or None if there isn't one."""
        return self.locations.get(self.key(name))

    def find_by_code(self, code):
        """Return the Location with this Internal Name (e.g. 'VW01'), or None."""
        return self.by_code.get(code.strip().casefold())

    def find_item(self, code):
        """Return the Item with this Internal Name (e.g. 'ITEM01'), or None."""
        return self.items.get(code.strip().casefold())

    def start_location(self):
        """The player starts at the first location in the file (None if there are none)."""
        return next(iter(self.locations.values()), None)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def load_world(path):
    """Read the world file at `path` and return a World. Raises WorldFileError on failure."""
    path = Path(path)
    try:
        text, problems = read_text(path)
    except OSError as err:
        raise WorldFileError(f"Could not read '{path.name}': {err.strerror or err}") from err

    world = parse_world(text, title=path.stem.replace("_", " "))
    world.warnings = problems + world.warnings      # reading problems come first
    if not world.locations:
        raise WorldFileError(
            f"No locations were found in '{path.name}'. "
            f"Each location should start with a line like '## Forest Gate'."
        )
    return world


def parse_world(text, title="Virtual World"):
    """Turn the text of a world file into a World."""
    world = World(title)

    # Pass 1: split the text into one block of lines per "## Location" heading.
    blocks, world.regions = split_blocks(text)

    # Pass 2: turn each block into a Location.
    for name, region, lines in blocks:
        if world.find(name) is not None:
            world.warnings.append(
                f"The location '{name}' is defined more than once; "
                f"only the first definition is used."
            )
            continue
        location = build_location(name, region, lines, world.warnings)
        if location.internal_name:
            other = world.find_by_code(location.internal_name)
            if other is not None:
                world.warnings.append(
                    f"'{name}' and '{other.name}' both use the code {location.internal_name}, "
                    f"so pictures and objects cannot be matched to them reliably."
                )
        world.add_location(location)

    # Pass 3: every exit must lead to a location that actually exists.
    for location in world.locations.values():
        for exit_ in location.exits:
            if world.find(exit_.target_name) is None:
                world.warnings.append(
                    f"'{location.name}': the {exit_.direction} exit leads to "
                    f"'{exit_.target_name}', which is not defined in the file."
                )
    return world


def build_location(name, region, lines, warnings):
    """Build one Location from the lines that followed its '## Name' heading.

    Anything wrong is added to `warnings` instead of raising an error, so one
    bad location never stops the rest of the world from loading.
    """
    fields = read_fields(lines)

    location = Location(
        name,
        internal_name=one_line(fields.get("internal name", "")),
        description=one_line(fields.get("description", "")),
        region=region,
    )

    # The Exits text keeps its line breaks, so a malformed line can never be
    # glued onto the destination of the exit before it.
    exits_text = fields.get("exits", "")
    for direction, target in EXIT_RE.findall(exits_text):
        location.exits.append(Exit(direction, target.strip()))

    # Report anything missing...
    missing = [
        label
        for label, value in (
            ("Internal Name", location.internal_name),
            ("Description", location.description),
            ("Exits", exits_text),
        )
        if not value
    ]
    if missing:
        warnings.append(f"'{name}' is incomplete - missing: {', '.join(missing)}.")

    # ...and anything in the Exits text that the exit pattern did not recognise.
    # Cut out every exit we understood; whatever is left (minus bullets) is junk.
    leftover = NOISE_RE.sub(" ", EXIT_RE.sub(" ", exits_text)).strip()
    if leftover:
        warnings.append(
            f"'{name}': part of the Exits could not be understood and was skipped: "
            f"'{leftover}'. Expected the form `DIRECTION` → Place Name."
        )
    return location


# ---------------------------------------------------------------------------
# Pictures (Member 2)
# ---------------------------------------------------------------------------

def check_image_file(path, extension):
    """Quick health check of a picture file WITHOUT loading it.

    Returns None if the file looks fine, otherwise a short reason it can't be used.
    """
    signature = IMAGE_SIGNATURES.get(extension.lower())
    if signature is None:
        return f"a .{extension} file cannot be displayed (only .png and .gif can)"
    try:
        with open(path, "rb") as image_file:
            start = image_file.read(len(signature))
    except OSError as err:
        return f"the file could not be read ({err.strerror or err})"
    if not start:
        return "the file is empty"
    if start != signature:
        return f"the file is not a genuine .{extension} picture"
    return None


def attach_images(world, folder):
    """Match picture files to locations by listing the files in `folder`.

    A picture belongs to a location when its file name starts with the location's
    code, e.g. VW01_Forest_Gate.png belongs to the location whose Internal Name is VW01.

    Never raises. Every problem is recorded in world.warnings, and the affected
    location keeps a plain-English `image_problem` that the window shows instead of
    a picture, so the rest of the program carries on working.
    """
    for location in world.locations.values():
        location.image_path = None
        location.image_problem = "No picture file was found for this location."

    # The directory listing: the names of all the files in the folder.
    file_names = None
    if folder is not None:
        try:
            file_names = sorted(os.listdir(folder))
        except OSError:
            pass
    if file_names is None:
        world.warnings.append(f"The picture folder '{folder}' could not be read, so no pictures will be shown.")
        for location in world.locations.values():
            location.image_problem = "The picture folder could not be found."
        return

    # Group the picture files by code: {"vw01": [(file name, name part, extension), ...]}
    pictures = {}
    for file_name in file_names:
        match = IMAGE_NAME_RE.match(file_name)
        if match:
            code, name_part, extension = match.groups()
            pictures.setdefault(code.casefold(), []).append((file_name, name_part, extension))

    # Give each location the first usable picture that carries its code.
    for location in world.locations.values():
        if not location.internal_name:
            location.image_problem = "This location has no code, so its picture cannot be found."
            continue
        candidates = pictures.get(location.internal_name.casefold(), [])
        if not candidates:
            world.warnings.append(f"No picture file was found for '{location.name}' ({location.internal_name}).")
            continue

        reasons = []
        for file_name, name_part, extension in candidates:
            path = Path(folder) / file_name
            reason = check_image_file(path, extension)
            if reason is None:
                location.image_path = path
                location.image_problem = None
                # The code matched, but does the rest of the file name agree?
                if NON_ALNUM_RE.sub("", name_part.casefold()) != NON_ALNUM_RE.sub("", location.name.casefold()):
                    world.warnings.append(
                        f"The picture '{file_name}' is named for a different place than "
                        f"'{location.name}'; it is used for {location.internal_name} anyway."
                    )
                break
            reasons.append(f"{file_name}: {reason}")
        else:
            # The loop ended without finding a usable picture.
            location.image_problem = f"The picture file cannot be used ({reasons[0]})."
            world.warnings.append(f"The picture for '{location.name}' cannot be used - " + "; ".join(reasons) + ".")

    # Picture files whose code matches no location.
    for code, files in pictures.items():
        if code not in world.by_code:
            for file_name, _name_part, _extension in files:
                world.warnings.append(f"The picture '{file_name}' does not match any location, so it is not used.")
