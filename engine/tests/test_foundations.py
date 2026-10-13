import sqlite3

import pytest

from qlab.lab import Lab
from qlab.storage import db
from qlab.storage.backup import create_backup, restore_backup
from qlab.tasks import checkpoints, queue


@pytest.fixture
def lab(tmp_path):
    lab = Lab.open(tmp_path / "data")
    yield lab
    lab.close()


def test_migrations_idempotent_and_checksummed(lab):
    assert db.migrate(lab.con, lab.paths.db, lab.paths.backups) == []
    v = lab.con.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert v >= 1


def test_failed_migration_rolls_back_and_keeps_backup(lab):  # AT-011
    before = {r[0] for r in lab.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    bad = db.available_migrations() + [(9999, "9999_bad.sql", "CREATE TABLE zz (a INT); INSERT INTO nope VALUES (1)")]
    with pytest.raises(db.MigrationError):
        db.migrate(lab.con, lab.paths.db, lab.paths.backups, migrations=bad)
    after = {r[0] for r in lab.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert after == before  # la table zz a été annulée
    backups = list(lab.paths.backups.glob("pre-migration-*.sqlite"))
    assert backups, "sauvegarde pré-migration absente"
    restored = sqlite3.connect(backups[0])
    assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    restored.close()


def test_task_state_machine(lab):
    tid = queue.submit(lab.con, "noop", {"x": 1}, idempotency_key="k1")
    assert queue.submit(lab.con, "noop", {"x": 1}, idempotency_key="k1") == tid
    with pytest.raises(queue.IllegalTransition):
        queue.transition(lab.con, tid, "completed")
    t = queue.claim_next(lab.con)
    assert t["id"] == tid and t["state"] == "validating"
    queue.transition(lab.con, tid, "running")
    queue.transition(lab.con, tid, "completed", result={"ok": True})
    with pytest.raises(queue.IllegalTransition):
        queue.transition(lab.con, tid, "running")
    assert queue.get(lab.con, tid)["result"] == {"ok": True}


def test_recovery_and_checkpoints(lab):
    tid = queue.submit(lab.con, "noop", {})
    queue.claim_next(lab.con)
    queue.transition(lab.con, tid, "running")
    checkpoints.save(lab.con, lab.store, tid, {"gen": 1})
    checkpoints.save(lab.con, lab.store, tid, {"gen": 2})
    assert queue.recover_interrupted(lab.con) == [tid]
    assert queue.get(lab.con, tid)["state"] == "paused"
    assert checkpoints.latest(lab.con, lab.store, tid) == {"gen": 2}


def test_backup_restore_roundtrip(lab, tmp_path):  # AT-010
    tid = queue.submit(lab.con, "noop", {})
    sha = lab.store.put_json({"hello": "world"}, kind="test")
    checkpoints.save(lab.con, lab.store, tid, {"gen": 7})
    archive = create_backup(lab.con, lab.paths)
    report = restore_backup(archive, tmp_path / "restored")
    assert report["ok"], report
    lab2 = Lab.open(tmp_path / "restored")
    assert lab2.store.get_json(sha) == {"hello": "world"}
    assert checkpoints.latest(lab2.con, lab2.store, tid) == {"gen": 7}
    lab2.close()


def test_restore_detects_corruption(lab, tmp_path):
    import zipfile
    sha = lab.store.put_json({"a": 1}, kind="test")
    archive = create_backup(lab.con, lab.paths)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(tampered, "w") as dst:
        for n in src.namelist():
            data = src.read(n)
            dst.writestr(n, b"corrupt" if sha in n else data)
    report = restore_backup(tampered, tmp_path / "r2")
    assert not report["ok"] and report["missing_artifacts"] == [sha]


def test_restore_refuses_non_empty_target(lab, tmp_path):
    archive = create_backup(lab.con, lab.paths)
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "f").write_text("x")
    with pytest.raises(FileExistsError):
        restore_backup(archive, tmp_path / "busy")
