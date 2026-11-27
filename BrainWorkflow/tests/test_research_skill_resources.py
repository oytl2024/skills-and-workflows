from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from wqb.research_skill_resources import query_skill


class ResearchSkillResourcesTests(unittest.TestCase):
    def test_only_skill_and_report_markdown_are_readable(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / 'skills/brain-research'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('Economic methods', encoding='utf-8')
            result = query_skill(root, dict(path='skills/brain-research/SKILL.md', start=0, length=8))
            self.assertEqual(result['text'], 'Economic')
            self.assertEqual(result['next_start'], 8)
            self.assertEqual(result['authority'], 'research_guidance_not_platform_proof')
            for path in ('raw/x.md', 'machine/x.json', 'wiki/x.md', '../AGENTS.md', '/secret.md'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    query_skill(root, dict(path=path))

    def test_discovery_is_bounded_and_does_not_read_other_directories(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'skills/brain-research').mkdir(parents=True)
            for name in ('SKILL.md', 'notes.md'):
                (root / 'skills/brain-research' / name).write_text('methods', encoding='utf-8')
            (root / 'skills/brain-research/private.json').write_text('{}', encoding='utf-8')
            result = query_skill(root, dict(limit=1))
            self.assertEqual(len(result['items']), 1)
            self.assertEqual(result['next_offset'], 1)
            with self.assertRaises(ValueError):
                query_skill(root, dict(path='skills/brain-research/SKILL.md', length=True))


if __name__ == '__main__':
    unittest.main()
