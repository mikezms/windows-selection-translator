import unittest

from bilingual_layout import build_bilingual_pairs


class BilingualLayoutTests(unittest.TestCase):
    def test_pairs_sentences_when_boundaries_match(self):
        source = "First sentence. Second sentence! Third sentence?"
        target = "第一句。第二句！第三句？"

        pairs = build_bilingual_pairs(source, target)

        self.assertEqual(3, len(pairs))
        self.assertEqual(["句子", "句子", "句子"], [pair.unit for pair in pairs])
        self.assertEqual("Second sentence!", pairs[1].original)
        self.assertEqual("第二句！", pairs[1].translated)

    def test_falls_back_to_whole_paragraph_when_sentence_counts_differ(self):
        source = "First sentence. Second sentence."
        target = "这是合并后的完整译文。"

        pairs = build_bilingual_pairs(source, target)

        self.assertEqual(1, len(pairs))
        self.assertEqual("段落", pairs[0].unit)
        self.assertEqual(source, pairs[0].original)
        self.assertEqual(target, pairs[0].translated)

    def test_preserves_paragraph_groups(self):
        source = "One. Two.\n\nA final paragraph."
        target = "一。二。\n\n最后一段。"

        pairs = build_bilingual_pairs(source, target)

        self.assertEqual(["句子", "句子", "段落"], [pair.unit for pair in pairs])
        self.assertEqual("A final paragraph.", pairs[-1].original)

    def test_falls_back_to_whole_text_when_paragraph_counts_differ(self):
        source = "First paragraph.\n\nSecond paragraph."
        target = "合并后的完整译文。"

        pairs = build_bilingual_pairs(source, target)

        self.assertEqual(1, len(pairs))
        self.assertEqual("全文", pairs[0].unit)
        self.assertEqual(source, pairs[0].original)
        self.assertEqual(target, pairs[0].translated)


if __name__ == "__main__":
    unittest.main()
