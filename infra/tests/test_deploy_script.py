"""infra/deploy.sh の流れを、本物の git と、偽の docker・systemctl・curl・python3 で確かめる。

EC2 にも AWS にもつながない。偽のコマンドは呼ばれたことを calls.log に書き、
FAIL_SMOKE_SHAS に書いたコミットのときだけスモークを失敗させる。"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy.sh"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}

FAKES = {
    "docker": """#!/bin/bash
echo "docker $*" >> "$CALLS"
case "$1 $2" in
  "inspect -f") echo "${FAKE_API_HEALTH:-healthy}" ;;
  "image inspect") exit 0 ;;
  "image ls") printf '' ;;
esac
exit 0
""",
    "systemctl": """#!/bin/bash
echo "systemctl $* $(git rev-parse --short HEAD)" >> "$CALLS"
exit "${FAKE_RESTART_EXIT:-0}"
""",
    "curl": """#!/bin/bash
echo "curl $*" >> "$CALLS"
exit 0
""",
    "python3": """#!/bin/bash
head="$(git rev-parse HEAD)"
echo "smoke $head" >> "$CALLS"
if grep -qx "$head" "$FAIL_SMOKE_SHAS" 2>/dev/null; then exit 1; fi
exit 0
""",
}


def _run(cmd: list[str], *, check: bool = False, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    # 一時ディレクトリの git と、リポジトリの deploy.sh を偽物の PATH で動かすだけ
    kwargs.setdefault("text", True)
    return subprocess.run(cmd, check=check, **kwargs)  # noqa: S603


@dataclass
class Box:
    """デプロイ先（clone）と、main を進める元のリポジトリ（origin）"""

    origin: Path
    repo: Path
    calls: Path
    fail_smoke: Path
    env: dict[str, str]

    def git(self, *args: str, cwd: Path | None = None) -> str:
        out = _run(
            ["git", *args],
            cwd=cwd or self.repo,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()

    def commit_on_main(self, name: str) -> str:
        (self.origin / "infra" / f"{name}.txt").write_text(name)
        self.git("add", "-A", cwd=self.origin)
        self.git("commit", "-qm", name, cwd=self.origin)
        return self.git("rev-parse", "HEAD", cwd=self.origin)

    def deploy(self, *args: str) -> subprocess.CompletedProcess[str]:
        return _run(
            ["bash", str(SCRIPT), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def log(self) -> list[str]:
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def restarts(self) -> list[str]:
        return [line for line in self.log() if line.startswith("systemctl restart")]


@pytest.fixture
def box(tmp_path: Path) -> Box:
    if shutil.which("flock") is None:
        pytest.skip("flock がない環境")
    env = {**os.environ, **GIT_ENV}
    origin = tmp_path / "origin"
    (origin / "infra").mkdir(parents=True)
    (origin / "infra" / "tkb-app-start.sh").write_text("#!/bin/bash\n")
    (origin / "infra" / "prod_smoke.py").write_text("# 偽の python3 が代わりに判定する\n")
    _run(["git", "init", "-q", "-b", "main", str(origin)], env=env, check=True)
    _run(["git", "-C", str(origin), "add", "-A"], env=env, check=True)
    _run(["git", "-C", str(origin), "commit", "-qm", "first"], env=env, check=True)
    repo = tmp_path / "repo"
    _run(["git", "clone", "-q", str(origin), str(repo)], env=env, check=True)
    (repo / ".env").write_text("PUBLIC_URL=https://example.cloudfront.net\nAUTH_MODE=oauth\n")
    (repo / "data" / "processed").mkdir(parents=True)
    (repo / "data" / "processed" / "stations.sqlite").write_text("keep")
    # 本番と同じく、.env と data/ は git の管理外
    (repo / ".git" / "info" / "exclude").write_text(".env\ndata/\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in FAKES.items():
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
    calls = tmp_path / "calls.log"
    fail_smoke = tmp_path / "fail-smoke"
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "CALLS": str(calls),
            "FAIL_SMOKE_SHAS": str(fail_smoke),
            "TKB_REPO_DIR": str(repo),
            "TKB_DEPLOY_LOCK": str(tmp_path / "deploy.lock"),
            "TKB_START_SCRIPT_DEST": str(tmp_path / "tkb-app-start"),
            "TKB_HEALTH_TIMEOUT_SECONDS": "4",
        }
    )
    return Box(origin, repo, calls, fail_smoke, env)


def result_line(proc: subprocess.CompletedProcess[str]) -> str:
    lines = [line for line in proc.stdout.splitlines() if line.startswith("DEPLOY_RESULT=")]
    assert len(lines) == 1, proc.stdout + proc.stderr
    return lines[0]


def test_deploys_the_latest_main_and_keeps_env_and_data(box: Box) -> None:
    previous = box.git("rev-parse", "HEAD")
    target = box.commit_on_main("feature")

    proc = box.deploy(target)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert result_line(proc) == (
        f"DEPLOY_RESULT=success PREVIOUS={previous} TARGET={target} CURRENT={target}"
    )
    assert box.git("rev-parse", "HEAD") == target
    assert len(box.restarts()) == 1
    assert f"docker tag tkb_2613-api:latest tkb_2613-api:rollback-{previous[:7]}" in box.log()
    assert f"docker tag tkb_2613-web:latest tkb_2613-web:rollback-{previous[:7]}" in box.log()
    assert f"smoke {target}" in box.log()
    assert (box.repo / ".env").read_text().startswith("PUBLIC_URL=")
    assert (box.repo / "data" / "processed" / "stations.sqlite").read_text() == "keep"
    assert (Path(box.env["TKB_START_SCRIPT_DEST"])).exists()


def test_a_failed_smoke_rolls_back_to_the_previous_commit(box: Box) -> None:
    previous = box.git("rev-parse", "HEAD")
    target = box.commit_on_main("broken")
    box.fail_smoke.write_text(target + "\n")

    proc = box.deploy(target)

    assert proc.returncode == 10
    assert result_line(proc).startswith(f"DEPLOY_RESULT=rolled_back PREVIOUS={previous}")
    assert result_line(proc).endswith(f"CURRENT={previous}")
    assert box.git("rev-parse", "HEAD") == previous
    assert [line.split()[-1] for line in box.restarts()] == [target[:7], previous[:7]]


def test_an_unhealthy_api_rolls_back(box: Box) -> None:
    previous = box.git("rev-parse", "HEAD")
    target = box.commit_on_main("unhealthy")
    box.env["FAKE_API_HEALTH"] = "unhealthy"

    proc = box.deploy(target)

    # 前のコミットでも healthy にならないので、ロールバックも失敗として知らせる
    assert proc.returncode == 20
    assert result_line(proc).startswith("DEPLOY_RESULT=rollback_failed")
    assert box.git("rev-parse", "HEAD") == previous
    assert "rollback-" in proc.stdout


def test_a_failed_restart_rolls_back(box: Box) -> None:
    previous = box.git("rev-parse", "HEAD")
    target = box.commit_on_main("cannot-start")
    box.env["FAKE_RESTART_EXIT"] = "1"

    proc = box.deploy(target)

    assert proc.returncode == 20
    assert box.git("rev-parse", "HEAD") == previous


def test_only_the_latest_main_can_be_deployed(box: Box) -> None:
    previous = box.git("rev-parse", "HEAD")
    older = box.commit_on_main("older")
    box.commit_on_main("newer")

    proc = box.deploy(older)

    assert proc.returncode == 4
    assert "最新の main ではありません" in proc.stdout
    assert box.git("rev-parse", "HEAD") == previous
    assert box.restarts() == []


@pytest.mark.parametrize("arg", ["", "main", "abc123", "A" * 40, "0" * 39, "0" * 40 + ";id"])
def test_rejects_anything_but_a_full_sha(box: Box, arg: str) -> None:
    proc = box.deploy(arg)

    assert proc.returncode == 2
    assert result_line(proc).startswith("DEPLOY_RESULT=invalid_argument")
    assert box.restarts() == []


def test_hand_edits_to_tracked_files_stop_the_deploy(box: Box) -> None:
    target = box.commit_on_main("feature")
    (box.repo / "infra" / "tkb-app-start.sh").write_text("#!/bin/bash\necho edited\n")

    proc = box.deploy(target)

    assert proc.returncode == 4
    assert "手元の変更" in proc.stdout
    assert (box.repo / "infra" / "tkb-app-start.sh").read_text().endswith("edited\n")
    assert box.restarts() == []


def test_a_target_without_the_smoke_script_is_not_deployed(box: Box) -> None:
    (box.origin / "infra" / "prod_smoke.py").unlink()
    target = box.commit_on_main("no-smoke")

    proc = box.deploy(target)

    assert proc.returncode == 4
    assert box.restarts() == []


def test_a_missing_env_file_stops_the_deploy(box: Box) -> None:
    target = box.commit_on_main("feature")
    (box.repo / ".env").unlink()

    proc = box.deploy(target)

    assert proc.returncode == 4
    assert box.restarts() == []


def test_a_second_deploy_waits_for_nothing_and_stops(box: Box) -> None:
    target = box.commit_on_main("feature")
    lock = box.env["TKB_DEPLOY_LOCK"]
    holder = subprocess.Popen(["flock", lock, "sleep", "5"])  # noqa: S603, S607
    try:
        # flock が掴むのを待つ
        for _ in range(50):
            if _run(["flock", "-n", lock, "true"]).returncode != 0:
                break
        proc = box.deploy(target)
    finally:
        holder.kill()
        holder.wait()

    assert proc.returncode == 3
    assert result_line(proc).startswith("DEPLOY_RESULT=locked")
    assert box.restarts() == []
