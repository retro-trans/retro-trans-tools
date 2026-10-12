import ctypes
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from retro_trans import vita_io as v, vita_pkg, vita_repatch
from retro_trans.core import Cancelled, PatchError


def locked():
    error = PermissionError('test sharing violation')
    error.winerror = 32
    return error


class VitaIoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_transient_lock_retries_and_unrelated_error_fails_immediately(self):
        from unittest.mock import Mock
        operation = Mock(side_effect=[locked(), 'released'])
        with patch.object(v.time,'sleep'):
            self.assertEqual(v.sharing_retry(operation), 'released')
        self.assertEqual(operation.call_count,2)
        operation = Mock(side_effect=PermissionError('ordinary permission failure'))
        with self.assertRaises(PermissionError): v.sharing_retry(operation)
        self.assertEqual(operation.call_count,1)

    def test_timeout_and_cancellation_are_bounded(self):
        with self.assertRaises(PermissionError): v.sharing_retry(lambda: (_ for _ in ()).throw(locked()),timeout=0)
        cancel = threading.Event()
        def operation():
            cancel.set(); raise locked()
        with patch.object(v.time,'sleep'),self.assertRaises(Cancelled):
            v.sharing_retry(operation,cancel)

    def test_original_exception_survives_failed_cleanup(self):
        original = PatchError('original verification failure')
        def fail_cleanup(operation,**options):
            operation.__self__._finalizer.detach()
            raise locked()
        with patch.object(v,'sharing_retry',side_effect=fail_cleanup):
            with self.assertRaises(PatchError) as caught:
                with v.temporary_workspace(self.root): raise original
        self.assertIs(caught.exception,original)

    def test_success_then_failed_cleanup_explains_output_is_verified(self):
        def fail_cleanup(operation,**options):
            operation.__self__._finalizer.detach()
            raise locked()
        with patch.object(v,'sharing_retry',side_effect=fail_cleanup):
            with self.assertRaisesRegex(PatchError, 'saved and verified'):
                with v.temporary_workspace(self.root): pass

    def test_file_verification_retries_read_lock_and_preserves_hash_failure(self):
        source = self.root/'asset.bin';source.write_bytes(b'abcd')
        identity = dict(bytes=4,sha256='0'*64)
        with patch.object(vita_repatch,'sha256_file',side_effect=[locked(),'0'*64]) as hashing:
            with patch.object(v.time,'sleep'): vita_repatch.verify(source,identity)
        self.assertEqual(hashing.call_count,2)
        with patch.object(vita_repatch,'sha256_file',return_value='1'*64) as hashing:
            with self.assertRaises(PatchError): vita_repatch.verify(source,identity)
        self.assertEqual(hashing.call_count,1)

    @unittest.skipUnless(os.name == 'nt','Windows sharing violations')
    def test_actual_windows_lock_is_released_during_workspace_cleanup(self):
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                           wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        finished = threading.Event()
        thread = None
        with v.temporary_workspace(self.root) as root:
            target = root/'engine/portable/fs/ux0/app/PCSG00597/cpk/Ange.cpk'
            target.parent.mkdir(parents=True);target.write_bytes(b'locked game fixture')
            handle = create(str(target),0x80000000,1,None,3,0x80,None)
            self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
            def release():
                finished.wait(0.5)
                kernel.CloseHandle(handle)
            thread = threading.Thread(target=release);thread.start()
        finished.set();thread.join()
        self.assertFalse(root.exists())
        self.assertTrue(self.root.exists())
