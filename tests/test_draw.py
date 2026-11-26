import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "delivery-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import dv_draw  # noqa: E402


class MonospaceStub:
    """One unit of width per character, so tests need no font."""

    def getlength(self, text: str) -> float:
        return float(len(text))


def wrap(text: str, width: int = 10) -> list[str]:
    return dv_draw.wrap_text(text, MonospaceStub(), width)


class WrapTextTests(unittest.TestCase):
    def test_lines_break_at_the_width_and_lose_nothing(self):
        self.assertEqual(wrap("一二三四五六七八九十十一十二"), ["一二三四五六七八九十", "十一十二"])
        self.assertEqual(wrap("短"), ["短"])

    def test_punctuation_never_opens_a_line(self):
        self.assertEqual(wrap("一二三四五六七八九十、十一"), ["一二三四五六七八九十、", "十一"])
        self.assertEqual(wrap("一二三四五六七八九十。"), ["一二三四五六七八九十。"])

    def test_an_opening_bracket_never_ends_a_line(self):
        self.assertEqual(wrap("一二三四五六七八九（十一）"), ["一二三四五六七八九", "（十一）"])

    def test_latin_words_stay_whole(self):
        self.assertEqual(wrap("订单 OrderDetail 页面", 8), ["订单", "OrderDetail", "页面"])

    def test_a_word_wider_than_a_line_overflows_instead_of_vanishing(self):
        self.assertEqual(wrap("OrderDetail 页面", 6), ["OrderDetail", "页面"])


if __name__ == "__main__":
    unittest.main()
