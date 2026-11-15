from datetime import datetime, timezone

from scripts.evaluate_loghub import read_bgl, rolling_static


def test_bgl_reader_preserves_alert_labels_and_buckets(tmp_path):
    path = tmp_path / "BGL_2k.log"
    path.write_text(
        "- 1117838570 2005.06.03 node timestamp node RAS KERNEL INFO normal\n"
        "APPREAD 1117838575 2005.06.03 node timestamp node RAS APP FATAL failed\n",
        encoding="utf-8",
    )

    errors, total, alerts, skipped = read_bgl(path, None, bucket_minutes=1)

    bucket = datetime.fromtimestamp(1117838520, tz=timezone.utc)
    assert total[bucket] == 2
    assert errors[bucket] == 1
    assert alerts == {bucket}
    assert skipped == 0


def test_static_baseline_excludes_the_value_being_scored():
    assert rolling_static([1, 1, 1, 10], window=3) == {3}
