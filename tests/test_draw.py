import importlib.metadata
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "delivery-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import dv_draw  # noqa: E402


def have_dist(name: str) -> bool:
    try:
        importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


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


SPOKEN = (255, 255, 255)
UNSAID = (150, 166, 190)


@unittest.skipUnless(have_dist("Pillow"), "Pillow is required")
class SubtitleHighlightTests(unittest.TestCase):
    def render(self, text: str, spoken: int) -> "Image.Image":
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (dv_draw.W, dv_draw.H), (16, 24, 43))
        line = [{"char": char, "start_ms": index * 100, "end_ms": index * 100 + 90}
                for index, char in enumerate(text)]
        dv_draw.subtitle(ImageDraw.Draw(image), dv_draw.load_fonts(), line, "fullbleed", spoken)
        return image

    def column(self, image, color: tuple) -> list[int]:
        """Columns whose middle-of-line pixel is exactly `color` (a glyph core, not an edge)."""
        return [x for x in range(image.width)
                if image.getpixel((x, dv_draw.SUBTITLE_Y)) == color]

    def test_spoken_chars_are_lit_and_the_rest_wait_in_grey(self):
        image = self.render("打开页面点击保存", spoken=4)

        lit, unsaid = self.column(image, SPOKEN), self.column(image, UNSAID)
        self.assertTrue(lit and unsaid)
        self.assertLess(max(lit), min(unsaid))

    def test_nothing_is_lit_before_the_first_char_and_everything_after_the_last(self):
        self.assertEqual(self.column(self.render("打开页面", spoken=0), SPOKEN), [])
        self.assertEqual(self.column(self.render("打开页面", spoken=4), UNSAID), [])


if __name__ == "__main__":
    unittest.main()
