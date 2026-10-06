import copy
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from retro_trans.gui import Application
from retro_trans.catalog import Catalog
from retro_trans import z3_saves, __version__, chd
from retro_trans.ps3 import INSTALLATION_WARNING
from test_catalog import record, DATA
from test_z3_saves import inputs
from test_solutions import grouped_record, content, make_catalog
from retro_trans.catalog import scan_root
from retro_trans.solutions import SolutionPlan


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
        self.assertEqual(app.title(), 'Retro Trans ' + __version__)
        self.assertEqual([app.notebook.tab(tab, "text") for tab in app.notebook.tabs()], ["Automatic", "Apply xdelta", "Save conversion"])
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

    def test_mx_check_preserves_three_favorites_conversion_and_game_switch(self):
        from test_mx_converter import inputs as mx_inputs
        with tempfile.TemporaryDirectory() as temporary:
            root, app = Path(temporary), self.app
            ps2, psp = mx_inputs(root)
            app.notebook.select(2)
            app.save_game.set('MX (experimental)')
            app.save_ps3.set(str(ps2))
            app.save_vita.set(str(psp))
            app.save_output.set(str(root / 'converted'))
            app.save_direction.set('PSP → PS2')
            app.save_closed.set(True)
            app.apply()
            self.finish_worker()
            self.assertIn('experimental', app.detail.get())
            app.mx_experimental.set(True)
            app.apply()
            self.finish_worker()
            self.assertIsNotNone(app.save_checked, app.detail.get())
            self.assertIn('8,200', app.detail.get())
            self.assertIn('Nadesico: Prince of Darkness, Mobile Suit Zeta Gundam, Mobile Suit Gundam ZZ', app.detail.get())
            self.assertFalse(hasattr(app, 'mx_favorite'))
            checked = app.save_checked
            for variable in (app.mx_slot, app.mx_boot, app.mx_ppsspp, app.mx_psp_difficulty, app.mx_experimental):
                app.save_checked = checked
                variable.set(variable.get())
                self.assertIsNone(app.save_checked)
            app.save_checked = checked
            app.apply()
            self.finish_worker()
            self.assertEqual(app.status.get(), 'Completed.', app.detail.get())
            self.assertTrue((root / 'converted/psp-to-ps2/BISLPS-25345S01.psu').is_file())
            self.assertIn('still need testing', app.detail.get())
            app.save_game.set('Z3 Jigoku-hen')
            self.assertEqual(app.save_direction.get(), 'PS3 → Vita')
            self.assertEqual(app.save_ps3.get(), '')
            app.save_game.set('MX (experimental)')
            self.assertEqual(app.save_ps3.get(), str(ps2))
            self.assertFalse(app.save_closed.get())

    def test_mx_compact_layout_and_options(self):
        app = self.app
        app.notebook.select(2)
        app.save_game.set('MX (experimental)')
        app.update()
        for widget in app.controls:
            if widget.winfo_ismapped():
                self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), app.winfo_rootx() + app.winfo_width())
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), app.winfo_rooty() + app.winfo_height())
        app.mx_options()
        app.update()
        dialog = next(child for child in app.winfo_children() if child.winfo_class() == 'Toplevel')
        self.assertIn('experimental', dialog.title())
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        widgets = list(descendants(dialog))
        self.assertFalse(any(w.winfo_class() == 'TCombobox' for w in widgets))
        self.assertEqual(len([w for w in widgets if w.winfo_class() == 'TCheckbutton']), 2)
        entries = [w for w in widgets if w.winfo_class() == 'TEntry']
        self.assertEqual(len(entries), 3)
        self.assertTrue(all(not w.winfo_ismapped() for w in entries))
        toggle = next(w for w in widgets if w.winfo_class() == 'TButton' and str(w['text']).startswith('Show game files'))
        toggle.invoke()
        app.update()
        self.assertTrue(all(w.winfo_ismapped() for w in entries))
        toggle.invoke()
        app.update()
        self.assertTrue(all(not w.winfo_ismapped() for w in entries))
        dialog.destroy()
        app.set_busy(True)
        app.set_busy(False)  # Destroyed dialog widgets must not leak into controls.

    def test_mx_difficulty_checkbox_applies_to_ps2_output(self):
        from test_mx_converter import inputs as mx_inputs
        from retro_trans import mx_saves
        app, root = self.app, Path(self.storage.name)
        ps2, psp = mx_inputs(root)
        app.notebook.select(2)
        app.save_game.set('MX (experimental)')
        app.save_ps3.set(str(ps2))
        app.save_vita.set(str(psp))
        app.save_output.set(str(root / 'converted'))
        app.save_direction.set('PSP → PS2')
        app.save_closed.set(True)
        app.mx_experimental.set(True)
        self.assertTrue(app.mx_psp_difficulty.get())
        app.apply()
        self.finish_worker()
        self.assertEqual(app.save_checked['mappings'][0]['destination_balance'], 'psp')
        app.mx_psp_difficulty.set(False)
        self.assertIsNone(app.save_checked)
        app.apply()
        self.finish_worker()
        report = app.save_checked['mappings'][0]
        self.assertEqual(report['destination_balance'], 'original')
        self.assertTrue(report['difficulty_changed'])
        self.assertIn('difficulty: PSP → PS2 Original', app.detail.get())
        app.apply()
        self.finish_worker()
        payload = (root / 'converted/psp-to-ps2/BISLPS-25345S01/BISLPS-25345S01').read_bytes()
        self.assertEqual(mx_saves.inspect_balance(payload)['mode'], 'original')
        self.assertEqual(mx_saves.inspect_scenario(payload)['funds'], 8200)

    def test_mx_difficulty_checkbox_detects_ps2_source_without_invalidating_check(self):
        from test_mx_converter import inputs as mx_inputs
        from retro_trans import mx_saves
        app, root = self.app, Path(self.storage.name)
        ps2, psp = mx_inputs(root)
        source = ps2 / ps2.name
        app.notebook.select(2)
        app.save_game.set('MX (experimental)')
        app.save_ps3.set(str(ps2))
        app.save_vita.set(str(psp))
        app.save_output.set(str(root / 'converted'))
        app.save_closed.set(True)
        app.mx_experimental.set(True)
        app.mx_boot.set('owned-game.iso')
        app.mx_options()
        app.update()
        self.assertTrue(app.mx_difficulty_checkbox.instate(['disabled', 'alternate']))
        dialog = next(c for c in app.winfo_children() if c.winfo_class() == 'Toplevel')
        dialog.destroy()
        for mode in ('original', 'psp'):
            source.write_bytes(mx_saves.with_balance(source.read_bytes(), mode))
            app.invalidate_saves()
            with patch('retro_trans.mx_crypto.read_boot', return_value=b'owned-game'), \
                    patch('retro_trans.mx_crypto.music_defaults', return_value=bytes(157)):
                app.apply()
                self.finish_worker()
            self.assertIsNotNone(app.save_checked, app.detail.get())
            self.assertEqual(app.mx_psp_difficulty.get(), mode == 'psp')
            self.assertEqual(app.save_checked['mappings'][0]['source_balance'], mode)
            self.assertEqual(app.save_checked['mappings'][0]['destination_balance'], 'psp')
        app.save_direction.set('PSP → PS2')
        app.mx_psp_difficulty.set(False)
        app.save_direction.set('PS2 → PSP')
        app.save_direction.set('PSP → PS2')
        self.assertFalse(app.mx_psp_difficulty.get())  # Keep the user's output choice across direction changes.

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
            item = record()
            item['manifest']['patches'][0].update(source_format='iso', target_format='iso')
            app.catalog = make_catalog(item)
            app.found = [(source, chd.ChdSource())]
            app.file_box.configure(values=['game.chd'])
            app.file_box.current(0)
            def unpack(source, destination, *args):
                destination.mkdir()
                binary = destination / 'game.iso'
                binary.write_bytes(DATA['original'])
                return binary
            with patch('retro_trans.gui.inspect_chd', return_value=chd.Disc('dvd', 2048)), \
                    patch('retro_trans.gui.messagebox.askyesno', return_value=True) as ask, \
                    patch('retro_trans.gui.unpack_to_folder', side_effect=unpack) as extract:
                app.select_found()
                self.finish_worker()
            ask.assert_called_once()
            self.assertIn(str(root / 'game-unpacked'), ask.call_args.args[1])
            extract.assert_called_once()
            binary = root / 'game-unpacked/game.iso'
            self.assertEqual(app.selection[0], binary)
            self.assertEqual(app.apply_source.get(), str(binary))
            self.assertEqual(app.output_format.get(), 'CHD')
            self.assertEqual(Path(app.output.get()).suffix, '.chd')
            self.assertIn('extracted disc', app.detected.get())
            with patch.object(app, 'start') as start, patch('retro_trans.gui.apply_plan') as run, \
                    patch('retro_trans.gui.unpack_to_folder') as extract:
                app.apply()
                start.call_args.args[0](None, None)
                self.assertEqual(run.call_args.args[0], binary)
                extract.assert_not_called()
            app.output_format.set('Original format')
            app.change_output_format()
            self.assertEqual(Path(app.output.get()).suffix, '.' + app.plan.target.format)
            app.unpack_chd.set(False)
            with patch('retro_trans.gui.filedialog.askopenfilename', return_value=str(source)):
                app.pick_path(app.apply_source)
            app.manual_chd_mode()
            self.assertEqual(app.manual_format.get(), 'Original format')
            self.assertEqual(Path(app.apply_output.get()).suffix, '.chd')

    def test_chd_decline_and_multiple_candidates_never_unpack(self):
        app, root = self.app, Path(self.storage.name)
        source = root / 'disc.chd'
        source.write_bytes(b'MComprHD')
        app.events.put(('done', app.job_id, ('scan', [(source, chd.ChdSource()), (root / 'other.chd', chd.ChdSource())])))
        with patch('retro_trans.gui.inspect_chd', return_value=chd.Disc('dvd', 2048)), \
                patch('retro_trans.gui.messagebox.askyesno', return_value=False) as ask, \
                patch('retro_trans.gui.unpack_to_folder') as extract:
            app.poll()
            ask.assert_not_called()
            app.file_box.current(0)
            app.select_found()
            ask.assert_called_once()
            self.assertIsNone(app.selection)
            self.assertEqual(str(app.apply_button['state']), 'disabled')
            self.assertIn('not started', app.status.get())
            app.events.put(('done', app.job_id, ('scan', [(source, chd.ChdSource())])))
            app.poll()
            self.assertEqual(ask.call_count, 1)  # A catalog refresh cannot repeat a declined startup prompt.
            extract.assert_not_called()
            self.assertFalse((root / 'disc-unpacked').exists())

    def test_manual_chd_unpacks_then_waits_for_another_patch_click(self):
        app, root = self.app, Path(self.storage.name)
        source = root / 'disc.chd'
        source.write_bytes(b'MComprHD')
        binary = root / 'disc-unpacked/disc.iso'
        def unpack(*args):
            binary.parent.mkdir()
            binary.write_bytes(bytes(2048))
            return binary
        app.notebook.select(1)
        app.apply_source.set(str(source))
        app.apply_delta.set('local.xdelta')
        app.apply_output.set(str(root / 'custom-output.iso'))
        with patch('retro_trans.gui.inspect_chd', return_value=chd.Disc('dvd', 2048)), \
                patch('retro_trans.gui.messagebox.askyesno', return_value=True), \
                patch('retro_trans.gui.unpack_to_folder', side_effect=unpack) as extract, \
                patch('retro_trans.gui.manual_patch', return_value='verified') as run:
            app.apply()
            self.finish_worker()
            run.assert_not_called()
            self.assertEqual(app.apply_source.get(), str(binary))
            self.assertEqual(app.apply_output.get(), str(root / 'custom-output.iso'))
            app.apply()
            self.finish_worker()
            extract.assert_called_once()
            self.assertEqual(run.call_args.args[0], str(binary))

    def test_unrecognized_extraction_stays_selected_for_catalog_refresh(self):
        app, root = self.app, Path(self.storage.name)
        binary = root / 'unpacked.iso'
        binary.write_bytes(b'Unknown disc')
        app.events.put(('done', app.job_id, ('unpack_auto', (root / 'disc.chd', binary))))
        app.poll()
        self.finish_worker()
        self.assertIsNone(app.selection)
        self.assertEqual(app.file_label.get(), str(binary))
        self.assertIn(str(binary), app.detail.get())
        data = copy.deepcopy(app.catalog.data)
        data['releases'][0]['manifest']['game_name'] += ' updated'
        app.events.put(('catalog', None, Catalog(data)))
        with patch.object(app, 'identify_source') as identify, patch.object(app, 'scan') as scan:
            app.poll()
            identify.assert_called_once_with(str(binary))
            scan.assert_not_called()
        app.cancel.set()
        app.events.put(('done', app.job_id, ('unpack_auto', (root / 'disc.chd', binary))))
        with patch.object(app, 'identify_source') as identify:
            app.poll()
            identify.assert_not_called()
            self.assertIn('identification cancelled', app.detected.get())

    def test_ps3_warning_for_automatic_manual_and_grouped_patches(self):
        app, root = self.app, Path(self.storage.name)
        source = root / 'source.iso'
        source.write_bytes(DATA['original'])
        for platform in ('PS3', 'PS2'):
            item = record()
            item['manifest']['platform'] = platform
            app.catalog = make_catalog(item)
            node = next(n for n in app.catalog.nodes.values() if n.version == 'original')
            app.selection, app.plan = (source, node), app.catalog.plan(node)
            app.output.set(str(root / 'output.iso'))
            with patch('retro_trans.gui.messagebox.showwarning') as warning, patch.object(app, 'start') as start, \
                    patch('retro_trans.gui.apply_plan'):
                app.apply()
                result, message = start.call_args.args[0](None, None)
                self.assertEqual(warning.call_count, int(platform == 'PS3'))
                self.assertEqual(INSTALLATION_WARNING in message, platform == 'PS3')
        # A complete multi-file PS3 solution uses its component platform metadata.
        item = grouped_record()
        item['manifest']['platform'] = 'PlayStation 3'
        for track in (3, 17):
            (root / ('track' + str(track) + '.bin')).write_bytes(content(track, 'original'))
        app.catalog = make_catalog(item)
        app.selection = scan_root(root, app.catalog)[0]
        app.plan = app.catalog.plan(app.selection[1])
        with patch('retro_trans.gui.messagebox.showwarning') as warning, patch.object(app, 'start'):
            app.apply()
            warning.assert_called_once()
        # Manual disc identification is a bounded header read, with no full hash.
        image = bytearray(17 * 2048)
        image[32768:32775] = b'\x01CD001\x01'
        image[32808:32840] = b'PS3VOLUME'.ljust(32, b' ')
        source.write_bytes(image)
        app.notebook.select(1)
        app.apply_source.set(str(source))
        app.apply_delta.set('local.xdelta')
        app.apply_output.set(str(root / 'patched.iso'))
        with patch('retro_trans.gui.messagebox.showwarning') as warning, patch.object(app, 'start'):
            app.apply()
            app.apply()
            self.assertEqual(warning.call_count, 2)

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

    def test_grouped_folder_selection_route_and_patch_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, app = Path(temporary).resolve(), self.app
            for track in (3, 17):
                (root / 'renamed{}.bin'.format(track)).write_bytes(content(track, 'original'))
            app.catalog = make_catalog(grouped_record())
            with patch('retro_trans.gui.filedialog.askdirectory', return_value=temporary):
                app.choose_folder()
            self.finish_worker()
            self.assertIsInstance(app.plan, SolutionPlan)
            self.assertEqual(app.selection[0], root)
            self.assertEqual(len(app.found), 1)
            self.assertEqual(str(app.apply_button['state']), 'normal')
            self.assertEqual(app.output_format_box['values'], ('Original format',))
            self.assertEqual(app.auto_output_label['text'], 'New folder:')
            self.assertEqual(Path(app.output.get()), root / 'japan-disc-v1.1')
            app.change_output_format()
            self.assertEqual(Path(app.output.get()), root / 'japan-disc-v1.1')
            with patch.object(app, 'start') as start, patch('retro_trans.gui.apply_plan') as run:
                app.apply()
                work = start.call_args.args[0]
                result, message = work(None, None)
                self.assertIsInstance(run.call_args.args[2], SolutionPlan)
                self.assertFalse(run.call_args.kwargs['chd_output'])
                self.assertIn('Complete patch solution', message)
            # Browse to either member also selects its complete containing set.
            with patch('retro_trans.gui.filedialog.askopenfilename', return_value=str(root / 'renamed3.bin')):
                app.choose_source()
            self.finish_worker()
            self.assertEqual(app.selection[0], root)
            (root / 'renamed17.bin').unlink()
            app.events.put(('done', app.job_id, ('identify', scan_root(root, app.catalog))))
            app.poll()
            self.assertIsNone(app.plan)
            self.assertEqual(str(app.apply_button['state']), 'disabled')
            self.assertIn('incomplete', app.route.get())

    def test_many_missing_companion_files_keep_compact_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, app = Path(temporary).resolve(), self.app
            for track in (3, 17):
                (root / 'track{}.bin'.format(track)).write_bytes(content(track, 'original'))
            record = grouped_record()
            record['manifest']['solutions'][0]['copy_files'] = [
                dict(name='Missing disc track {:02d}.bin'.format(i), bytes=123, sha256='a' * 64) for i in range(15)]
            app.catalog = make_catalog(record)
            app.events.put(('done', app.job_id, ('identify', scan_root(root, app.catalog))))
            app.poll()
            app.update()
            self.assertIsNone(app.plan)
            self.assertIn('Missing disc track 14.bin', app.detail.get())
            self.assertLess(len(app.route.get()), 100)
            self.assertLessEqual(app.cancel_button.winfo_rooty() + app.cancel_button.winfo_height(),
                                 app.winfo_rooty() + app.winfo_height())

    def test_cue_without_group_metadata_shows_error_and_refresh_can_recognize_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, app = Path(temporary).resolve(), self.app
            cue = root / 'disc.cue'
            cue.write_bytes(b'descriptor')
            for track in (3, 17):
                (root / 'track{}.bin'.format(track)).write_bytes(content(track, 'original'))
            legacy = grouped_record()
            legacy['manifest']['schema_version'] = 1
            del legacy['manifest']['solutions']
            app.catalog = make_catalog(legacy)
            with patch('retro_trans.gui.filedialog.askopenfilename', return_value=str(cue)):
                app.choose_source()
            self.finish_worker()
            self.assertIn('Refresh catalog', app.detail.get())
            self.assertNotEqual(app.detected.get(), 'Identifying…')
            self.assertIsNone(app.plan)
            self.assertEqual(str(app.apply_button['state']), 'disabled')
            app.catalog = make_catalog(grouped_record())
            with patch('retro_trans.gui.filedialog.askopenfilename', return_value=str(cue)):
                app.choose_source()
            self.finish_worker()
            self.assertIsInstance(app.plan, SolutionPlan)
            self.assertEqual(app.selection[0], root)
            self.assertEqual(len(app.plan.edges), 2)


if __name__ == "__main__":
    unittest.main()
