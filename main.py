"""
main.py - Tkinter front end for the virtual world.

  Member 1: shows the current location (name, description, exits) and lets the
            user walk around by clicking exit buttons.
  Member 2: shows the picture of the current location, and warns about missing
            or unusable data instead of crashing.
  Member 3: shows the objects in the location and the inventory, with
            inspect / take / drop.
  Member 4: records the journey and shows it in its own window; saves the game
            to a text file and loads it back.

Run with:   python main.py
Keep the other .py files, the world file, the items file and the Images folder
in the same folder as this file.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from world import load_world, attach_images, WorldFileError
from items import load_items
from game import Game
from savegame import write_save, read_save

WORLD_FILE = "Whispers_of_the_Forgotten_Realms.md"   # looked for next to this script
FILE_TYPES = [("Markdown files", "*.md"), ("All files", "*.*")]
SAVE_TYPES = [("Saved games", "*.txt"), ("All files", "*.*")]

# The picture area is this many pixels. Bigger pictures are shrunk to fit.
IMAGE_W, IMAGE_H = 400, 300

# The most exits any location has (Hidden Spring has 5). The window is sized for this many buttons.
MOST_EXITS = 5

# Header colours for each region: (background, text). Regions not listed here
# (e.g. in a different world file) use FALLBACK_COLOURS.
REGION_COLOURS = {
    "Verdant Woods": ("#2E6B3F", "#FFFFFF"),
    "Ember Caves": ("#9B2F1F", "#FFFFFF"),
    "Clockwork Citadel": ("#7A5C14", "#FFFFFF"),
    "Shimmering Dunes": ("#E3C48A", "#3B2A0E"),
    "Starfall Ruins": ("#2B2F6B", "#FFFFFF"),
}
FALLBACK_COLOURS = ("#3A3F47", "#FFFFFF")

# Exit buttons are always listed in this order, so they don't jump around
# from one location to the next.
DIRECTION_ORDER = ["NORTH", "EAST", "SOUTH", "WEST", "UP", "DOWN"]


def direction_rank(exit_):
    """Sort key: where the exit's direction sits in DIRECTION_ORDER (unknown directions go last)."""
    if exit_.direction in DIRECTION_ORDER:
        return DIRECTION_ORDER.index(exit_.direction)
    return len(DIRECTION_ORDER)


