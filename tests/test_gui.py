import copy
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from retro_trans.gui import Application
from retro_trans.catalog import Catalog
from retro_trans import z3_saves
from test_z3_saves import inputs


@unittest.skipUnless(os.name == "nt", "Native Windows UI test")
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'LOCALAPPDATA': self.storage.name})
        self.environment.start()
        self.app = Application(startup=False)
        self.app.attributes("-alpha", 0)
        for callback in self.app.tk.splitlist(self.app.tk.call("after", "info")):
            self.app.after_cancel(callback)
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.environment.stop()
        self.storage.cleanup()

    def test_tabs_layout_and_long_diagnostics(self):
        app = self.app
        self.assertEqual([app.notebook.tab(tab, "text") for tab in app.notebook.tabs()], ["Automatic", "Apply xdelta", "Z3 saves"])
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

    def test_unchanged_catalog_does_not_repeat_identification(self):
        app = self.app
        fresh = Catalog(copy.deepcopy(app.catalog.data))
        node = next(iter(app.catalog.nodes.values()))
        for selection in (None, (Path("large.iso"), node)):
            app.selection = selection
            app.busy = True
            app.events.put(("catalog", None, fresh))
            with patch.object(app, "scan") as scan, patch.object(app, "start") as start:
                app.poll()
                app.busy = False
                app.poll()
                scan.assert_not_called()
                start.assert_not_called()
                self.assertIsNone(app.pending_catalog)

    def test_changed_catalog_still_rechecks_selected_file(self):
        app = self.app
        data = copy.deepcopy(app.catalog.data)
        data["releases"][0]["manifest"]["game_name"] += " updated"
        app.selection = (Path("large.iso"), next(iter(app.catalog.nodes.values())))
        app.events.put(("catalog", None, Catalog(data)))
        with patch.object(app, "start") as start:
            app.poll()
            start.assert_called_once()
            self.assertEqual(start.call_args.args[1], "identify")

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

    def finish_worker(self):
        deadline = time.monotonic() + 15
        while self.app.busy and time.monotonic() < deadline:
            self.app.update()
            self.app.poll()
            time.sleep(.01)
        self.assertFalse(self.app.busy, 'Save worker timed out')

    def select_saves(self, root):
        ps3, vita = inputs(root)
        app = self.app
        app.notebook.select(2)
        app.save_ps3.set(str(ps3))
        app.save_vita.set(str(vita))
        app.save_output.set(str(root / 'converted'))
        app.save_direction.set('Both directions')
        app.update()
        return ps3, vita

    def test_save_check_convert_offline_and_folder_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, app = Path(temporary), self.app
            ps3, vita = self.select_saves(root)
            before = z3_saves.source_blobs(z3_saves.load_ps3(ps3), z3_saves.load_vita(vita))
            self.assertEqual(str(app.apply_button['state']), 'disabled')
            app.apply()  # Return cannot bypass the closed-emulator gate.
            self.assertFalse(app.busy)
            app.save_closed.set(True)
            self.assertEqual(app.apply_button['text'], 'Check saves')
            app.apply()
            self.finish_worker()
            self.assertIsNotNone(app.save_checked, app.detail.get())
            self.assertFalse((root / 'converted').exists())
            self.assertEqual(app.apply_button['text'], 'Convert saves')
            app.apply()
            self.finish_worker()
            self.assertEqual(app.status.get(), 'Completed.', app.detail.get())
            self.assertTrue((root / 'converted/rpcs3-to-vita3k.zip').is_file())
            self.assertTrue((root / 'converted/vita3k-to-rpcs3.zip').is_file())
            self.assertEqual(z3_saves.source_blobs(z3_saves.load_ps3(ps3), z3_saves.load_vita(vita)), before)
            self.assertEqual(app.apply_button['text'], 'Check saves')
            self.assertNotEqual(app.save_output.get(), str(root / 'converted'))
            with patch('retro_trans.gui.os.startfile') as open_folder:
                app.open_folder()
                open_folder.assert_called_once_with(str(root / 'converted'))

    def test_save_checks_invalidated_by_changed_inputs_and_direction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, app = Path(temporary), self.app
            ps3, vita = self.select_saves(root)
            app.save_closed.set(True)
            app.apply()
            self.finish_worker()
            checked = app.save_checked
            self.assertIsNotNone(checked)
            for variable in (app.save_ps3, app.save_vita, app.save_output, app.save_direction, app.save_closed):
                app.save_checked = checked
                variable.set(variable.get())
                self.assertIsNone(app.save_checked)
            app.save_checked = checked
            (ps3 / 'NPJB00520-SYS/ICON0.PNG').write_bytes(b'changed')
            app.apply()
            self.finish_worker()
            self.assertIn('changed since checking', app.detail.get())
            self.assertFalse((root / 'converted').exists())
            self.assertEqual(app.apply_button['text'], 'Check saves')

    def test_save_browse_and_invalid_folder_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, app = Path(temporary), self.app
            app.notebook.select(2)
            with patch('retro_trans.gui.filedialog.askdirectory', return_value=temporary):
                app.pick_save_folder(app.save_ps3)
                app.pick_save_folder(app.save_vita)
                app.pick_save_folder(app.save_output, output=True)
            self.assertEqual(Path(app.save_output.get()).parent, root)
            self.assertFalse(Path(app.save_output.get()).exists())
            (root / 'empty').mkdir()
            app.save_ps3.set(str(root / 'empty'))
            app.save_vita.set(str(root / 'missing'))
            app.save_closed.set(True)
            app.apply()
            self.finish_worker()
            self.assertIn('system and manual save', app.detail.get())
            self.assertIsNone(app.save_checked)

    def test_catalog_refresh_waits_while_using_save_tab(self):
        app = self.app
        app.notebook.select(2)
        data = copy.deepcopy(app.catalog.data)
        data['releases'][0]['manifest']['game_name'] += ' updated'
        fresh = Catalog(data)
        app.selection = (Path('large.iso'), next(iter(app.catalog.nodes.values())))
        app.events.put(('catalog', None, fresh))
        with patch.object(app, 'start') as start:
            app.poll()
            self.assertIs(app.pending_catalog, fresh)
            start.assert_not_called()
            app.notebook.select(0)
            app.poll()
            start.assert_called_once()

    def test_chd_output_defaults_and_format_switching(self):
        with tempfile.TemporaryDirectory() as temporary:
            app, root = self.app, Path(temporary)
            source = root / 'game.chd'
            source.write_bytes(b'MComprHD')
            node = next(n for n in app.catalog.nodes.values() if n.version == 'original')
            app.found = [(source, node)]
            app.file_box.configure(values=['game.chd'])
            app.file_box.current(0)
            app.select_found()
            self.assertEqual(app.output_format.get(), 'CHD')
            self.assertEqual(Path(app.output.get()).suffix, '.chd')
            self.assertIn('verified on Patch', app.detected.get())
            app.output_format.set('Original format')
            app.change_output_format()
            self.assertEqual(Path(app.output.get()).suffix, '.' + app.plan.target.format)
            with patch('retro_trans.gui.filedialog.askopenfilename', return_value=str(source)):
                app.pick_path(app.apply_source)
            self.assertEqual(app.manual_format.get(), 'CHD')
            app.unpack_chd.set(False)
            app.manual_chd_mode()
            self.assertEqual(app.manual_format.get(), 'Original format')
            self.assertEqual(Path(app.apply_output.get()).suffix, '.chd')

    def test_manual_chd_controls_reach_worker(self):
        app = self.app
        app.notebook.select(1)
        app.apply_source.set('source.chd')
        app.apply_delta.set('patch.xdelta')
        app.apply_output.set('patched.chd')
        app.manual_format.set('CHD')
        with patch.object(app, 'start') as start, patch('retro_trans.gui.manual_patch', return_value='verified-disc-hash') as run:
            app.apply()
            work = start.call_args.args[0]
            output, message = work(None, None)
            self.assertTrue(run.call_args.kwargs['unpack_chd'])
            self.assertTrue(run.call_args.kwargs['chd_output'])
            self.assertIn('Patched disc SHA-256', message)


if __name__ == "__main__":
    unittest.main()
