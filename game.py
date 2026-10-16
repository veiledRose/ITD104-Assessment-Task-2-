"""
game.py - the player's progress through the world: where they are, what they
carry, and where they have been.

Member 3 added the inventory and the take/drop rules.
Member 4 added the journey history and restoring a saved state.

The window never changes these lists itself - it asks the Game, which enforces
the rules. That keeps the rules in one place where they can be tested without
opening a window.
"""


class Game:
    """The state of one play-through of a World."""

    def __init__(self, world):
        self.world = world
        self.current = world.start_location()   # the Location the player is standing in
        self.inventory = []                      # the Items the player is carrying

        # Every location the player has entered, in order. Repeat visits are kept (going
        # A -> B -> A gives three entries), and the starting location is the first entry.
        self.journey = [self.current] if self.current is not None else []

    def move_to(self, location):
        """Walk to another location, and record it in the journey."""
        self.current = location
        self.journey.append(location)

    def visited(self):
        """The set of locations that appear anywhere in the journey."""
        return set(self.journey)

    def take(self, item):
        """Move `item` from the current location into the inventory.

        Returns (ok, message). Taking something that is not here changes nothing.
        """
        if item not in self.current.items:
            return False, f"There is no {item.name} here to take."
        self.current.items.remove(item)
        self.inventory.append(item)
        return True, f"You take the {item.name}."

    def drop(self, item):
        """Move `item` from the inventory into the current location.

        Returns (ok, message). Dropping something you are not carrying changes nothing.
        """
        if item not in self.inventory:
            return False, f"You are not carrying the {item.name}."
        self.inventory.remove(item)
        self.current.items.append(item)
        return True, f"You drop the {item.name}."

    def restore(self, state):
        """Put the game into a saved state.

        `state` must come from savegame.read_save(), which has already checked that it is
        complete and consistent - this method just applies it.
        """
        for location in self.world.locations.values():
            location.items = []                       # empty every location...
        for item, location in state.placements:
            location.items.append(item)               # ...then put each object where it was saved
        self.inventory = list(state.inventory)
        self.current = state.current
        self.journey = list(state.journey)