class WorldExplorer:
    """The main window."""

    def __init__(self, root):
        self.root = root
        self.world = None          # the loaded World
        self.game = None           # the Game: where the player is and what they carry
        self.world_path = None     # the three data sources, so any one can be re-chosen
        self.items_path = None
        self.images_dir = None
        self.base_status = ""      # the status line shown when nothing else needs saying
        self.objects_shown = []    # the Items listed in the "Objects here" box, row by row
        self.inventory_shown = []  # the Items listed in the "Inventory" box, row by row
        self.journey_window = None # the "Your journey" window, while it is open

        # Pictures that have been loaded. Tkinter only shows a PhotoImage while
        # something in our program still refers to it, so this dictionary also
        # keeps the pictures alive (and means each one is only loaded once).
        self.photo_cache = {}

        root.title("Virtual World")

        self.build_menu()
        self.build_widgets()
        self.fix_window_size()

        # Let the empty window appear first, then load the data.
        root.after(100, self.load_initial_world)

    # ------------------------------------------------------------------
    # Building the window
    # ------------------------------------------------------------------

    def build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Open world file...", command=self.choose_world_file)
        file_menu.add_command(label="Choose items file...", command=self.choose_items_file)
        file_menu.add_command(label="Choose picture folder...", command=self.choose_image_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Show warnings...", command=self.show_warnings)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        game_menu = tk.Menu(menubar, tearoff=False)
        game_menu.add_command(label="Save game...", command=self.save_game)
        game_menu.add_command(label="Load game...", command=self.load_game)
        game_menu.add_separator()
        game_menu.add_command(label="View journey...", command=self.show_journey)
        menubar.add_cascade(label="Game", menu=game_menu)
        self.root.config(menu=menubar)

    def build_widgets(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)      # row 1 (the body) takes all spare space

        # Row 0: coloured band showing the region and the location name.
        self.header = tk.Frame(self.root)
        self.header.grid(row=0, column=0, sticky="ew")
        self.region_label = tk.Label(self.header, font=("Georgia", 10), anchor="w")
        self.region_label.pack(fill="x", padx=20, pady=(8, 0))
        self.name_label = tk.Label(self.header, font=("Georgia", 22, "bold"), anchor="w")
        self.name_label.pack(fill="x", padx=20, pady=(0, 8))

        # Row 1: what you SEE on the left, what you can DO on the right.
        body = ttk.Frame(self.root, padding=12)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, minsize=280)     # keeps the right-hand column the same width everywhere
        body.rowconfigure(0, weight=1)

        # --- Left: the picture, with the description underneath ---
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        self.picture = tk.Canvas(
            left, width=IMAGE_W, height=IMAGE_H, bg="#E9E4DA",
            highlightthickness=1, highlightbackground="#C8C8C8",
        )
        self.picture.grid(row=0, column=0)       # no "sticky", so it sits centred

        self.description = tk.Text(
            left, wrap="word", font=("Georgia", 14), width=60, height=5,
            padx=14, pady=10, spacing2=4, relief="flat", bg="#FFFFFF",
            highlightthickness=1, highlightbackground="#C8C8C8",
            cursor="arrow", state="disabled",
        )
        self.description.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

        # --- Right: exits, objects here, inventory ---
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="new")

        exits_box = ttk.LabelFrame(right, text="Exits", padding=8)
        exits_box.pack(fill="x")
        self.exits_frame = ttk.Frame(exits_box)
        self.exits_frame.pack(fill="both", expand=True)

        self.objects_panel, self.objects_list = self.build_item_panel(
            right, "Objects here", 2,
            [("Inspect", self.inspect_here), ("Take", self.take_selected)],
        )
        self.inventory_panel, self.inventory_list = self.build_item_panel(
            right, "Inventory", 4,
            [("Inspect", self.inspect_carried), ("Drop", self.drop_selected)],
        )
        # Double-clicking an object is a shortcut for Inspect.
        self.objects_list.bind("<Double-Button-1>", self.inspect_here)
        self.inventory_list.bind("<Double-Button-1>", self.inspect_carried)

        # Row 2: the status message on the left, and three buttons on the right. The buttons
        # are packed FIRST so that a long message gets clipped instead of pushing them out of view.
        bottom = ttk.Frame(self.root)
        bottom.grid(row=2, column=0, sticky="ew")
        for label, command in (("Load game", self.load_game), ("Save game", self.save_game),
                               ("Journey", self.show_journey)):
            ttk.Button(bottom, text=label, command=command).pack(side="right", padx=(0, 8), pady=4)
        self.status = ttk.Label(bottom, anchor="w", padding=(12, 6))
        self.status.pack(side="left", fill="x", expand=True)

    def fix_window_size(self):
        """Open the window just big enough for everything, then stop it resizing itself.

        The size is measured with the most exit buttons any location has, so it never has
        to change as the player walks around. Measuring (instead of hard-coding a size in
        pixels) keeps everything visible whatever the screen's text scaling is.
        """
        for _ in range(MOST_EXITS):
            ttk.Button(self.exits_frame, text="Go south to Observatory Antechamber").pack(fill="x", pady=1)
        self.root.update_idletasks()            # let Tk work out how big everything wants to be
        width, height = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(width, height)
        for widget in self.exits_frame.winfo_children():
            widget.destroy()

    def build_item_panel(self, parent, title, rows, buttons):
        """A titled box holding a scrolling list of objects and a row of buttons.

        Returns (panel, listbox). `buttons` is a list of (label, command) pairs.
        """
        panel = ttk.LabelFrame(parent, text=title, padding=8)
        panel.pack(fill="x", pady=(10, 0))

        list_area = ttk.Frame(panel)
        list_area.pack(fill="x")
        scrollbar = ttk.Scrollbar(list_area, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        # exportselection=False: otherwise choosing a row in one list would
        # un-choose the row in the other list.
        listbox = tk.Listbox(list_area, height=rows, exportselection=False, activestyle="none")
        listbox.pack(side="left", fill="x", expand=True)
        listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=listbox.yview)

        button_row = ttk.Frame(panel)
        button_row.pack(fill="x", pady=(6, 0))
        for label, command in buttons:
            ttk.Button(button_row, text=label, command=command).pack(
                side="left", fill="x", expand=True, padx=2
            )
        return panel, listbox

    # ------------------------------------------------------------------
    # Drawing the current state
    # ------------------------------------------------------------------

    def refresh(self, highlight=None):
        """Redraw the whole window from the game's current state.

        `highlight` is an object to select in whichever list it now appears in.
        """
        location = self.game.current

        # Header band, coloured by region.
        background, foreground = REGION_COLOURS.get(location.region, FALLBACK_COLOURS)
        self.header.config(bg=background)
        self.region_label.config(text=location.region or "", bg=background, fg=foreground)
        self.name_label.config(text=location.name, bg=background, fg=foreground)

        self.show_picture(location)

        # Description. The text box is read-only (disabled), so unlock it while we change it.
        self.description.config(state="normal")
        self.description.delete("1.0", "end")
        self.description.insert(
            "1.0", location.description or "(No description is available for this location.)"
        )
        self.description.config(state="disabled")

        # Exits: remove the previous location's buttons, then make one button per Exit.
        for widget in self.exits_frame.winfo_children():
            widget.destroy()
        if not location.exits:
            ttk.Label(self.exits_frame, text="There is no way out of here.").pack()
        for exit_ in sorted(location.exits, key=direction_rank):
            self.add_exit_button(exit_)

        # Objects lying here, and objects being carried.
        self.objects_shown = list(location.items)
        self.inventory_shown = list(self.game.inventory)
        self.objects_panel.config(text=f"Objects here ({len(self.objects_shown)})")
        self.inventory_panel.config(text=f"Inventory ({len(self.inventory_shown)})")
        self.fill_list(self.objects_list, self.objects_shown, highlight)
        self.fill_list(self.inventory_list, self.inventory_shown, highlight)

        self.update_journey_view()

    def add_exit_button(self, exit_):
        """Add one button to the Exits panel."""
        destination = self.world.find(exit_.target_name)
        label = f"Go {exit_.direction.lower()} to {exit_.target_name}"

        if destination is None:
            # The file has an exit to a place that doesn't exist: show it, greyed out.
            button = ttk.Button(self.exits_frame, text=label + " (not available)", state="disabled")
        else:
            # "destination=destination" fixes the value for THIS button. Without it,
            # every button made in the loop would end up using the last destination.
            button = ttk.Button(
                self.exits_frame, text=label,
                command=lambda destination=destination: self.go(destination),
            )
        button.pack(fill="x", pady=1)

    def fill_list(self, listbox, items, select=None):
        """Put the names of `items` into a listbox, selecting `select` (or the first row)."""
        listbox.delete(0, "end")
        for item in items:
            listbox.insert("end", item.name)
        if items:
            row = items.index(select) if select in items else 0
            listbox.selection_set(row)
            listbox.see(row)

    # ------------------------------------------------------------------
    # The picture
    # ------------------------------------------------------------------

    def show_picture(self, location):
        """Draw the location's picture, or a message saying why there isn't one."""
        self.picture.delete("all")
        photo = self.get_photo(location)
        middle_x, middle_y = IMAGE_W // 2, IMAGE_H // 2
        if photo is not None:
            self.picture.create_image(middle_x, middle_y, image=photo)
        else:
            self.picture.create_text(
                middle_x, middle_y, text=location.image_problem or "No picture available.",
                width=IMAGE_W - 60, justify="center", fill="#5A5A5A", font=("Georgia", 12),
            )

    def get_photo(self, location):
        """The picture for `location`, shrunk to fit - or None (location.image_problem says why)."""
        path = location.image_path
        if path is None:
            return None
        if path in self.photo_cache:
            return self.photo_cache[path]

        try:
            full = tk.PhotoImage(master=self.root, file=str(path))
        except tk.TclError:
            # The file looked fine in the quick check but Tkinter could not read it.
            location.image_problem = f"The picture file '{path.name}' could not be loaded."
            location.image_path = None           # don't try again every visit
            self.world.warnings.append(f"The picture for '{location.name}' could not be loaded ({path.name}).")
            return None

        # A PhotoImage can only be shrunk by WHOLE-number factors (2 = half size, 3 = a third...),
        # so find the smallest factor that makes it fit the picture area.
        # (a + b - 1) // b divides and rounds up.
        factor = max(1, (full.width() + IMAGE_W - 1) // IMAGE_W, (full.height() + IMAGE_H - 1) // IMAGE_H)
        photo = full.subsample(factor) if factor > 1 else full
        self.photo_cache[path] = photo
        return photo

    # ------------------------------------------------------------------
    # What the player does
    # ------------------------------------------------------------------

    def say(self, text):
        """Show a message in the status line."""
        self.status.config(text=text)

    def go(self, location):
        """Walk to `location`."""
        self.game.move_to(location)
        self.say(self.base_status)
        self.refresh()

    def selected_item(self, listbox, shown):
        """The Item chosen in `listbox`, or None if nothing is chosen."""
        chosen = listbox.curselection()
        return shown[chosen[0]] if chosen else None

    def inspect(self, listbox, shown):
        item = self.selected_item(listbox, shown)
        if item is None:
            self.say("Choose an object in the list first.")
            return
        messagebox.showinfo(item.name, f"{item.name}\n\n{item.description or '(No description is available.)'}")

    # "event=None" lets these be used both as button commands and as double-click handlers.
    def inspect_here(self, event=None):
        self.inspect(self.objects_list, self.objects_shown)

    def inspect_carried(self, event=None):
        self.inspect(self.inventory_list, self.inventory_shown)

    def take_selected(self):
        item = self.selected_item(self.objects_list, self.objects_shown)
        if item is None:
            self.say("There is nothing here to take." if not self.objects_shown else "Choose an object to take first.")
            return
        ok, message = self.game.take(item)
        self.say(message)
        self.refresh(highlight=item if ok else None)

    def drop_selected(self):
        item = self.selected_item(self.inventory_list, self.inventory_shown)
        if item is None:
            self.say("You are not carrying anything." if not self.inventory_shown else "Choose an object to drop first.")
            return
        ok, message = self.game.drop(item)
        self.say(message)
        self.refresh(highlight=item if ok else None)

    # ------------------------------------------------------------------
    # The journey (Member 4)
    # ------------------------------------------------------------------

    def journey_is_open(self):
        return self.journey_window is not None and bool(self.journey_window.winfo_exists())

    def show_journey(self):
        """Game > View journey...  Opens the journey window (or brings it to the front)."""
        if self.game is None:
            return
        if self.journey_is_open():
            self.journey_window.lift()
            self.update_journey_view()
            return

        window = tk.Toplevel(self.root)
        window.title("Your journey")
        window.protocol("WM_DELETE_WINDOW", self.close_journey)
        self.journey_window = window

        self.journey_summary = ttk.Label(window, padding=(12, 10))
        self.journey_summary.pack(fill="x")

        columns = ttk.Frame(window, padding=(12, 0, 12, 12))
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=1)
        columns.columnconfigure(1, weight=2)
        columns.rowconfigure(0, weight=1)
        self.steps_list = self.build_journey_list(columns, "Order of visits", 0, 26)
        self.places_list = self.build_journey_list(columns, "All locations", 1, 46)
        self.update_journey_view()

    def build_journey_list(self, parent, title, column, width):
        """A titled, scrolling list for the journey window. Returns the Listbox."""
        panel = ttk.LabelFrame(parent, text=title, padding=8)
        panel.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column == 0 else 0)
        scrollbar = ttk.Scrollbar(panel, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        listbox = tk.Listbox(panel, height=18, width=width, exportselection=False, activestyle="none")
        listbox.pack(side="left", fill="both", expand=True)
        listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=listbox.yview)
        return listbox

    def close_journey(self):
        if self.journey_window is not None:
            self.journey_window.destroy()
        self.journey_window = None

    def update_journey_view(self):
        """Redraw the journey window, if it is open, from the game's journey history."""
        if self.game is None or not self.journey_is_open():
            return
        journey = self.game.journey

        # How many times has each location been entered, and at which step first?
        visits = {}
        first_step = {}
        for step, location in enumerate(journey, start=1):
            visits[location] = visits.get(location, 0) + 1
            first_step.setdefault(location, step)
        self.journey_summary.config(
            text=f"You have visited {len(visits)} of {len(self.world.locations)} locations "
                 f"in {len(journey)} steps."
        )

        # Left: every step in order, so repeat visits show up again. "You are here" is selected.
        self.steps_list.delete(0, "end")
        for step, location in enumerate(journey, start=1):
            self.steps_list.insert("end", f"{step}.  {location.name}")
        if journey:
            self.steps_list.selection_set(len(journey) - 1)
            self.steps_list.see(len(journey) - 1)

        # Right: every location in the world, grouped by region, marked visited or not.
        self.places_list.delete(0, "end")
        row = 0
        region = object()                  # something that never equals a real region name
        current_row = None
        for location in self.world.locations.values():
            if location.region != region:
                region = location.region
                self.places_list.insert("end", (region or "(no region)").upper())
                self.places_list.itemconfig(row, foreground="#555555")
                row += 1
            if location in visits:
                self.places_list.insert(
                    "end", f"   [x] {location.name}   (visits: {visits[location]}, first: step {first_step[location]})")
                self.places_list.itemconfig(row, foreground="#000000")
            else:
                self.places_list.insert("end", f"   [ ] {location.name}")
                self.places_list.itemconfig(row, foreground="#8A8A8A")
            if location is self.game.current:
                current_row = row
            row += 1
        if current_row is not None:
            self.places_list.selection_set(current_row)
            self.places_list.see(current_row)

    # ------------------------------------------------------------------
    # Saving and loading the game (Member 4)
    # ------------------------------------------------------------------

    def save_game(self):
        """Game > Save game...  Writes the current state to a text file."""
        if self.game is None:
            return
        path = filedialog.asksaveasfilename(
            title="Save game", defaultextension=".txt", initialfile="saved_game.txt", filetypes=SAVE_TYPES)
        if not path:                                    # cancelled
            return
        problem = write_save(self.game, path)
        if problem:
            messagebox.showerror("Could not save the game", problem)
        else:
            self.say(f"Game saved to {Path(path).name}.")

    def load_game(self):
        """Game > Load game...  Restores a saved state - but only if the whole file checks out."""
        if self.game is None:
            return
        path = filedialog.askopenfilename(title="Load a saved game", filetypes=SAVE_TYPES)
        if not path:                                    # cancelled
            return
        state, problems = read_save(self.world, path)
        if problems:
            shown = problems[:10]
            text = "\n\n".join(shown)
            if len(problems) > len(shown):
                text += f"\n\n...and {len(problems) - len(shown)} more."
            messagebox.showerror(
                "Could not load the saved game",
                "The saved game was not loaded, and your current game has not changed.\n\n" + text)
            return
        self.game.restore(state)
        self.say(f"Loaded the saved game {Path(path).name}.")
        self.refresh()          # redraws the location, picture, exits, objects, inventory AND journey

    # ------------------------------------------------------------------
    # Loading the data
    # ------------------------------------------------------------------

    def open_world(self, path):
        """Load a world file, plus the items file and picture folder that sit beside it."""
        path = Path(path)
        self.world_path = path
        self.items_path = path.with_name(path.stem + "_Items.md")   # e.g. Whispers_..._Items.md
        self.images_dir = path.parent / "Images"
        return self.load_everything()

    def load_everything(self):
        """(Re)load the world, its objects and its pictures, and start a fresh game."""
        try:
            world = load_world(self.world_path)
        except WorldFileError as err:
            messagebox.showerror("Could not open world file", str(err))
            return False

        load_items(world, self.items_path)
        attach_images(world, self.images_dir)
        if tk.TkVersion < 8.6:
            world.warnings.append(
                f"This copy of Python uses Tk {tk.TkVersion}, which is too old to show .png pictures "
                f"(Tk 8.6 or newer is needed). Installing Python from python.org fixes this."
            )

        self.world = world
        self.game = Game(world)
        self.photo_cache = {}
        self.root.title(world.title)

        pictures = sum(1 for location in world.locations.values() if location.image_path)
        self.base_status = (f"Loaded {len(world.locations)} locations, {len(world.items)} objects "
                            f"and {pictures} pictures.")
        if world.warnings:
            self.base_status += f" {len(world.warnings)} problem(s) found - see File > Show warnings."
        self.say(self.base_status)
        self.refresh()
        if world.warnings:
            self.show_warnings()
        return True

    def load_initial_world(self):
        """On start-up: open the default world file, or ask the user to choose one."""
        default = Path(__file__).resolve().parent / WORLD_FILE
        if default.is_file():
            if self.open_world(default):
                return
        else:
            messagebox.showinfo(
                "World file not found",
                f"Could not find '{WORLD_FILE}' in the same folder as this program.\n\n"
                f"Choose the world file to open.",
            )
        while self.world is None:            # keep asking until a file loads or the user cancels
            path = filedialog.askopenfilename(title="Open a world file", filetypes=FILE_TYPES)
            if not path:                     # cancelled
                self.root.destroy()
                return
            self.open_world(path)

    def choose_world_file(self):
        """File > Open world file..."""
        path = filedialog.askopenfilename(title="Open a world file", filetypes=FILE_TYPES)
        if path:
            self.open_world(path)

    def choose_items_file(self):
        """File > Choose items file...  (restarts the game with the new objects)"""
        if self.world is None:
            return
        path = filedialog.askopenfilename(title="Choose the items file (this restarts the game)",
                                          filetypes=FILE_TYPES)
        if path:
            self.items_path = Path(path)
            self.load_everything()

    def choose_image_folder(self):
        """File > Choose picture folder...  (restarts the game)"""
        if self.world is None:
            return
        folder = filedialog.askdirectory(title="Choose the folder containing the pictures (this restarts the game)")
        if folder:
            self.images_dir = Path(folder)
            self.load_everything()

    def show_warnings(self):
        """List the problems found while loading the data."""
        if self.world is None:
            return
        if not self.world.warnings:
            messagebox.showinfo("Warnings", "No problems were found in the data.")
            return
        shown = self.world.warnings[:12]
        text = "\n\n".join(shown)
        if len(self.world.warnings) > len(shown):
            text += f"\n\n...and {len(self.world.warnings) - len(shown)} more."
        messagebox.showwarning("Problems found in the data", text)


def main():
    root = tk.Tk()
    WorldExplorer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
