#
# Copyright (c) 2026, Oracle and/or its affiliates. All rights reserved.
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
#
# The Universal Permissive License (UPL), Version 1.0
#
# Subject to the condition set forth below, permission is hereby granted to any
# person obtaining a copy of this software, associated documentation and/or
# data (collectively, the "Software"), free of charge and under any and all
# copyright rights in the Software, and any and all patent rights owned or
# freely licensable by each licensor hereunder covering either (i) the
# unmodified Software as contributed to or provided by such licensor, or (ii)
# the Larger Works (as defined below) to which the Software is contributed by
# such licensors) to deal in both
#
# (a) the Software, and
#
# (b) any piece of software and/or hardware listed in the lrgrwrks.txt file if
# one is included with the Software (each a "Larger Work" to which the Software
# is contributed by such licensors),
#
# without restriction, including without limitation the rights to copy, create
# derivative works of, display, perform, and distribute the Software and make,
# use, sell, offer for sale, import, export, have made, and have sold the
# Software and the Larger Work(s), and to sublicense the foregoing rights on
# either these or other terms.
#
# This license is subject to the following condition: The above copyright
# notice and either this complete permission notice or at a minimum a reference
# to the UPL must be included in all copies or substantial portions of the
# Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
"""
Tests for the Tcl-level behavior of the cffi-based _tkinter implementation.
These tests only need a Tcl interpreter, no Tk windows, so they can run
unattended without a graphical session.
"""
import threading
import time
import unittest

try:
    import _tkinter
    import tkinter
except Exception:  # _tkinter may not be bootstrapped in this runtime
    _tkinter = None
    tkinter = None


def _have_tk():
    return _tkinter is not None


def _dispatch_events_until(app, condition, timeout=10.0):
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        _tkinter.dooneevent(_tkinter.DONT_WAIT)
        time.sleep(0.005)


class TkTclTest(unittest.TestCase):

    def setUp(self):
        if not _have_tk():
            self.skipTest("_tkinter not available")
        self.t = tkinter.Tcl()

    def tearDown(self):
        self.t = None

    def test_tclerror_exported(self):
        self.assertIs(tkinter.TclError, _tkinter.TclError)

    def test_eval_and_call(self):
        self.assertEqual(self.t.eval("expr 2 + 3"), "5")
        self.assertEqual(self.t.call("expr", "2", "+", "3"), 5)
        self.t.eval("proc double {x} { return [expr $x * 2] }")
        self.assertEqual(self.t.call("double", "21"), 42)

    def test_unicode_roundtrip(self):
        text = "héllo wörld 漢字 🎉"
        v = tkinter.StringVar(self.t, text)
        self.assertEqual(v.get(), text)
        # Tcl 8.6 counts UTF-16 code units, so an astral emoji counts as two
        utf16_len = len(text.encode("utf-16-be")) // 2
        self.assertEqual(self.t.call("string", "length", text), utf16_len)

    def test_embedded_nul_roundtrip(self):
        v = tkinter.StringVar(self.t)
        v.set("x\0y")
        self.assertEqual(v.get(), "x\0y")

    def test_timer_callbacks(self):
        fired = []
        self.t.after(30, lambda: fired.append("timer"))
        self.t.after(60, lambda a, b: fired.append((a, b)), "é", "漢字")
        _dispatch_events_until(self.t, lambda: len(fired) >= 2)
        self.assertIn("timer", fired)
        self.assertIn(("é", "漢字"), fired)

    def test_callback_exception_reported(self):
        def bad():
            raise ValueError("boom")
        self.t.createcommand("pybad", bad)
        with self.assertRaises(Exception):
            self.t.call("pybad")

    def test_worker_call_without_mainloop(self):
        res = {}

        def worker():
            try:
                self.t.call("expr", "1")
            except RuntimeError as e:
                res["err"] = str(e)
            except Exception as e:
                res["err"] = f"wrong: {type(e).__name__}"

        w = threading.Thread(target=worker)
        w.start()
        w.join(10)
        self.assertEqual(res.get("err"), "main thread is not in main loop")

    def test_worker_dispatch(self):
        app = self.t.tk
        self.t.eval("proc double {x} { return [expr $x * 2] }")

        results = {}
        done = threading.Event()

        def worker():
            try:
                results["call"] = self.t.call("double", "21")
                v = tkinter.StringVar(self.t, "from-worker-漢字")
                results["var"] = v.get()
                try:
                    self.t.call("nosuchcommand")
                except tkinter.TclError:
                    results["tclerror"] = True
            except Exception as e:
                results["error"] = f"{type(e).__name__}: {e}"
            finally:
                done.set()

        app.dispatching = True
        try:
            w = threading.Thread(target=worker)
            w.start()
            _dispatch_events_until(self.t, done.is_set)
            w.join(10)
        finally:
            app.dispatching = False
        self.assertNotIn("error", results)
        self.assertEqual(results.get("call"), 42)
        self.assertEqual(results.get("var"), "from-worker-漢字")
        self.assertIs(results.get("tclerror"), True)

    def test_worker_call_cancelled_when_dispatching_ends(self):
        app = self.t.tk
        results = {}

        def worker():
            try:
                results["r"] = self.t.call("expr", "1")
            except RuntimeError as e:
                results["r"] = "cancelled"

        app.dispatching = True
        try:
            w = threading.Thread(target=worker)
            w.start()
            time.sleep(0.05)
            app.dispatching = False
            app._cancel_pending_thread_calls()
            w.join(10)
        finally:
            app.dispatching = False
        self.assertEqual(results.get("r"), "cancelled")
