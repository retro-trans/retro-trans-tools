"""Compact native tabs; stale background results cannot change a newer selection."""
import json
import os
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

TEXT, MUTED, ACCENT, ERROR = "#202020", "#606060", "#166534", "#a4262c"


class Application(tk.Tk):
    def __init__(self, startup=True, visible=True):
        super().__init__()
        if not visible:
            self.withdraw()
        self.title("Retro Trans Patcher")
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
        self.detail = tk.StringVar(value="Select a binary or use the standalone xdelta tabs.")
        self.catalog_status = tk.StringVar(value="Catalog: {} patches".format(len(self.catalog.edges)))
        self.app_update_status = update_status()
        self.detected = tk.StringVar(value="No binary selected")
        self.file_label, self.output = tk.StringVar(), tk.StringVar()
        self.target = tk.StringVar(value="Latest")
        self.route = tk.StringVar(value="Select a recognized binary to see its patch route.")
        self.apply_source, self.apply_delta, self.apply_output = (tk.StringVar() for _ in range(3))
        self.create_source, self.create_modified, self.create_output = (tk.StringVar() for _ in range(3))
        self.settings_path = cache_directory().parent / "settings.json"
        try:
            self.settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if not isinstance(self.settings, dict):
                self.settings = {}
        except (ValueError, OSError):
            self.settings = {}
        self.build_styles()
        self.build_layout()
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
        for title in ("Automatic", "Apply xdelta", "Create xdelta"):
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
        self.path_row(self.tabs[1], 0, "Original file:", self.apply_source)
        self.path_row(self.tabs[1], 1, "Patch file:", self.apply_delta, extension=".xdelta")
        self.path_row(self.tabs[1], 2, "Patched copy:", self.apply_output, save=True)
        ttk.Label(self.tabs[1], text="Applies a local patch with xdelta checks. No catalog match required.",
                  style="Muted.TLabel").grid(row=3, column=0, columnspan=3, sticky="w", pady=8)
        self.path_row(self.tabs[2], 0, "Original file:", self.create_source)
        self.path_row(self.tabs[2], 1, "Modified file:", self.create_modified)
        self.path_row(self.tabs[2], 2, "Save patch:", self.create_output, save=True, extension=".xdelta")
        ttk.Label(self.tabs[2], text="Creates a standard xdelta patch. Both inputs are kept intact.",
                  style="Muted.TLabel").grid(row=3, column=0, columnspan=3, sticky="w", pady=8)
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
            self.settings["last_browse_folder"] = str(Path(path).parent)
            try:
                atomic_json(self.settings_path, self.settings)
            except OSError:
                pass
        return path

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
            self.detected.set(self.selection[1].label)
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
                self.output.set(str(path.with_name(path.stem + "-v" + self.plan.target.version + "." + self.plan.target.format)))
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
        self.apply_button.configure(text=("Patch", "Apply patch", "Create patch")[tab],
            state="normal" if not self.busy and (tab != 0 or (self.plan and self.plan.edges)) else "disabled")

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
        if tab == 0:
            if not self.selection or not self.plan or not self.plan.edges or not self.output.get():
                return
            source, plan, catalog, output = self.selection[0], self.plan, self.catalog, self.output.get()
            def work(cancel, progress):
                apply_plan(source, output, plan, catalog, self.client, cancel=cancel, progress=progress)
                return (Path(output), "Every patch step and the final output were verified.")
        else:
            values = (self.apply_source, self.apply_delta, self.apply_output) if tab == 1 else (self.create_source, self.create_modified, self.create_output)
            source, second, output = [v.get() for v in values]
            if not all((source, second, output)):
                self.status.set("Choose both inputs and an output filename.")
                return
            def work(cancel, progress):
                digest = manual_patch(source, second, output, create=tab == 2, cancel=cancel, progress=progress)
                mode = "Patch created." if tab == 2 else "Applied with xdelta checks; no catalog output hash was supplied."
                return (Path(output), mode + "\nOutput SHA-256: " + digest)
        self.start(work, "patch")

    def poll(self):
        try:
            while True:
                kind, job, value = self.events.get_nowait()
                if job is not None and job != self.job_id:
                    continue
                if kind == "catalog":
                    self.pending_catalog = value
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
                    else:
                        self.saved_output, message = value[1]
                        self.status.set("Completed.")
                        self.status_label.configure(foreground=ACCENT)
                        self.detail.set(message + "\nSaved: " + str(self.saved_output))
                        self.progress.configure(value=100)
                        self.folder_button.configure(state="normal")
        except queue.Empty:
            pass
        if self.pending_catalog and not self.busy and not self.closing:
            self.catalog, self.pending_catalog = self.pending_catalog, None
            if self.selection:
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
            "\n\nAutomatic mode verifies catalog hashes. Manual xdelta works offline.")

    def open_folder(self):
        if self.saved_output:
            os.startfile(str(self.saved_output.parent))

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
