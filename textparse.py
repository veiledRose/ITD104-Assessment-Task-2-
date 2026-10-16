"""
textparse.py - small Markdown-reading helpers shared by the world file and the items file.

Both files are laid out the same way:

    # Region: Verdant Woods            <- a region heading
    ## Forest Gate                      <- one "## Name" block per location (or object)
    **Internal Name:** VW01              <- "**Field:** value" lines inside a block
    **Description:** You stand at...

No Markdown library is used: the text is split into lines and each piece is
recognised with Python's `re` module.
"""

import re
from pathlib import Path

# "# Region: Verdant Woods"   ->  group 1 = "Verdant Woods"
REGION_RE = re.compile(r"^#\s+Region:\s*(.+?)\s*$", re.IGNORECASE)

# "## Forest Gate"   ->  group 1 = "Forest Gate"
# (one "#" is a region heading, so a block heading needs exactly two)
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")

# "**Description:** You stand at..."   ->  group 1 = "Description", group 2 = the text.
# A field's text runs until the next "**Something:**" at the start of a line
# (or the end of the block), so a field is allowed to continue over several lines.
FIELD_RE = re.compile(
    r"^\*\*([^*:]+):\*\*[ \t]*(.*?)(?=^\*\*[^*:]+:\*\*|\Z)",
    re.MULTILINE | re.DOTALL,
)


def read_text(path):
    """Read a text file and return (text, problems). Raises OSError if it cannot be read."""
    path = Path(path)
    problems = []
    try:
        # "utf-8-sig" also copes with the invisible marker some Windows editors put at the start.
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        problems.append(f"'{path.name}' is not valid UTF-8, so some characters may display incorrectly.")
    return text, problems


def split_blocks(text):
    """Split `text` into one block per "## Name" heading.

    Returns (blocks, regions). Each block is [name, region, lines], where `region` is
    the nearest "# Region:" heading above it (or None) and `lines` are the lines under
    its heading. `regions` lists the region names in the order they appear.
    """
    blocks = []
    regions = []
    region = None
    current = None
    for line in text.splitlines():
        region_match = REGION_RE.match(line)
        if region_match:
            region = region_match.group(1)
            if region not in regions:
                regions.append(region)
            current = None   # anything before the next heading belongs to no block
            continue

        heading_match = HEADING_RE.match(line)
        if heading_match:
            current = [heading_match.group(1), region, []]
            blocks.append(current)
        elif current is not None:
            current[2].append(line)
    return blocks, regions


def read_fields(lines):
    """Find every "**Field:** value" in a block's lines.

    Returns a dictionary like {"internal name": "VW01", "description": "..."}.
    Field names are lower-cased so "Internal name" and "Internal Name" both work.
    """
    fields = {}
    for field_name, value in FIELD_RE.findall("\n".join(lines)):
        fields[field_name.strip().casefold()] = value.strip()
    return fields


def one_line(text):
    """Collapse line breaks and repeated spaces into single spaces."""
    return " ".join(text.split())
