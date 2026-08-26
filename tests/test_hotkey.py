import unittest
from unittest import mock

import hotkey


class HotkeyTests(unittest.TestCase):
    def test_clean_text_preserves_paragraphs(self):
        raw = " First line\r\nwrapped line.\r\n\r\n Second paragraph. "

        self.assertEqual(
            "First line wrapped line.\n\nSecond paragraph.",
            hotkey.clean_text(raw),
        )

    def test_wait_for_clipboard_change_accepts_same_copied_text(self):
        with (
            mock.patch.object(hotkey, "_clipboard_sequence_number", return_value=11),
            mock.patch.object(hotkey, "_clipboard_text", return_value="same text"),
        ):
            copied = hotkey._wait_for_clipboard_change(10)

        self.assertEqual("same text", copied)

    def test_copy_retries_ctrl_c_before_ctrl_insert(self):
        with (
            mock.patch.object(hotkey, "_wait_hotkey_released", return_value=True),
            mock.patch.object(
                hotkey,
                "_copy_selection_once",
                side_effect=("", "selected text"),
            ) as copy_once,
            mock.patch.object(hotkey.time, "sleep"),
        ):
            copied = hotkey.copy_selected_text("alt+t")

        self.assertEqual("selected text", copied)
        self.assertEqual(
            [mock.call(use_insert=False), mock.call(use_insert=False)],
            copy_once.call_args_list,
        )

    def test_copy_stops_when_hotkey_is_still_pressed(self):
        with (
            mock.patch.object(hotkey, "_wait_hotkey_released", return_value=False),
            mock.patch.object(hotkey, "_copy_selection_once") as copy_once,
        ):
            copied = hotkey.copy_selected_text("alt+t")

        self.assertEqual("", copied)
        copy_once.assert_not_called()


if __name__ == "__main__":
    unittest.main()
