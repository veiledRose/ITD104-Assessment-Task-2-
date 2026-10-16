"""
items.py - the objects the player can find, inspect, take and drop (Member 3).

The items file uses the same layout as the world file (see textparse.py):

    # Region: Verdant Woods
    ## Weathered Compass
    **Internal Name:** ITEM01
    **Description:** A small brass compass...
    **Initial Location:** VW01          <- the Internal Name of a LOCATION
"""

from textparse import read_text, split_blocks, read_fields, one_line


class Item:
    """One collectible object."""

    def __init__(self, name, internal_name, description, region=None):
        self.name = name                    # "Weathered Compass"
        self.internal_name = internal_name  # "ITEM01"
        self.description = description
        self.region = region                # the region heading it appeared under

    def __repr__(self):
        return f"Item({self.name!r}, {self.internal_name!r})"


def load_items(world, path):
    """Read the items file and put each item into its starting location.

    Never raises. Problems are added to world.warnings and loading carries on,
    so a bad or missing items file never stops the rest of the program.
    """
    # Start from a clean slate, so loading twice can never double up the objects.
    world.items = {}
    for location in world.locations.values():
        location.items = []

    try:
        text, problems = read_text(path)
    except (OSError, TypeError) as err:
        reason = getattr(err, "strerror", None) or err
        world.warnings.append(
            f"The items file could not be read, so there will be no objects in the world ({reason})."
        )
        return
    world.warnings.extend(problems)

    blocks, _regions = split_blocks(text)
    if not blocks:
        world.warnings.append(
            "The items file contains no objects (each should start with a line like '## Silver Acorn')."
        )

    for name, region, lines in blocks:
        fields = read_fields(lines)
        code = one_line(fields.get("internal name", ""))
        description = one_line(fields.get("description", ""))
        start_code = one_line(fields.get("initial location", ""))

        if not code:
            world.warnings.append(f"The object '{name}' has no Internal Name, so its name is used instead.")
            code = name
        if world.find_item(code) is not None:
            world.warnings.append(f"The object code {code} is used more than once; only the first one is kept.")
            continue
        if not description:
            world.warnings.append(f"The object '{name}' has no Description.")

        # Where does it start? The items file names the location by its code (e.g. VW01).
        location = world.find_by_code(start_code) if start_code else None
        if location is None:
            if start_code:
                world.warnings.append(
                    f"The object '{name}' starts in '{start_code}', which is not a location "
                    f"in the world, so it will not appear."
                )
            else:
                world.warnings.append(f"The object '{name}' has no Initial Location, so it will not appear.")
            continue

        item = Item(name, code, description, region)
        location.items.append(item)                    # associate the object with its location
        world.items[code.casefold()] = item
