import os
from pathlib import Path
import unittest
from unittest.mock import patch

from retro_trans.gui import Application


@unittest.skipUnless(os.name == "nt", "Native Windows UI test")
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.app = Application(startup=False)
        self.app.attributes("-alpha", 0)
        for callback in self.app.tk.splitlist(self.app.tk.call("after", "info")):
            self.app.after_cancel(callback)
        self.app.update()

    def tearDown(self):
        self.app.destroy()

    def test_tabs_layout_and_long_diagnostics(self):
        app = self.app
        app.geometry("{}x{}".format(*app.minsize()))
        detail = "Hash mismatch: " + "a" * 64 + "\nCheck the binary.\n" * 12
        app.detail.set(detail)
        app.status.set("Downloading SRWZ-English-Best-v0.9.79-to-v0.9.83.xdelta")
        for tab in range(3):
            app.notebook.select(tab)
            app.update()
            self.assertEqual(app.detail_text.get("1.0", "end-1c"), detail)
            for widget in app.controls + [app.progress, app.status_label, app.detail_text, app.cancel_button, app.folder_button]:
                if not widget.winfo_ismapped():
                    continue
                self.assertGreater(widget.winfo_height(), 1)
                self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), app.winfo_rootx() + app.winfo_width())
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), app.winfo_rooty() + app.winfo_height())

    def test_stale_result_ignored_and_manual_mode_without_recognition(self):
        app = self.app
        app.job_id = 3
        app.events.put(("error", 2, ValueError("obsolete")))
        app.poll()
        self.assertNotEqual(app.detail.get(), "obsolete")
        app.notebook.select(1)
        app.update()
        self.assertEqual(str(app.apply_button["state"]), "normal")
        app.job_kind = "patch"
        app.set_busy(True)
        app.events.put(("error", 3, ValueError("Current failure")))
        app.poll()
        self.assertFalse(app.busy)
        self.assertEqual(app.detail.get(), "Current failure")

    def test_multiple_matches_require_selection(self):
        app = self.app
        node = next(iter(app.catalog.nodes.values()))
        app.events.put(("done", app.job_id, ("scan", [(Path("a.iso"), node), (Path("b.iso"), node)])))
        app.poll()
        self.assertIsNone(app.selection)
        self.assertEqual(str(app.apply_button["state"]), "disabled")
        app.file_box.current(0)
        app.select_found()
        self.assertIsNotNone(app.selection)

    def test_layout_at_150_and_200_percent_scaling(self):
        original_styles = Application.build_styles
        for dpi in (144, 192):
            self.app.destroy()
            def scaled_styles(app):
                app.tk.call("tk", "scaling", dpi / 72)
                original_styles(app)
            with patch.object(Application, "build_styles", scaled_styles):
                self.app = Application(startup=False)
            self.app.attributes("-alpha", 0)
            for tab in range(3):
                self.app.notebook.select(tab)
                self.app.update()
                for widget in self.app.controls + [self.app.cancel_button, self.app.detail_text]:
                    if widget.winfo_ismapped():
                        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), self.app.winfo_rootx() + self.app.winfo_width())
                        self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), self.app.winfo_rooty() + self.app.winfo_height())


if __name__ == "__main__":
    unittest.main()
