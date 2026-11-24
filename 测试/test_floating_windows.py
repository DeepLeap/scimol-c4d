"""Pure Python checks for the guarded Win32 floating-dialog follower."""

import os
import time
import unittest
from unittest.mock import Mock, patch

from scimol_c4d.floating_windows import (
    GAP, Rect, Window, WindowFollower, Win32Windows, choose_window, editor_open_position,
    follower_position,
)


class Dialog:
    def __init__(self, x, y):
        self.point = {"x": x, "y": y}

    def Local2Screen(self):
        return self.point


class Native:
    def __init__(self, parent, child=None, work=Rect(0, 0, 2400, 1400)):
        self.items = {item.hwnd: item for item in (parent, child) if item}
        self.work = work
        self.moves = []

    def windows(self, pid):
        return list(self.items.values())

    def window(self, hwnd):
        return self.items.get(hwnd)

    def workarea(self, hwnd):
        return self.work

    def move(self, hwnd, x, y):
        self.moves.append((hwnd, x, y))
        item = self.items[hwnd]
        self.items[hwnd] = Window(item.hwnd, item.pid, item.title,
                                  Rect(x, y, x + item.frame.width, y + item.frame.height),
                                  (x + 8, y + 30), item.class_name)
        return True


def window(hwnd, title, frame, pid=None):
    pid = os.getpid() if pid is None else pid
    return Window(hwnd, pid, title, frame, (frame.left + 8, frame.top + 30), "QDialog")


class FloatingWindowsTests(unittest.TestCase):
    def setUp(self):
        self.parent = window(100, "分子资源库", Rect(200, 100, 900, 820))
        self.child = window(101, "结构详情", Rect(906, 100, 1426, 780))

    def test_position_follows_right_edge_and_child_keeps_own_size(self):
        work = Rect(0, 0, 2400, 1400)
        self.assertEqual(follower_position(self.parent.frame, self.child.frame, work), (906, 100))
        wider = Rect(200, 100, 1020, 820)
        resized_child = Rect(906, 100, 1566, 800)
        self.assertEqual(follower_position(wider, resized_child, work), (1026, 100))
        self.assertEqual(GAP, 6)

    def test_small_monitor_prefers_left_then_keeps_grab_area(self):
        self.assertEqual(follower_position(Rect(700, 20, 1100, 700),
                                           Rect(0, 0, 400, 500), Rect(0, 0, 1200, 800)),
                         (294, 20))
        x, y = follower_position(Rect(100, 50, 550, 700), Rect(0, 0, 700, 900),
                                  Rect(0, 0, 600, 500))
        self.assertGreaterEqual(x + 700, 80)
        self.assertLessEqual(x, 520)
        self.assertEqual(y, 0)

    def test_window_selection_requires_pid_title_anchor_and_floating_size(self):
        work = Rect(0, 0, 2400, 1400)
        anchor = self.parent.client_origin
        self.assertEqual(choose_window([self.parent], anchor, os.getpid(), self.parent.title, work), self.parent)
        self.assertIsNone(choose_window([self.parent], anchor, os.getpid() + 1, self.parent.title, work))
        self.assertIsNone(choose_window([self.parent], (1200, 1000), os.getpid(), self.parent.title, work))
        self.assertIsNone(choose_window([self.parent], anchor, os.getpid(), "other", work))
        main = window(9, self.parent.title, Rect(0, 0, 2200, 1300))
        self.assertIsNone(choose_window([main], main.client_origin, os.getpid(), main.title, work))
        self.assertIsNone(choose_window([self.parent, self.parent], anchor, os.getpid(), self.parent.title, work))

    def test_open_position_uses_sdk_anchor_and_rejects_docked_main_window(self):
        native = Native(self.parent)
        self.assertEqual(editor_open_position(Dialog(*self.parent.client_origin), native=native), (906, 100))
        native.items = {9: window(9, "分子资源库", Rect(0, 0, 2200, 1300))}
        self.assertIsNone(editor_open_position(Dialog(8, 30), native=native))

    def test_unavailable_win32_or_sdk_anchor_falls_back_cleanly(self):
        with patch("scimol_c4d.floating_windows.Win32Windows", side_effect=OSError("unavailable")):
            self.assertIsNone(editor_open_position(Dialog(8, 30)))
            follower = WindowFollower()
            self.assertFalse(follower.start(Dialog(8, 30), Dialog(914, 130)))
            self.assertFalse(follower.is_running)
        native = Native(self.parent, self.child)
        self.assertIsNone(editor_open_position(Dialog(None, None), native=native))
        self.assertFalse(WindowFollower(native).start(Dialog(None, None), Dialog(914, 130)))

    def test_default_poll_interval_and_running_state(self):
        native = Native(self.parent, self.child)
        follower = WindowFollower(native)
        self.assertEqual(follower.interval, 0.03)
        self.assertEqual(WindowFollower(native, interval=0.001).interval, 0.02)
        self.assertFalse(follower.is_running)
        self.assertTrue(follower.start(Dialog(*self.parent.client_origin), Dialog(*self.child.client_origin)))
        self.assertTrue(follower.is_running)
        follower.stop()
        self.assertFalse(follower.is_running)

    def test_minimized_parent_stops_without_moving_child(self):
        native = Native(self.parent, self.child)
        follower = WindowFollower(native, interval=0.02)
        self.assertTrue(follower.start(Dialog(*self.parent.client_origin), Dialog(*self.child.client_origin)))
        try:
            # Win32Windows.window returns None for an iconic HWND.
            native.items.pop(self.parent.hwnd)
            deadline = time.monotonic() + 1
            while follower.is_running and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(follower.is_running)
            self.assertEqual(native.moves, [])
        finally:
            follower.stop()

    def test_win32_rejects_iconic_window_before_reading_geometry(self):
        native = object.__new__(Win32Windows)
        native.user32 = Mock()
        native.user32.IsWindow.return_value = True
        native.user32.IsWindowVisible.return_value = True
        native.user32.IsIconic.return_value = True
        self.assertIsNone(native.window(100))
        native.user32.GetAncestor.assert_not_called()

    def test_follower_moves_only_child_when_parent_moves_or_resizes(self):
        native = Native(self.parent, self.child)
        follower = WindowFollower(native, interval=0.08)
        self.assertTrue(follower.start(Dialog(*self.parent.client_origin), Dialog(*self.child.client_origin)))
        try:
            native.items[100] = window(100, "分子资源库", Rect(300, 150, 1100, 870))
            deadline = time.monotonic() + 1
            while len(native.moves) == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(native.moves, [(101, 1106, 150)])
            time.sleep(0.22)
            self.assertEqual(len(native.moves), 1)
            native.items.pop(101)
            time.sleep(0.12)
            self.assertEqual(len(native.moves), 1)
        finally:
            follower.stop()

    def test_same_native_window_and_wrong_pid_are_rejected(self):
        native = Native(self.parent)
        follower = WindowFollower(native)
        self.assertFalse(follower.start(Dialog(*self.parent.client_origin),
                                        Dialog(*self.parent.client_origin),
                                        editor_title=self.parent.title))
        self.assertEqual(native.moves, [])
        native.items[101] = window(101, "结构详情", self.child.frame, pid=os.getpid() + 1)
        self.assertFalse(follower.start(Dialog(*self.parent.client_origin),
                                        Dialog(*self.child.client_origin)))


if __name__ == "__main__":
    unittest.main()
