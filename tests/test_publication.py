"""Publication policy tests use disposable repos, never the real local planning archive."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_publication.py"


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nivakyo-policy-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "--quiet")
        self.git("config", "user.name", "Fixture reviewer")
        self.git("config", "user.email", "fixture@example.invalid")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, check=True)

    def write(self, path, text="Synthetic test fixture\n"):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        self.git("add", "--", path)

    def check(self, *args, input=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.root,
                              input=input, capture_output=True, text=True)

    def test_public_source_and_usage_docs_are_allowed(self):
        self.write("src/simulator.py")
        self.write("docs/architecture.md")
        self.assertEqual(self.check("--staged").returncode, 0)
        self.git("commit", "--quiet", "-m", "Public source fixture")
        self.assertEqual(self.check("--ref", "HEAD").returncode, 0)

    def test_staged_local_planning_is_blocked(self):
        self.write(".local/planning/notes.md")
        result = self.check("--staged")
        self.assertEqual(result.returncode, 1)
        self.assertIn(".local/planning/notes.md", result.stderr)

    def test_renamed_known_plan_and_schedule_are_blocked(self):
        for path in ("docs/project_brief.md", "phase-2.md", "roadmap.json", "schedule.docx"):
            with self.subTest(path=path):
                self.write(path)
                self.assertEqual(self.check("--staged").returncode, 1)
                self.git("rm", "--cached", "--", path)

    def test_deleted_planning_is_still_blocked_in_history(self):
        self.write("docs/roadmap.md")
        self.git("commit", "--quiet", "-m", "Synthetic protected history fixture")
        self.git("rm", "docs/roadmap.md")
        self.git("commit", "--quiet", "-m", "Delete synthetic fixture")
        self.assertEqual(self.check("--staged").returncode, 0)
        self.assertEqual(self.check("--ref", "HEAD").returncode, 1)

    def test_pre_push_checks_refs_and_allows_ref_deletion(self):
        self.write("plans/synthetic.md")
        self.git("commit", "--quiet", "-m", "Synthetic push fixture")
        sha = self.git("rev-parse", "HEAD").stdout.decode().strip()
        line = "refs/heads/main %s refs/heads/main %s\n" % (sha, "0" * 40)
        self.assertEqual(self.check("--pre-push", input=line).returncode, 1)
        deletion = "(delete) %s refs/heads/main %s\n" % ("0" * 40, sha)
        self.assertEqual(self.check("--pre-push", input=deletion).returncode, 0)
        self.assertEqual(self.check("--pre-push", input="malformed\n").returncode, 2)


if __name__ == "__main__":
    unittest.main()
