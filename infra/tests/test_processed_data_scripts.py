"""infra/upload-processed-data.sh と infra/install-processed-data.sh を、aws・curl・systemctl の
偽物で通して確かめる（S3 にも EC2 にもつながない）。"""

import hashlib
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="deployment shell scripts require POSIX paths"
)

BASH = shutil.which("bash") or "/bin/bash"

INFRA = Path(__file__).resolve().parents[1]
UPLOAD = INFRA / "upload-processed-data.sh"
INSTALL = INFRA / "install-processed-data.sh"
TABLES = [
    "stations.parquet",
    "postal.parquet",
    "area_codes.parquet",
    "muni_mesh.parquet",
    "households_500m.parquet",
    "schools.parquet",
    "shelters.parquet",
    "bus_stops.parquet",
    "school_districts.parquet",
    "ridership.parquet",
    "corporations.sqlite",
]
URL = "https://tkb-bucket.s3.us-east-1.amazonaws.com/processed/x.tar.gz?X-Amz-Signature=abc"

FAKE_AWS = """#!/bin/bash
# s3api get-public-access-block / s3 cp / s3 presign だけ
case "$1 $2" in
  "s3api get-public-access-block") echo "$FAKE_BLOCK" ;;
  "s3 cp") cp "${@: -2:1}" "$FAKE_S3/uploaded.tar.gz"; echo "${@: -1}" > "$FAKE_S3/key" ;;
  "s3 presign") echo "$FAKE_URL" ;;
  *) exit 2 ;;
esac
"""
FAKE_CURL = """#!/bin/bash
out=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift 2 ;; *) shift ;; esac
done
cp "$FAKE_S3/uploaded.tar.gz" "$out"
"""
FAKE_SYSTEMCTL = """#!/bin/bash
echo "$*" >> "$FAKE_S3/systemctl"
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("aws", FAKE_AWS), ("curl", FAKE_CURL), ("systemctl", FAKE_SYSTEMCTL)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    src = tmp_path / "processed"
    src.mkdir()
    for name in TABLES:
        (src / name).write_bytes(f"table {name}".encode())
    (tmp_path / "s3").mkdir()
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TKB_PROCESSED_DIR": str(src),
        "TKB_APP_DIR": str(tmp_path / "app"),
        "FAKE_S3": str(tmp_path / "s3"),
        "FAKE_BLOCK": "True\tTrue\tTrue\tTrue",
        "FAKE_URL": URL,
    }


def run(args: list[str], env: dict[str, str], stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  リポジトリのスクリプトを偽物の PATH で動かすだけ
        [BASH, *args], env=env, input=stdin, capture_output=True, text=True, check=False
    )


def uploaded_sha(env: dict[str, str]) -> str:
    return hashlib.sha256((Path(env["FAKE_S3"]) / "uploaded.tar.gz").read_bytes()).hexdigest()


def test_upload_packs_every_table_with_a_manifest_and_prints_the_url(env: dict[str, str]) -> None:
    done = run([str(UPLOAD), "tkb-bucket"], env)

    assert done.returncode == 0, done.stderr
    sha = uploaded_sha(env)
    assert sha in done.stdout
    assert URL in done.stdout
    assert (Path(env["FAKE_S3"]) / "key").read_text().startswith("s3://tkb-bucket/processed/")
    with tarfile.open(Path(env["FAKE_S3"]) / "uploaded.tar.gz") as tar:
        assert sorted(tar.getnames()) == sorted([*TABLES, "MANIFEST.sha256"])
        assert all(m.uid == 0 and m.isfile() for m in tar.getmembers())


@pytest.mark.parametrize("missing", ["corporations.sqlite", "households_500m.parquet"])
def test_upload_stops_when_a_table_is_missing(env: dict[str, str], missing: str) -> None:
    (Path(env["TKB_PROCESSED_DIR"]) / missing).unlink()

    done = run([str(UPLOAD), "tkb-bucket"], env)

    assert done.returncode != 0
    assert missing in done.stderr
    assert not (Path(env["FAKE_S3"]) / "uploaded.tar.gz").exists()


def test_upload_refuses_a_bucket_that_can_be_public(env: dict[str, str]) -> None:
    done = run([str(UPLOAD), "tkb-bucket"], {**env, "FAKE_BLOCK": "True\tTrue\tFalse\tTrue"})

    assert done.returncode != 0
    assert not (Path(env["FAKE_S3"]) / "uploaded.tar.gz").exists()


@pytest.mark.parametrize("expires", ["0", "7200", "abc"])
def test_upload_keeps_the_url_short_lived(env: dict[str, str], expires: str) -> None:
    assert run([str(UPLOAD), "tkb-bucket", expires], env).returncode != 0


def test_install_swaps_the_tables_and_restarts_the_app(env: dict[str, str]) -> None:
    assert run([str(UPLOAD), "tkb-bucket"], env).returncode == 0
    dest = Path(env["TKB_APP_DIR"]) / "data" / "processed"
    dest.mkdir(parents=True)
    (dest / "stations.parquet").write_text("old")

    done = run([str(INSTALL), uploaded_sha(env)], env, stdin=URL + "\n")

    assert done.returncode == 0, done.stderr
    assert URL not in done.stdout + done.stderr
    assert sorted(p.name for p in dest.iterdir()) == sorted(TABLES)
    assert (dest / "stations.parquet").read_text() == "table stations.parquet"
    assert oct((dest / "corporations.sqlite").stat().st_mode)[-3:] == "644"
    assert (dest.parent / "processed.prev" / "stations.parquet").read_text() == "old"
    assert (Path(env["FAKE_S3"]) / "systemctl").read_text().strip() == "restart tkb-app"
    assert [p.name for p in dest.parent.iterdir() if p.name.startswith(".processed-")] == []


def test_install_rejects_a_wrong_sha_and_keeps_the_old_tables(env: dict[str, str]) -> None:
    assert run([str(UPLOAD), "tkb-bucket"], env).returncode == 0
    dest = Path(env["TKB_APP_DIR"]) / "data" / "processed"
    dest.mkdir(parents=True)
    (dest / "stations.parquet").write_text("old")

    done = run([str(INSTALL), "0" * 64], env, stdin=URL + "\n")

    assert done.returncode != 0
    assert (dest / "stations.parquet").read_text() == "old"
    assert not (Path(env["FAKE_S3"]) / "systemctl").exists()


def test_install_rejects_a_url_outside_s3(env: dict[str, str]) -> None:
    assert run([str(UPLOAD), "tkb-bucket"], env).returncode == 0

    done = run([str(INSTALL), uploaded_sha(env)], env, stdin="https://example.com/x.tar.gz\n")

    assert done.returncode != 0
    assert not (Path(env["TKB_APP_DIR"]) / "data" / "processed").exists()


def test_install_rejects_unexpected_members(env: dict[str, str], tmp_path: Path) -> None:
    evil = tmp_path / "evil"
    evil.mkdir()
    (evil / "x.parquet").write_text("x")
    archive = Path(env["FAKE_S3"]) / "uploaded.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(evil / "x.parquet", arcname="../x.parquet")

    done = run([str(INSTALL), uploaded_sha(env)], env, stdin=URL + "\n")

    assert done.returncode != 0
    assert not (tmp_path / "app" / "x.parquet").exists()
    assert not (Path(env["TKB_APP_DIR"]) / "data" / "processed").exists()
