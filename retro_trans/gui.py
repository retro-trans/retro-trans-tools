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
from . import z3_saves
from .chd import is_chd, inspect_chd

TEXT, MUTED, ACCENT, ERROR = "#202020", "#606060", "#166534", "#a4262c"


class Application(tk.Tk):
    def __init__(self, startup=True, visible=True):
        super().__init__()
        if not visible:
            self.withdraw()
        self.title("Retro Trans")
        self.geometry("700x440")
        self.client, self.catalog = GitHubClient(), load_catalog()
        self.pending_catalog = None
        self.events, self.threads = queue.Queue(), []
        self.cancel, self.background_cancel = threading.Event(), threading.Event()
        self.job_id, self.job_kind = 0, ""
        self.busy, self.closing, self.refresh_running = False, False, False
        self.selection, self.plan, self.saved_output = None, None, None
        self.found, self.controls, self.readonly_controls, self.selection_buttons = [], [], [], []
        self.status = tk.StringVar(value="Ready.")
        self.detail = tk.StringVar(value="Select a binary, apply a local patch, or convert Z3 saves.")
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
        self.build_styles()
        self.build_layout()
        for variable in (self.save_ps3, self.save_vita, self.save_output, self.save_direction, self.save_closed):
            variable.trace_add('write', self.invalidate_saves)
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
        for title in ("Automatic", "Apply xdelta", "Z3 saves"):
            page = ttk.Frame(self.notebook, padding=10)
            page.columnconfigure(1, weight=1)
            self.notebook.add(page, text=title)
            self.tabs.append(page)
        auto = self.tabs[0]
        ttk.Label(auto, text="Binary:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.file_box = ttk.Combobox(auto, textvariable=self.file_label, state="readonly", width=1)
        self.file_box.grid(row=0, column=1, sticky="ew")
        self.controls.append(self.file_box)
        self.readonly_controls.append(self.file_box)
        self.file_box.bind("<<ComboboxSelected>>", self.select_found)
        actions = ttk.Frame(auto)
        actions.grid(row=0, column=2, padx=(8, 0))
        browse = self.button(actions, "Browse…", self.choose_source)
        browse.pack(side="left")
        scan = self.button(actions, "Scan", self.scan)
        scan.pack(side="left", padx=(4, 0))
        self.selection_buttons.extend([browse, scan])
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
        self.path_row(auto, 4, "Patched copy:", self.output, save=True)
        self.output_format_box = self.format_row(auto, 5, self.output_format, lambda: self.change_output_format())
        self.path_row(self.tabs[1], 0, "Original file:", self.apply_source)
        self.path_row(self.tabs[1], 1, "Patch file:", self.apply_delta, extension=".xdelta")
        self.path_row(self.tabs[1], 2, "Patched copy:", self.apply_output, save=True)
        self.manual_format_box = self.format_row(self.tabs[1], 3, self.manual_format, lambda: self.change_output_format(manual=True))
        unpack = ttk.Checkbutton(self.tabs[1], text='Unpack CHD input before patching', variable=self.unpack_chd,
                                 command=self.manual_chd_mode)
        unpack.grid(row=4, column=0, columnspan=3, sticky='w', pady=3)
        self.controls.append(unpack)
        ttk.Label(self.tabs[1], text="Local xdelta checks; no catalog match required.",
                  style="Muted.TLabel").grid(row=5, column=0, columnspan=3, sticky="w", pady=3)
        saves = self.tabs[2]
        ttk.Label(saves, text='Convert:').grid(row=0, column=0, sticky='w')
        direction = ttk.Combobox(saves, textvariable=self.save_direction,
                                values=list(self.save_directions), state='readonly', width=1)
        direction.grid(row=0, column=1, sticky='ew')
        self.controls.append(direction)
        self.readonly_controls.append(direction)
        self.button(saves, 'Instructions', self.save_help).grid(row=0, column=2, sticky='ew', padx=(8, 0))
        self.save_folder_row(saves, 1, 'RPCS3 saves:', self.save_ps3)
        self.save_folder_row(saves, 2, 'Vita3K saves:', self.save_vita)
        self.save_folder_row(saves, 3, 'New output:', self.save_output, output=True)
        closed = ttk.Checkbutton(saves, text='Both emulators are closed.', variable=self.save_closed)
        closed.grid(row=4, column=0, columnspan=3, sticky='w', pady=3)
        self.controls.append(closed)
        ttk.Label(saves, textvariable=self.save_summary, style='Muted.TLabel').grid(
            row=5, column=0, columnspan=3, sticky='w', pady=(3, 0))
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
        ttk.Label(page, text=title).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        entry = ttk.Entry(page, textvariable=variable, width=1)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        self.controls.append(entry)
        self.button(page, "Save as…" if save else "Browse…", lambda: self.pick_path(variable, save, extension)).grid(
            row=row, column=2, sticky="ew", padx=(8, 0), pady=3)

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
        return path

    @staticmethod
    def next_save_output(parent):
        stem = 'Z3-saves-' + datetime.now().strftime('%Y%m%d-%H%M%S')
        path, suffix = parent / stem, 1
        while path.exists():
            path = parent / (stem + '-' + str(suffix))
            suffix += 1
        return path

    def save_folder_row(self, page, row, title, variable, output=False):
        ttk.Label(page, text=title).grid(row=row, column=0, sticky='w', padx=(0, 8), pady=3)
        entry = ttk.Entry(page, textvariable=variable, width=1)
        entry.grid(row=row, column=1, sticky='ew', pady=3)
        self.controls.append(entry)
        self.button(page, 'Browse…', lambda: self.pick_save_folder(variable, output)).grid(
            row=row, column=2, sticky='ew', padx=(8, 0), pady=3)

    def pick_save_folder(self, variable, output=False):
        path = filedialog.askdirectory(title='Choose where to create a new output folder' if output else
            ('Choose RPCS3 savedata (contains NPJB00520 folders)' if variable is self.save_ps3 else
             'Choose Vita3K PCSG00264 save folder'), mustexist=True)
        if path:
            variable.set(str(self.next_save_output(Path(path))) if output else path)

    def invalidate_saves(self, *args):
        self.save_checked = None
        self.save_summary.set('Both save folders need system data and a manual save.')
        self.update_action()

    def save_help(self):
        dialog = tk.Toplevel(self)
        dialog.title('Z3 save conversion instructions')
        dialog.transient(self)
        text = tk.Text(dialog, wrap='word', width=78, height=24, padx=12, pady=12)
        bar = ttk.Scrollbar(dialog, command=text.yview)
        bar.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        text.configure(yscrollcommand=bar.set)
        text.insert('1.0', z3_saves.GUIDE.read_text(encoding='utf-8'))
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

    def choose_source(self):
        path = self.pick_path(tk.StringVar())
        if path:
            self.apply_source.set(path)
            self.selection, self.plan = None, None
            self.file_label.set(path)
            self.detected.set("Identifying…")
            catalog = self.catalog
            self.start(lambda cancel, progress: [(Path(path), n) for n in recognize(path, catalog, cancel, progress)], "identify")

    def scan(self):
        self.selection, self.plan = None, None
        self.file_label.set("")
        self.detected.set("Scanning the app folder…")
        catalog = self.catalog
        self.start(lambda cancel, progress: scan_root(application_root(), catalog, cancel, progress), "scan")

    def select_found(self, event=None):
        index = self.file_box.current()
        if 0 <= index < len(self.found):
            self.selection = self.found[index]
            chd = is_chd(self.selection[0]) if self.selection[0].is_file() else False
            self.detected.set(self.selection[1].label + (' • CHD (disc verified on Patch)' if chd else ''))
            self.output_format.set('CHD' if chd else 'Original format')
            self.apply_source.set(str(self.selection[0]))
            self.target_box.configure(values=["Latest", "Next version only"] + [n.version for n in self.catalog.versions(self.selection[1])])
            self.target.set("Latest")
            self.plan_selection()

    def plan_selection(self):
        self.plan = None
        if self.selection:
            try:
                self.plan = self.catalog.plan(self.selection[1], self.target.get())
                self.route.set(self.plan.summary if self.plan.edges else "Already at the selected version. " + self.plan.summary)
                path = self.selection[0]
                can_pack = self.plan.target.format == 'iso' or (self.plan.target.format == 'bin' and
                    path.is_file() and is_chd(path))
                self.output_format_box.configure(values=['Original format', 'CHD'] if can_pack else ['Original format'])
                if not can_pack:
                    self.output_format.set('Original format')
                extension = 'chd' if self.output_format.get() == 'CHD' else self.plan.target.format
                self.output.set(str(path.with_name(path.stem + "-v" + self.plan.target.version + "." + extension)))
            except PatchError as exc:
                self.route.set(str(exc))
        self.update_action()

    def route_details(self):
        if self.plan:
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
        self.apply_button.configure(text=("Patch", "Apply patch", 'Convert saves' if self.save_checked else 'Check saves')[tab],
            state="normal" if enabled else "disabled")

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
        if tab == 2:
            self.convert_saves()
            return
        if tab == 0:
            if not self.selection or not self.plan or not self.plan.edges or not self.output.get():
                return
            source, plan, catalog, output = self.selection[0], self.plan, self.catalog, self.output.get()
            chd_output = self.output_format.get() == 'CHD'
            def work(cancel, progress):
                apply_plan(source, output, plan, catalog, self.client, cancel=cancel, progress=progress, chd_output=chd_output)
                return (Path(output), 'Every patch step was verified.' +
                        (' The CHD was extracted again and matched the verified disc.' if chd_output else ' Final disc bytes verified.'))
        else:
            values = (self.apply_source, self.apply_delta, self.apply_output)
            source, second, output = [v.get() for v in values]
            if not all((source, second, output)):
                self.status.set("Choose both inputs and an output filename.")
                return
            unpack, chd_output = self.unpack_chd.get(), self.manual_format.get() == 'CHD'
            def work(cancel, progress):
                digest = manual_patch(source, second, output, cancel=cancel, progress=progress,
                                      unpack_chd=unpack, chd_output=chd_output)
                return (Path(output), 'Applied with xdelta checks; no catalog output hash was supplied.\n' +
                        ('CHD round trip verified. Patched disc SHA-256: ' if chd_output else 'Output SHA-256: ') + digest)
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
                    elif value[0] in ("scan", "identify"):
                        self.found = value[1]
                        self.file_box.configure(values=["{} — {}".format(p.name, n.label) for p, n in self.found])
                        self.selection, self.plan = None, None
                        if len(self.found) == 1:
                            self.file_box.current(0)
                            self.select_found()
                        else:
                            self.file_label.set("")
                            self.detected.set("Choose a recognized file" if self.found else "No recognized binary")
                            self.route.set("Select a file above." if self.found else "Browse to another file, or use Apply xdelta for a local patch.")
                        self.status.set("{} matching file/version entries found.".format(len(self.found)))
                        self.detail.set("Your original is preserved. The route runs only when you click Patch.")
                        self.update_action()
                    elif value[0] == 'save_check':
                        if self.cancel.is_set():
                            self.status.set('Cancelled.')
                        else:
                            self.save_checked = value[1]
                            mappings = value[1]['mappings']
                            self.save_summary.set('{} saves checked. Ready to convert.'.format(len(mappings)))
                            self.status.set('Check passed. Review the slots, then click Convert saves.')
                            self.detail.set('\n'.join(m['source_folder'] + ' → ' + m['destination_folder'] for m in mappings))
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
                self.start(lambda cancel, progress: [(path, n) for n in recognize(path, catalog, cancel, progress)], "identify")
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
            "\n\nAutomatic mode verifies catalog hashes. Manual xdelta and Z3 save conversion work offline.")

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
