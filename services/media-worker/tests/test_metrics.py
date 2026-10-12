"""Worker metrics (ADR-0048): jobs are counted by capability and status; GPU time is summed."""

from prometheus_client import generate_latest
from wasifyai_media_worker.metrics import record_job


def test_a_job_is_counted_timed_and_its_gpu_seconds_summed():
    record_job("music.generate", "completed", 12.5, 11.0)
    record_job("music.generate", "failed", 3.0, 0.0)
    text = generate_latest().decode()
    assert 'wdai_jobs_total{capability="music.generate",status="completed"}' in text
    assert 'wdai_jobs_total{capability="music.generate",status="failed"}' in text
    assert 'wdai_job_gpu_seconds_total{capability="music.generate"}' in text
    assert 'wdai_job_seconds_count{capability="music.generate"}' in text
