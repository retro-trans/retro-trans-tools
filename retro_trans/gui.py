"""Compact native tabs; stale background results cannot change a newer selection."""
import json
import os
from datetime import datetime
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk

from . import __version__
from .core import Cancelled, GitHubClient, PatchError, cache_directory, manual_patch
from .catalog import (APP_REPO, application_root, apply_plan, atomic_json, load_catalog,
                      recognize, refresh_catalog, scan_root)
from .updater import stage_update, update_status
from . import z3_saves, mx_converter, vita_repatch
from .chd import (ChdSource, is_chd, inspect_chd, extraction_folder, unpack_to_folder, unpacked_layout)
from .ps3 import INSTALLATION_WARNING, MANUAL_REMINDER, is_ps3_platform, looks_like_ps3
from .solutions import SolutionSource, SolutionPlan

TEXT, MUTED, ACCENT, ERROR = "#202020", "#606060", "#166534", "#a4262c"


class Application(tk.Tk):
    def __init__(self, startup=True, visible=True):
        super().__init__()
        if not visible:
            self.withdraw()
        self.title("Retro Trans " + __version__)
        self.geometry("700x440")
        self.client, self.catalog = GitHubClient(), load_catalog()
        self.pending_catalog = None
        self.events, self.threads = queue.Queue(), []
        self.cancel, self.background_cancel = threading.Event(), threading.Event()
        self.job_id, self.job_kind = 0, ""
        self.busy, self.closing, self.refresh_running = False, False, False
        self.selection, self.plan, self.saved_output = None, None, None
        self.plan_problem = ''
        self.extracted_inputs, self.declined_chds = set(), set()
        self.found, self.controls, self.readonly_controls, self.selection_buttons = [], [], [], []
        self.status = tk.StringVar(value="Ready.")
        self.detail = tk.StringVar(value="Select a binary, apply a local patch, or convert saves.")
        self.catalog_status = tk.StringVar(value="Catalog: {} patches".format(len(self.catalog.edges)))
        self.app_update_status = update_status()
        self.detected = tk.StringVar(value="No binary selected")
        self.file_label, self.output = tk.StringVar(), tk.StringVar()
        self.target = tk.StringVar(value="Latest")
        self.output_format = tk.StringVar(value='Original format')
        self.manual_format = tk.StringVar(value='Original format')
        self.unpack_chd = tk.BooleanVar(value=True)
        self.route = tk.StringVar(value="Select a recognized binary to see its patch route.")
        self.apply_source, self.apply_delta, self.apply_output = (tk.StringVar() for _ in range(3))
        self.save_ps3, self.save_vita = tk.StringVar(), tk.StringVar()
        self.save_output = tk.StringVar(value=str(self.next_save_output(Path.home() / 'Documents' / 'Retro Trans')))
        self.save_directions = {'PS3 → Vita': 'rpcs3-to-vita3k', 'Vita → PS3': 'vita3k-to-rpcs3', 'Both directions': 'both'}
        self.save_direction = tk.StringVar(value='PS3 → Vita')
        self.save_closed = tk.BooleanVar(value=False)
        self.save_summary = tk.StringVar(value='Jigoku-hen • Decrypted RPCS3 / Vita3K saves')
        self.save_checked = None
        self.settings_path = cache_directory().parent / "settings.json"
        try:
            self.settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if not isinstance(self.settings, dict):
                self.settings = {}
        except (ValueError, OSError):
            self.settings = {}
        self.save_game = tk.StringVar(value='Z3 Jigoku-hen')
        self.previous_save_game = self.save_game.get()
        self.save_paths = {}
        self.mx_slot = tk.StringVar(value='')
        self.mx_boot = tk.StringVar(value=self.settings.get('mx_game_file', ''))
        self.mx_ppsspp = tk.StringVar(value=self.settings.get('mx_ppsspp',
            str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'PPSSPP' / 'PPSSPPWindows64.exe')))
        self.mx_psp_difficulty = tk.BooleanVar(value=True)
        self.mx_ps2_output_difficulty = True
        self.mx_source_difficulty = None
        self.mx_syncing_difficulty = False
        self.mx_difficulty_note = tk.StringVar()
        self.mx_difficulty_caption = tk.StringVar(value='PSP difficulty on PS2')
        self.mx_difficulty_checkbox = None
        self.vita_source, self.vita_output = tk.StringVar(), tk.StringVar()
        self.vita_license = tk.StringVar()
        sidecar = application_root() / vita_repatch.MANIFEST
        self.vita_description = tk.StringVar(value=str(sidecar) if sidecar.is_file() else '')
        self.mx_experimental = tk.BooleanVar(value=False)
        self.build_styles()
        self.build_layout()
        for variable in (self.save_ps3, self.save_vita, self.save_output, self.save_direction, self.save_closed,
                         self.mx_slot, self.mx_boot, self.mx_ppsspp, self.mx_experimental):
            variable.trace_add('write', self.invalidate_saves)
        self.mx_psp_difficulty.trace_add('write', self.change_mx_difficulty)
        self.save_game.trace_add('write', self.change_save_game)
        for variable in (self.vita_source, self.vita_output, self.vita_license):
            variable.trace_add('write', lambda *args: self.update_action())
        self.update_idletasks()
        scale = self.winfo_fpixels("1i") / 96
        width, height = max(round(700 * scale), self.winfo_reqwidth()), max(round(440 * scale), self.winfo_reqheight())
        self.minsize(max(round(650 * scale), self.winfo_reqwidth()), height)
        self.geometry("{}x{}".format(width, height))
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.after(80, self.poll)
        if startup:
            self.after(100, self.scan)
            self.after(150, self.refresh)

    def build_styles(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            font.nametofont(name).configure(family="Segoe UI", size=9)
        self.option_add("*Font", "TkDefaultFont")
        self.configure(bg=style.lookup("TFrame", "background"))
        style.configure("TButton", padding=(8, 3))
        style.configure("TEntry", padding=3)
        style.configure("TCombobox", padding=3)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Status.TLabel", font=("Segoe UI", 9, "bold"))

    def button(self, parent, text, command, **kw):
        control = ttk.Button(parent, text=text, command=command, **kw)
        self.controls.append(control)
        return control

    def build_layout(self):
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(toolbar, textvariable=self.catalog_status, style="Muted.TLabel").pack(side="left")
        ttk.Button(toolbar, text="About / Updates", command=self.about).pack(side="right")
        self.refresh_button = ttk.Button(toolbar, text="Refresh catalog", command=self.refresh)
        self.refresh_button.pack(side="right", padx=6)
        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="x")
        self.tabs = []
        for title in ("Automatic", "Apply xdelta", "Save conversion", "Vita rePatch"):
            page = ttk.Frame(self.notebook, padding=10)
            page.columnconfigure(1, weight=1)
            self.notebook.add(page, text=title)
            self.tabs.append(page)
        auto = self.tabs[0]
        ttk.Label(auto, text="Input:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.file_box = ttk.Combobox(auto, textvariable=self.file_label, state="readonly", width=1)
        self.file_box.grid(row=0, column=1, sticky="ew")
        self.controls.append(self.file_box)
        self.readonly_controls.append(self.file_box)
        self.file_box.bind("<<ComboboxSelected>>", self.select_found)
        actions = ttk.Frame(auto)
        actions.grid(row=0, column=2, padx=(8, 0))
        browse = self.button(actions, "Browse…", self.choose_source)
        browse.pack(side="left")
        folder = self.button(actions, "Folder…", self.choose_folder)
        folder.pack(side="left", padx=(4, 0))
        scan = self.button(actions, "Scan", self.scan)
        scan.pack(side="left", padx=(4, 0))
        self.selection_buttons.extend([browse, folder, scan])
        ttk.Label(auto, text="Detected:").grid(row=1, column=0, sticky="w", pady=5)
        self.detected_label = ttk.Label(auto, textvariable=self.detected, style="Muted.TLabel")
        self.detected_label.grid(row=1, column=1, columnspan=2, sticky="ew", pady=5)
        ttk.Label(auto, text="Target:").grid(row=2, column=0, sticky="w")
        self.target_box = ttk.Combobox(auto, textvariable=self.target, values=["Latest", "Next version only"], state="readonly", width=1)
        self.target_box.grid(row=2, column=1, sticky="ew")
        self.controls.append(self.target_box)
        self.readonly_controls.append(self.target_box)
        self.target_box.bind("<<ComboboxSelected>>", lambda event: self.plan_selection())
        self.button(auto, "Route details", self.route_details).grid(row=2, column=2, sticky="ew", padx=(8, 0))
        self.route_label = ttk.Label(auto, textvariable=self.route, style="Muted.TLabel")
        self.route_label.grid(row=3, column=0, columnspan=3, sticky="ew", pady=5)
        self.auto_output_label, self.auto_output_button = self.path_row(auto, 4, "Patched copy:", self.output, save=True)
        self.output_format_box = self.format_row(auto, 5, self.output_format, lambda: self.change_output_format())
        self.path_row(self.tabs[1], 0, "Original file:", self.apply_source)
        self.path_row(self.tabs[1], 1, "Patch file:", self.apply_delta, extension=".xdelta")
        self.path_row(self.tabs[1], 2, "Patched copy:", self.apply_output, save=True)
        self.manual_format_box = self.format_row(self.tabs[1], 3, self.manual_format, lambda: self.change_output_format(manual=True))
        unpack = ttk.Checkbutton(self.tabs[1], text='Unpack CHD input before patching', variable=self.unpack_chd,
                                 command=self.manual_chd_mode)
        unpack.grid(row=4, column=0, columnspan=3, sticky='w', pady=3)
        self.controls.append(unpack)
        ttk.Label(self.tabs[1], text="Local xdelta checks; no catalog match required.\n" + MANUAL_REMINDER,
                  style="Muted.TLabel").grid(row=5, column=0, columnspan=3, sticky="w", pady=3)
        saves = self.tabs[2]
        ttk.Label(saves, text='Convert:').grid(row=0, column=0, sticky='w')
        choices = ttk.Frame(saves)
        choices.grid(row=0, column=1, sticky='ew')
        choices.columnconfigure((0, 1), weight=1)
        game = ttk.Combobox(choices, textvariable=self.save_game,
                           values=['Z3 Jigoku-hen', 'MX (experimental)'], state='readonly', width=1)
        game.grid(row=0, column=0, sticky='ew', padx=(0, 6))
        self.controls.append(game)
        self.readonly_controls.append(game)
        direction = ttk.Combobox(choices, textvariable=self.save_direction,
                                values=list(self.save_directions), state='readonly', width=1)
        direction.grid(row=0, column=1, sticky='ew')
        self.save_direction_box = direction
        self.controls.append(direction)
        self.readonly_controls.append(direction)
        self.button(saves, 'Instructions', self.save_help).grid(row=0, column=2, sticky='ew', padx=(8, 0))
        self.save_first_label = self.save_folder_row(saves, 1, 'RPCS3 saves:', self.save_ps3)
        self.save_second_label = self.save_folder_row(saves, 2, 'Vita3K saves:', self.save_vita)
        self.save_folder_row(saves, 3, 'New output:', self.save_output, output=True)
        closed = ttk.Checkbutton(saves, text='Both emulators are closed.', variable=self.save_closed)
        closed.grid(row=4, column=0, columnspan=2, sticky='w', pady=3)
        self.controls.append(closed)
        self.mx_options_button = self.button(saves, 'MX options…', self.mx_options)
        self.mx_options_button.grid(row=4, column=2, sticky='ew', padx=(8, 0), pady=3)
        self.mx_options_button.grid_remove()
        ttk.Label(saves, textvariable=self.save_summary, style='Muted.TLabel').grid(
            row=5, column=0, columnspan=3, sticky='w', pady=(3, 0))
        vita = self.tabs[3]
        ttk.Label(vita, text='SRW Z3 Jigoku-hen • Physical Vita • PCSG00264 v01.00').grid(
            row=0, column=0, columnspan=3, sticky='w', pady=(0, 6))
        self.path_row(vita, 1, 'Original PKG:', self.vita_source, extension='.pkg')
        self.path_row(vita, 2, 'Matching work.bin:', self.vita_license, extension='.bin')
        for row, title, variable, is_output in (
                (3, 'New output:', self.vita_output, True),):
            ttk.Label(vita, text=title).grid(row=row, column=0, sticky='w', padx=(0, 8))
            entry = ttk.Entry(vita, textvariable=variable, width=1)
            entry.grid(row=row, column=1, sticky='ew', pady=3)
            self.controls.append(entry)
            self.button(vita, 'Browse…', lambda v=variable, out=is_output: self.pick_vita_folder(v, out)).grid(
                row=row, column=2, sticky='ew', padx=(8, 0))
        self.path_row(vita, 4, 'Local patch (optional):', self.vita_description, extension='.json')
        ttk.Label(vita, text='Downloads the official Vita3K tool; needs 6 GB temporary space.\n'
                  'Your license stays local. Originals, emulator setup and saves stay untouched.',
                  style='Muted.TLabel').grid(row=5, column=0, columnspan=3, sticky='w', pady=5)
        self.button(vita, 'Instructions', lambda: messagebox.showinfo('Physical Vita rePatch',
                    vita_repatch.GUIDE, parent=self)).grid(row=6, column=2, sticky='ew')
        self.notebook.bind("<<NotebookTabChanged>>", lambda event: self.update_action())
        self.status_label = ttk.Label(outer, textvariable=self.status, style="Status.TLabel")
        self.status_label.pack(fill="x", pady=(10, 5))
        self.progress = ttk.Progressbar(outer, maximum=100)
        self.progress.pack(fill="x")
        details = ttk.Frame(outer)
        details.pack(fill="both", expand=True, pady=6)
        self.detail_text = tk.Text(details, height=3, width=1, wrap="word", font="TkTextFont",
            background=self.cget("bg"), foreground=MUTED, relief="flat", borderwidth=0,
            highlightthickness=0, state="disabled")
        self.detail_text.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(details, command=self.detail_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.detail_text.configure(yscrollcommand=scrollbar.set)
        self.detail.trace_add("write", self.update_detail)
        self.update_detail()
        actions = ttk.Frame(outer)
        actions.pack(fill="x")
        self.folder_button = ttk.Button(actions, text="Open output folder", command=self.open_folder, state="disabled")
        self.folder_button.pack(side="left")
        self.apply_button = self.button(actions, "Patch", self.apply, default="active", state="disabled")
        self.apply_button.pack(side="right")
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.cancel_work, state="disabled")
        self.cancel_button.pack(side="right", padx=6)
        outer.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(200, event.width - 20)))
        auto.bind("<Configure>", lambda event: (self.route_label.configure(wraplength=max(200, event.width - 20)),
            self.detected_label.configure(wraplength=max(200, event.width - 110))))
        self.bind("<Return>", lambda event: self.apply())
        self.bind("<Escape>", lambda event: self.cancel_work() if self.busy else None)

    def path_row(self, page, row, title, variable, save=False, extension=""):
        label = ttk.Label(page, text=title)
        label.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        entry = ttk.Entry(page, textvariable=variable, width=1)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        self.controls.append(entry)
        button = self.button(page, "Save as…" if save else "Browse…", lambda: self.pick_path(variable, save, extension))
        button.grid(row=row, column=2, sticky="ew", padx=(8, 0), pady=3)
        return label, button

    def format_row(self, page, row, variable, command):
        ttk.Label(page, text='Output format:').grid(row=row, column=0, sticky='w', pady=3)
        box = ttk.Combobox(page, textvariable=variable, values=['Original format', 'CHD'], state='readonly', width=1)
        box.grid(row=row, column=1, sticky='ew', pady=3)
        box.bind('<<ComboboxSelected>>', lambda event: command())
        self.controls.append(box)
        self.readonly_controls.append(box)
        return box

    def manual_chd_mode(self):
        if not self.unpack_chd.get():
            self.manual_format.set('Original format')
        self.manual_format_box.configure(values=['Original format', 'CHD'] if self.unpack_chd.get() else ['Original format'])
        self.change_output_format(manual=True)

    def change_output_format(self, manual=False):
        if not manual and isinstance(self.plan, SolutionPlan):
            self.output_format.set('Original format')
            return
        variable = self.apply_output if manual else self.output
        mode = self.manual_format if manual else self.output_format
        if manual:
            source = Path(self.apply_source.get())
            extension = source.suffix or '.bin'
            try:
                if self.unpack_chd.get() and source.is_file() and is_chd(source):
                    disc = inspect_chd(source)
                    extension = '.iso' if disc.sector_size == 2048 else '.bin'
            except (OSError, PatchError):
                extension = '.iso'
        else:
            extension = '.' + self.plan.target.format if self.plan else '.iso'
        if variable.get():
            variable.set(str(Path(variable.get()).with_suffix('.chd' if mode.get() == 'CHD' else extension)))

    def pick_path(self, variable, save=False, extension=""):
        if save and variable is self.output and isinstance(self.plan, SolutionPlan):
            parent = filedialog.askdirectory(title='Choose where to create the patched folder', mustexist=True)
            if parent:
                variable.set(str(Path(parent) / Path(variable.get()).name))
            return parent
        options = {"initialdir": self.settings.get("last_browse_folder", str(application_root())),
                   "filetypes": [("All files", "*.*")]}
        if extension:
            options["filetypes"].insert(0, ("xdelta patches", "*.xdelta *.vcdiff"))
        if save:
            path = filedialog.asksaveasfilename(confirmoverwrite=False, defaultextension=extension,
                initialfile=Path(variable.get()).name if variable.get() else "", **options)
        else:
            path = filedialog.askopenfilename(**options)
        if path:
            variable.set(path)
            if variable is self.apply_source:
                chd = is_chd(path)
                self.manual_format.set('CHD' if chd and self.unpack_chd.get() else 'Original format')
                self.apply_output.set(str(Path(path).with_name(Path(path).stem + '-patched' + Path(path).suffix)))
                self.change_output_format(manual=True)
            elif save and variable in (self.output, self.apply_output):
                self.change_output_format(manual=variable is self.apply_output)
            self.settings["last_browse_folder"] = str(Path(path).parent)
            try:
                atomic_json(self.settings_path, self.settings)
            except OSError:
                pass
            if variable is self.apply_source and chd and self.unpack_chd.get():
                self.prepare_chd(path, manual=True)
        return path

    @staticmethod
    def next_save_output(parent):
        stem = 'Converted-saves-' + datetime.now().strftime('%Y%m%d-%H%M%S')
        path, suffix = parent / stem, 1
        while path.exists():
            path = parent / (stem + '-' + str(suffix))
            suffix += 1
        return path

    def save_folder_row(self, page, row, title, variable, output=False):
        label = ttk.Label(page, text=title)
        label.grid(row=row, column=0, sticky='w', padx=(0, 8), pady=3)
        entry = ttk.Entry(page, textvariable=variable, width=1)
        entry.grid(row=row, column=1, sticky='ew', pady=3)
        self.controls.append(entry)
        self.button(page, 'Browse…', lambda: self.pick_save_folder(variable, output)).grid(
            row=row, column=2, sticky='ew', padx=(8, 0), pady=3)
        return label

    def pick_save_folder(self, variable, output=False):
        if self.save_game.get().startswith('MX') and not output:
            if variable is self.save_ps3:
                menu = tk.Menu(self, tearoff=False)
                def choose_file():
                    path = filedialog.askopenfilename(title='Choose the PS2 card or exported PSU',
                        filetypes=[('PS2 saves', '*.ps2 *.psu'), ('All files', '*.*')])
                    if path:
                        variable.set(path)
                def choose_folder():
                    path = filedialog.askdirectory(title='Choose an extracted BISLPS-25345Sxx manual save', mustexist=True)
                    if path:
                        variable.set(path)
                menu.add_command(label='Memory card or PSU file…', command=choose_file)
                menu.add_command(label='Extracted save folder…', command=choose_folder)
                menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
                return
            path = filedialog.askdirectory(title='Choose the PPSSPP MX manual slot (ULJS00041xxxx)', mustexist=True)
            if path:
                variable.set(path)
            return
        path = filedialog.askdirectory(title='Choose where to create a new output folder' if output else
            ('Choose RPCS3 savedata (contains NPJB00520 folders)' if variable is self.save_ps3 else
             'Choose Vita3K PCSG00264 save folder'), mustexist=True)
        if path:
            variable.set(str(self.next_save_output(Path(path))) if output else path)

    def invalidate_saves(self, *args):
        self.save_checked = None
        self.mx_source_difficulty = None
        self.refresh_mx_difficulty()
        self.save_summary.set('Experimental • Early Hugo intermission only • Review MX options.' if
                              self.save_game.get().startswith('MX') else 'Both save folders need system data and a manual save.')
        self.update_action()

    def change_mx_difficulty(self, *args):
        if self.mx_syncing_difficulty:
            return
        self.mx_ps2_output_difficulty = self.mx_psp_difficulty.get()
        self.invalidate_saves()

    def refresh_mx_difficulty(self):
        source = self.save_direction.get() == 'PS2 → PSP'
        self.mx_syncing_difficulty = True
        try:
            self.mx_psp_difficulty.set(self.mx_source_difficulty == 'psp' if source else self.mx_ps2_output_difficulty)
        finally:
            self.mx_syncing_difficulty = False
        self.mx_difficulty_caption.set('PSP difficulty on PS2' + (' (source save)' if source else ''))
        if source:
            self.mx_difficulty_note.set({
                None: 'Check saves will detect the PS2 source difficulty. PSP output always uses PSP difficulty.',
                'original': 'Detected PS2 Original. Converting to PSP changes the difficulty to PSP.',
                'psp': 'Detected PSP difficulty in the PS2 save. No difficulty change is needed.'
            }[self.mx_source_difficulty])
        else:
            self.mx_difficulty_note.set('Checked: PSP difficulty. Unticked: PS2 Original.\n'
                'The PSP source always uses PSP difficulty; untick to change the PS2 output.' +
                (' PSP output always uses PSP difficulty.' if self.save_direction.get() == 'Both directions' else ''))
        box = self.mx_difficulty_checkbox
        if box is not None and box.winfo_exists():
            box.configure(state='disabled' if source else 'normal')
            box.state(['alternate' if source and self.mx_source_difficulty is None else '!alternate'])

    def change_save_game(self, *args):
        self.save_paths[self.previous_save_game] = (self.save_ps3.get(), self.save_vita.get())
        selected = self.save_game.get()
        self.previous_save_game = selected
        first, second = self.save_paths.get(selected, ('', ''))
        self.save_ps3.set(first)
        self.save_vita.set(second)
        self.save_closed.set(False)
        mx = selected.startswith('MX')
        self.save_directions = ({'PS2 → PSP': 'ps2-to-psp', 'PSP → PS2': 'psp-to-ps2', 'Both directions': 'both'} if mx else
            {'PS3 → Vita': 'rpcs3-to-vita3k', 'Vita → PS3': 'vita3k-to-rpcs3', 'Both directions': 'both'})
        self.save_direction_box.configure(values=list(self.save_directions))
        self.save_direction.set(next(iter(self.save_directions)))
        self.save_first_label.configure(text='PS2 save/card:' if mx else 'RPCS3 saves:')
        self.save_second_label.configure(text='PSP manual save:' if mx else 'Vita3K saves:')
        self.mx_options_button.grid() if mx else self.mx_options_button.grid_remove()
        self.invalidate_saves()

    def mx_options(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self)
        dialog.title('MX conversion — experimental profile')
        dialog.transient(self)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill='both', expand=True)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text='PS2 English port 0.1.18 ↔ MX Portable 0.4.9\n'
                  'Early Hugo / Cerberus intermission only; use a separate test card/profile.',
                  wraplength=550).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 10))
        self.mx_difficulty_checkbox = ttk.Checkbutton(body, textvariable=self.mx_difficulty_caption,
                                                     variable=self.mx_psp_difficulty)
        self.mx_difficulty_checkbox.grid(row=1, column=0, columnspan=3, sticky='w')
        ttk.Label(body, textvariable=self.mx_difficulty_note, wraplength=550).grid(
            row=2, column=0, columnspan=3, sticky='w', pady=(4, 8))
        self.refresh_mx_difficulty()
        advanced = ttk.Frame(body)
        advanced.columnconfigure(1, weight=1)
        advanced.grid(row=4, column=0, columnspan=3, sticky='ew')
        advanced.grid_remove()
        def toggle_files():
            expanded = bool(advanced.grid_info())
            advanced.grid_remove() if expanded else advanced.grid()
            files_button.configure(text=('Show' if expanded else 'Hide') + ' game files and slot…')
        files_button = ttk.Button(body, text='Show game files and slot…', command=toggle_files)
        files_button.grid(row=3, column=0, columnspan=3, sticky='w', pady=4)
        for row, label, variable in ((1, 'PS2 slot directory:', self.mx_slot),
                                    (2, 'PSP ISO / BOOT.BIN:', self.mx_boot),
                                    (3, 'PPSSPP 1.20.4 EXE:', self.mx_ppsspp)):
            ttk.Label(advanced, text=label).grid(row=row, column=0, sticky='w', padx=(0, 8), pady=4)
            widget = ttk.Entry(advanced, textvariable=variable, width=38)
            widget.grid(row=row, column=1, sticky='ew', pady=4)
            if row in (2, 3):
                def browse(var=variable):
                    path = filedialog.askopenfilename(parent=dialog, filetypes=[('All files', '*.*')])
                    if path:
                        var.set(path)
                ttk.Button(advanced, text='Browse…', command=browse).grid(row=row, column=2, padx=(8, 0))
        ttk.Label(advanced, text='Slot example: BISLPS-25345S01. Leave blank when there is only one manual save.\n'
                  'Game files are needed for encrypted PSP saves and PSP music defaults.',
                  wraplength=550).grid(row=4, column=0, columnspan=3, sticky='w', pady=6)
        ttk.Label(body, text='All favorite-series choices and existing funds are kept.\n'
                  'Option toggles reset. System/gallery and battle saves are not converted.\n'
                  'PSP output is for PPSSPP only. PS2 loading and save/reload still need testing.',
                  wraplength=550).grid(row=5, column=0, columnspan=3, sticky='w', pady=8)
        ttk.Checkbutton(body, text='My saves match this test profile; I understand the experimental limits.',
                        variable=self.mx_experimental).grid(row=6, column=0, columnspan=3, sticky='w')
        def close():
            self.settings.update(mx_game_file=self.mx_boot.get(), mx_ppsspp=self.mx_ppsspp.get())
            try:
                atomic_json(self.settings_path, self.settings)
            except OSError:
                pass
            dialog.destroy()
        ttk.Button(body, text='Done', command=close).grid(row=7, column=2, sticky='e', pady=(10, 0))
        dialog.protocol('WM_DELETE_WINDOW', close)
        dialog.bind('<Return>', lambda event: (close(), 'break')[-1])
        dialog.bind('<Escape>', lambda event: close())
        dialog.grab_set()

    def save_help(self):
        dialog = tk.Toplevel(self)
        mx = self.save_game.get().startswith('MX')
        dialog.title(('MX' if mx else 'Z3') + ' save conversion instructions')
        dialog.transient(self)
        text = tk.Text(dialog, wrap='word', width=78, height=24, padx=12, pady=12)
        bar = ttk.Scrollbar(dialog, command=text.yview)
        bar.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        text.configure(yscrollcommand=bar.set)
        text.insert('1.0', (mx_converter.GUIDE if mx else z3_saves.GUIDE).read_text(encoding='utf-8'))
        text.configure(state='disabled')
        dialog.bind('<Escape>', lambda event: dialog.destroy())

    def convert_saves(self):
        ps3, vita, output = self.save_ps3.get(), self.save_vita.get(), self.save_output.get()
        if not all(value.strip() for value in (ps3, vita, output)) or not self.save_closed.get():
            self.status.set('Choose both save folders, a new output folder, and close both emulators.')
            return
        direction = self.save_directions[self.save_direction.get()]
        checked = self.save_checked
        self.save_checked = None
        if self.save_game.get().startswith('MX'):
            self.convert_mx(ps3, vita, output, direction, checked)
            return
        if checked is None:
            self.start(lambda cancel, progress: z3_saves.build(ps3, vita, output,
                direction=direction, cancel=cancel, progress=progress), 'save_check')
        else:
            def work(cancel, progress):
                z3_saves.build(ps3, vita, output, write=True, expected_sources=checked['source_files'],
                    direction=direction, cancel=cancel, progress=progress)
                return (Path(output), 'Converted saves, original backups, and ZIPs verified.\n'
                        'Use the included instructions to import and test them in the destination emulator.')
            self.start(work, 'save_convert')

    def convert_mx(self, ps2, psp, output, direction, checked):
        options = dict(direction=direction, ps2_slot=self.mx_slot.get().strip() or None,
                       boot_path=self.mx_boot.get().strip() or None, ppsspp_path=self.mx_ppsspp.get().strip() or None,
                       balance='keep' if direction == 'ps2-to-psp' else ('psp' if self.mx_psp_difficulty.get() else 'original'),
                       experimental=self.mx_experimental.get())
        if checked is None:
            self.start(lambda cancel, progress: mx_converter.build(ps2, psp, output,
                cancel=cancel, progress=progress, **options), 'save_check')
        else:
            def work(cancel, progress):
                mx_converter.build(ps2, psp, output, write=True, expected_sources=checked['source_files'],
                                   cancel=cancel, progress=progress, **options)
                return Path(output), ('Experimental MX saves created with verified files, backups and import instructions.\n'
                                      'Game load, next battle and save/reload still need testing on a separate profile/card.')
            self.start(work, 'save_convert')

    def choose_source(self):
        path = self.pick_path(tk.StringVar())
        if path:
            self.identify_source(path)

    def identify_source(self, path):
        self.apply_source.set(str(path))
        self.selection, self.plan = None, None
        self.file_label.set(str(path))
        self.detected.set('Identifying…')
        catalog = self.catalog
        self.start(lambda cancel, progress: [(Path(path), n) for n in recognize(
            path, catalog, cancel, progress, defer_chd=True)], 'identify')

    def prepare_chd(self, path, manual=False, automatic=False):
        """Ask on the UI thread; extract once in the background and keep the result."""
        path = Path(path).resolve()
        if not manual:
            self.selection, self.plan = None, None
            self.apply_source.set(str(path))
            self.file_label.set(str(path))
            self.detected.set('CHD — extraction required to identify the disc')
            self.route.set('Select this CHD to unpack it, or browse to an already extracted ISO/BIN.')
            self.update_action()
        if automatic and path in self.declined_chds:
            return
        try:
            disc, destination = inspect_chd(path), extraction_folder(path)
        except (OSError, PatchError) as exc:
            self.status.set('Could not prepare this CHD.')
            self.detail.set(str(exc))
            return
        if not messagebox.askyesno('Unpack CHD once?',
                'Extract this CHD into a new child folder?\n\n' + str(destination) +
                '\n\nThe extracted disc needs {:.2f} GiB of space. This may take a while.\n'
                'The app will select the extracted ISO/BIN and use it for patching, without '
                'unpacking the source again. The CHD and completed extraction are kept.\n\n'
                'Unpack now?'.format(disc.size / (1024 ** 3)), parent=self):
            self.declined_chds.add(path)
            self.status.set('CHD extraction not started.')
            self.detail.set('Nothing was unpacked. Select the CHD again to retry, or browse to an extracted ISO/BIN.')
            return
        self.declined_chds.discard(path)
        self.start(lambda cancel, progress: (path, unpack_to_folder(path, destination, cancel, progress)),
                   'unpack_manual' if manual else 'unpack_auto')

    def choose_folder(self):
        path = filedialog.askdirectory(title='Choose the folder containing all required game files', mustexist=True,
            initialdir=self.settings.get('last_browse_folder', str(application_root())))
        if path:
            self.selection, self.plan = None, None
            self.file_label.set(path)
            self.detected.set('Identifying file set…')
            catalog = self.catalog
            self.start(lambda cancel, progress: scan_root(path, catalog, cancel, progress, defer_chd=True), 'identify')

    def scan(self):
        self.selection, self.plan = None, None
        self.file_label.set("")
        self.detected.set("Scanning the app folder…")
        catalog = self.catalog
        self.start(lambda cancel, progress: scan_root(application_root(), catalog, cancel, progress, defer_chd=True), "scan")

    def select_found(self, event=None, automatic=False):
        index = self.file_box.current()
        if 0 <= index < len(self.found):
            self.selection = self.found[index]
            if isinstance(self.selection[1], ChdSource) or (self.selection[0].is_file() and is_chd(self.selection[0])):
                self.prepare_chd(self.selection[0], automatic=automatic)
                return True
            if isinstance(self.selection[1], SolutionSource):
                self.selection = (self.selection[1].root, self.selection[1])
            extracted = self.selection[0].resolve() in self.extracted_inputs
            self.detected.set(self.selection[1].label + (' • extracted disc' if extracted else ''))
            self.output_format.set('CHD' if extracted else 'Original format')
            self.apply_source.set(str(self.selection[0]))
            self.target_box.configure(values=["Latest", "Next version only"] + [n.version for n in self.catalog.versions(self.selection[1])])
            self.target.set("Latest")
            self.plan_selection()

    def plan_selection(self):
        self.plan = None
        self.plan_problem = ''
        self.detail.set('Your originals are preserved. The route runs only when you click Patch.')
        grouped = self.selection and isinstance(self.selection[1], SolutionSource)
        self.auto_output_label.configure(text='New folder:' if grouped else 'Patched copy:')
        self.auto_output_button.configure(text='Folder…' if grouped else 'Save as…')
        if self.selection:
            try:
                self.plan = self.catalog.plan(self.selection[1], self.target.get())
                self.route.set(self.plan.summary if self.plan.edges else "Already at the selected version. " + self.plan.summary)
                path = self.selection[0]
                if isinstance(self.plan, SolutionPlan):
                    self.output_format_box.configure(values=['Original format'])
                    self.output_format.set('Original format')
                    self.output.set(str(path / (self.plan.target.id[1] + '-v' + self.plan.target.version)))
                    self.update_action()
                    return
                can_pack = self.plan.target.format == 'iso' or (self.plan.target.format == 'bin' and
                    path.is_file() and (is_chd(path) or unpacked_layout(path) is not None))
                self.output_format_box.configure(values=['Original format', 'CHD'] if can_pack else ['Original format'])
                if not can_pack:
                    self.output_format.set('Original format')
                extension = 'chd' if self.output_format.get() == 'CHD' else self.plan.target.format
                self.output.set(str(path.with_name(path.stem + "-v" + self.plan.target.version + "." + extension)))
            except PatchError as exc:
                self.plan_problem = str(exc)
                self.route.set('No complete patch route. See the missing-file details below.'
                               if grouped and len(str(exc)) > 160 else str(exc))
                self.detail.set(self.plan_problem)
        self.update_action()

    def route_details(self):
        if self.plan:
            if isinstance(self.plan, SolutionPlan):
                dialog = tk.Toplevel(self)
                dialog.title('Patch solution')
                dialog.transient(self)
                text = tk.Text(dialog, wrap='word', width=76, height=20, padx=10, pady=10)
                bar = ttk.Scrollbar(dialog, command=text.yview)
                bar.pack(side='right', fill='y')
                text.pack(fill='both', expand=True)
                text.configure(yscrollcommand=bar.set)
                text.insert('1.0', self.plan.details)
                text.configure(state='disabled')
                dialog.bind('<Escape>', lambda event: dialog.destroy())
            else:
                messagebox.showinfo("Patch route", self.plan.summary + "\n\n" + "\n".join(e.asset.name for e in self.plan.edges))

    def update_detail(self, *args):
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", self.detail.get())
        self.detail_text.configure(state="disabled")
        self.detail_text.yview_moveto(0)

    def update_action(self):
        if not hasattr(self, "apply_button"):
            return
        tab = self.notebook.index(self.notebook.select())
        enabled = not self.busy and (tab != 0 or (self.plan and self.plan.edges))
        if tab == 2:
            enabled = enabled and self.save_closed.get() and all(v.get().strip() for v in
                (self.save_ps3, self.save_vita, self.save_output))
        if tab == 3:
            enabled = enabled and all(v.get().strip() for v in
                (self.vita_source, self.vita_output, self.vita_license))
        self.apply_button.configure(text=("Patch", "Apply patch", 'Convert saves' if self.save_checked else 'Check saves', 'Create rePatch')[tab],
            state="normal" if enabled else "disabled")

    def pick_vita_folder(self, variable, output=False):
        path = filedialog.askdirectory(title='Choose where to create the rePatch output' if output else
                                       'Choose decrypted PCSG00264 (contains eboot.bin)', mustexist=True)
        if path:
            if output:
                base = Path(path) / ('Vita-rePatch-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
                candidate, suffix = base, 1
                while candidate.exists():
                    candidate = base.with_name(base.name + '-' + str(suffix))
                    suffix += 1
                variable.set(str(candidate))
            else:
                variable.set(path)

    def create_vita_repatch(self):
        source, output, description = [v.get().strip() for v in
                                       (self.vita_source, self.vita_output, self.vita_description)]
        if not source or not output:
            return
        work_bin = self.vita_license.get().strip()
        if not work_bin:
            return
        def work(cancel, progress):
            result = vita_repatch.apply(source, output, description or None, self.client,
                                       cancel=cancel, progress=progress, work_bin=work_bin)
            return result, vita_repatch.GUIDE
        self.start(work, 'vita_repatch')

    def set_busy(self, busy):
        self.busy = busy
        for control in self.controls:
            control.configure(state="disabled" if busy else ("readonly" if control in self.readonly_controls else "normal"))
        if busy and self.job_kind in ("scan", "identify"):
            for control in self.selection_buttons:
                control.configure(state="normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.update_action()

    def start(self, work, kind):
        if self.busy and self.job_kind not in ("scan", "identify"):
            return
        self.cancel.set()
        self.cancel = threading.Event()
        self.job_id += 1
        job, cancel = self.job_id, self.cancel
        self.job_kind = kind
        self.set_busy(True)
        self.status_label.configure(foreground=TEXT)
        self.status.set({"scan": "Scanning app folder…", "identify": "Identifying binary…"}.get(kind, "Working…"))
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.folder_button.configure(state="disabled")
        def progress(message, fraction):
            self.events.put(("progress", job, (message, fraction)))
        def run():
            try:
                self.events.put(("done", job, (kind, work(cancel, progress))))
            except Exception as exc:
                self.events.put(("error", job, exc))
        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()

    def refresh(self):
        if self.refresh_running:
            return
        self.refresh_running = True
        self.refresh_button.configure(state="disabled")
        def run():
            try:
                self.events.put(("catalog", None, refresh_catalog(self.client, cancel=self.background_cancel)))
            except Exception as exc:
                self.events.put(("catalog_error", None, str(exc)))
            try:
                message = stage_update(self.client, cancel=self.background_cancel)
                if message:
                    self.events.put(("update", None, message))
            except Exception as exc:
                self.events.put(("update", None, "Update check unavailable: " + str(exc)))
            finally:
                self.events.put(("refresh_finished", None, None))
        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()

    def apply(self):
        if self.busy:
            return
        tab = self.notebook.index(self.notebook.select())
        if tab == 3:
            self.create_vita_repatch()
            return
        if tab == 2:
            self.convert_saves()
            return
        if tab == 0:
            if not self.selection or not self.plan or not self.plan.edges or not self.output.get():
                return
            source, plan, catalog, output = self.selection[0], self.plan, self.catalog, self.output.get()
            if source.is_file() and is_chd(source):
                self.prepare_chd(source)
                return
            nodes = [p.source for _, _, p in plan.parts] if isinstance(plan, SolutionPlan) else [plan.source]
            ps3 = any(is_ps3_platform(n.platform) for n in nodes)
            chd_output = self.output_format.get() == 'CHD'
            def work(cancel, progress):
                apply_plan(source, output, plan, catalog, self.client, cancel=cancel, progress=progress, chd_output=chd_output)
                if isinstance(plan, SolutionPlan):
                    return (Path(output), 'Complete patch solution verified. Patched files and required unchanged files saved together.' + reminder)
                return (Path(output), 'Every patch step was verified.' +
                        (' New CHD output verified against the patched disc.' if chd_output else ' Final disc bytes verified.') + reminder)
        else:
            values = (self.apply_source, self.apply_delta, self.apply_output)
            source, second, output = [v.get() for v in values]
            if not all((source, second, output)):
                self.status.set("Choose both inputs and an output filename.")
                return
            unpack, chd_output = self.unpack_chd.get(), self.manual_format.get() == 'CHD'
            if unpack and Path(source).is_file() and is_chd(source):
                self.prepare_chd(source, manual=True)
                return
            ps3 = looks_like_ps3(source)
            if self.selection and Path(source).resolve() == self.selection[0].resolve():
                node = self.selection[1]
                nodes = [n for _, n in node.found.values()] if isinstance(node, SolutionSource) else [node]
                ps3 = ps3 or any(is_ps3_platform(n.platform) for n in nodes)
            def work(cancel, progress):
                digest = manual_patch(source, second, output, cancel=cancel, progress=progress,
                                      unpack_chd=unpack, chd_output=chd_output)
                return (Path(output), 'Applied with xdelta checks; no catalog output hash was supplied.\n' +
                        ('CHD round trip verified. Patched disc SHA-256: ' if chd_output else 'Output SHA-256: ') + digest + reminder)
        reminder = '\n\n' + (INSTALLATION_WARNING if ps3 else MANUAL_REMINDER) if ps3 or tab == 1 else ''
        if ps3:
            messagebox.showwarning('PS3 installation data', INSTALLATION_WARNING, parent=self)
        self.start(work, "patch")

    def poll(self):
        try:
            while True:
                kind, job, value = self.events.get_nowait()
                if job is not None and job != self.job_id:
                    continue
                if kind == "catalog":
                    # A normal startup refresh usually returns the same catalog.
                    # Do not queue another full image read after the initial scan.
                    self.pending_catalog = value if value.data != self.catalog.data else None
                    self.catalog_status.set("Catalog current: {} patches".format(len(value.edges)))
                elif kind == "catalog_error":
                    self.catalog_status.set("Using saved catalog (refresh unavailable)")
                elif kind == "refresh_finished":
                    self.refresh_running = False
                    self.refresh_button.configure(state="normal")
                elif kind == "update":
                    self.app_update_status = value
                elif kind == "progress" and not self.cancel.is_set():
                    message, fraction = value
                    self.status.set(message)
                    if fraction is None:
                        if str(self.progress["mode"]) != "indeterminate":
                            self.progress.configure(mode="indeterminate")
                            self.progress.start(30)
                    else:
                        self.progress.stop()
                        self.progress.configure(mode="determinate", value=fraction * 100)
                elif kind in ("done", "error"):
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.set_busy(False)
                    if kind == "error":
                        self.status.set("Cancelled." if isinstance(value, Cancelled) else "Could not complete this step.")
                        self.status_label.configure(foreground=MUTED if isinstance(value, Cancelled) else ERROR)
                        self.detail.set(str(value))
                        if self.job_kind in ('scan', 'identify'):
                            self.selection, self.plan, self.found = None, None, []
                            self.file_box.configure(values=[])
                            self.detected.set('Identification cancelled.' if isinstance(value, Cancelled) else 'Could not identify this file set.')
                            self.route.set('See the details below.')
                            self.update_action()
                    elif value[0] in ("scan", "identify"):
                        self.found = value[1]
                        self.file_box.configure(values=["{} — {}".format(p.name, n.label) for p, n in self.found])
                        self.selection, self.plan = None, None
                        self.plan_problem = ''
                        if len(self.found) == 1:
                            self.file_box.current(0)
                            if self.select_found(automatic=value[0] == 'scan'):
                                continue
                        else:
                            if self.found:
                                self.file_label.set("")
                            self.detected.set("Choose a file to identify or patch" if self.found else "No recognized binary")
                            self.route.set("Select a file set above." if self.found else "Browse to another file or folder, or use Apply xdelta for a local patch.")
                        self.status.set("{} file/version entries found.".format(len(self.found)))
                        self.detail.set(self.plan_problem or "Your original is preserved. The route runs only when you click Patch.")
                        if not self.found and Path(self.apply_source.get()).resolve() in self.extracted_inputs:
                            self.detail.set('No catalog match. The extracted disc is kept at:\n' +
                                            self.apply_source.get() + '\nUse Apply xdelta if you have a local patch.')
                        self.update_action()
                    elif value[0] in ('unpack_auto', 'unpack_manual'):
                        source, binary = value[1]
                        self.extracted_inputs.add(binary.resolve())
                        self.apply_source.set(str(binary))
                        if value[0] == 'unpack_auto':
                            self.manual_format.set('CHD' if self.unpack_chd.get() else 'Original format')
                        previous = Path(self.apply_output.get())
                        if not self.apply_output.get() or (previous.parent == source.parent and
                                previous.stem == source.stem + '-patched'):
                            self.apply_output.set(str(binary.with_name(binary.stem + '-patched' + binary.suffix)))
                        self.change_output_format(manual=True)
                        self.status.set('CHD unpacked. The extracted disc is now selected.')
                        self.detail.set('Kept: ' + str(binary) + '\nThe original CHD is preserved. Click Patch when ready.')
                        if value[0] == 'unpack_auto':
                            self.file_label.set(str(binary))
                            if not self.cancel.is_set() and not self.closing:
                                self.identify_source(binary)
                            else:
                                self.detected.set('Extracted disc kept; identification cancelled.')
                    elif value[0] == 'save_check':
                        if self.cancel.is_set():
                            self.status.set('Cancelled.')
                        else:
                            self.save_checked = value[1]
                            mappings = value[1]['mappings']
                            self.save_summary.set('{} saves checked. Ready to convert.'.format(len(mappings)))
                            self.status.set('Check passed. Review the slots, then click Convert saves.')
                            self.detail.set('\n'.join(m['source_folder'] + ' → ' + m['destination_folder'] for m in mappings))
                            if value[1].get('profile') == mx_converter.PROFILE:
                                self.mx_source_difficulty = next((m['source_balance'] for m in mappings
                                    if m['direction'] == 'ps2-to-psp'), None)
                                self.refresh_mx_difficulty()
                                self.save_summary.set('Experimental MX candidate checked. Review the details before converting.')
                                difficulty = {'original': 'PS2 Original', 'psp': 'PSP'}
                                self.detail.set('\n'.join(m['source_folder'] + ' → ' + m['destination_folder'] +
                                    '\nFunds: {:,}; units: {}; pilots: {}; difficulty: {} → {}; favorites kept: {}.'.format(
                                        m['source']['funds'], m['source']['unit_count'], m['source']['pilot_count'],
                                        difficulty[m['source_balance']], difficulty[m['destination_balance']],
                                        ', '.join(m['retained_series'])) for m in mappings)
                                    + '\n\n' + '\n'.join(value[1]['warnings']))
                            self.progress.configure(value=100)
                        self.update_action()
                    else:
                        self.saved_output, message = value[1]
                        if value[0] == 'save_convert':
                            self.save_output.set(str(self.next_save_output(self.saved_output.parent)))
                        self.status.set("Completed.")
                        self.status_label.configure(foreground=ACCENT)
                        self.detail.set(message + "\nSaved: " + str(self.saved_output))
                        self.progress.configure(value=100)
                        self.folder_button.configure(state="normal")
        except queue.Empty:
            pass
        if (self.pending_catalog and not self.busy and not self.closing
                and self.notebook.index(self.notebook.select()) == 0):
            self.catalog, self.pending_catalog = self.pending_catalog, None
            if self.selection and self.notebook.index(self.notebook.select()) == 0:
                path, catalog = self.selection[0], self.catalog
                self.start(lambda cancel, progress: [(path, n) for n in recognize(path, catalog, cancel, progress, defer_chd=True)], "identify")
            elif Path(self.apply_source.get()).resolve() in self.extracted_inputs:
                self.identify_source(self.apply_source.get())
            elif self.notebook.index(self.notebook.select()) == 0:
                self.scan()
        self.threads = [t for t in self.threads if t.is_alive()]
        if self.closing and not self.threads:
            self.destroy()
        else:
            self.after(80, self.poll)

    def cancel_work(self):
        self.cancel.set()
        self.status.set("Cancelling…")
        self.cancel_button.configure(state="disabled")

    def close_app(self):
        self.closing = True
        self.cancel.set()
        self.background_cancel.set()
        self.status.set("Closing; waiting for work to stop…")
        if not any(t.is_alive() for t in self.threads):
            self.destroy()

    def about(self):
        messagebox.showinfo("Retro Trans " + __version__, self.app_update_status +
            "\n\nApp and releases:\nhttps://github.com/" + APP_REPO +
            "\n\nAutomatic mode verifies catalog hashes. Manual xdelta and save conversion work offline.")

    def open_folder(self):
        if self.saved_output:
            os.startfile(str(self.saved_output if self.saved_output.is_dir() else self.saved_output.parent))

    def destroy(self):
        for callback in self.tk.splitlist(self.tk.call("after", "info")):
            self.after_cancel(callback)
        super().destroy()


def main(health_report=None):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    app = Application()
    if health_report:
        atomic_json(health_report, {"ok": True, "version": __version__})
    app.mainloop()
