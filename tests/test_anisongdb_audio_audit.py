"""Recording comparisons must preserve covers and edits sharing an intro."""
import numpy as np
import pytest

from tools.audit_anisongdb_audio import compare_recordings, compare_waveforms, is_strict_recording_match


RATE = 512


@pytest.mark.parametrize("gain", [0.5, 2.0, -1.0])
def test_recording_comparison_aligns_shifted_and_scaled_audio(gain):
    samples = np.random.default_rng(2).normal(0, 100, RATE * 45)
    shifted = np.r_[np.zeros(RATE * 2), samples * gain]
    result = compare_waveforms(samples, shifted, rate=RATE)
    assert result["source_offset_seconds"] == 2
    assert result["whole_correlation"] == 1
    assert is_strict_recording_match(result)


def test_shared_intro_does_not_establish_complete_recording_identity():
    rng = np.random.default_rng(4)
    samples = rng.normal(0, 100, RATE * 95)
    changed = samples.copy()
    changed[RATE * 75:] = rng.normal(0, 100, RATE * 20)
    result = compare_waveforms(samples, changed, rate=RATE)
    assert result["status"] == "strong_audio_match"
    assert not is_strict_recording_match(result)


@pytest.mark.parametrize("volume", [30, 50])
def test_different_vocals_over_shared_backing_remain_unconfirmed(volume):
    rng = np.random.default_rng(8)
    backing = rng.normal(0, 100, RATE * 45)
    time = np.arange(len(backing)) / RATE
    original = backing + volume * np.sin(time * 2 * np.pi * 17)
    cover = backing + volume * np.sin(time * 2 * np.pi * 29)
    assert not is_strict_recording_match(compare_waveforms(original, cover, rate=RATE))


@pytest.mark.parametrize("delay", [-0.49, -0.27, 0.36, 0.49])
def test_encoding_offsets_smaller_than_one_sample_do_not_hide_identical_recordings(delay):
    time = np.arange(RATE * 45) / RATE
    def recording(time):
        return sum(volume * np.sin(2 * np.pi * (frequency * time + slope * time * time))
                   for frequency, volume, slope in ((13.17, 80, 0.71), (41.57, 60, 0.37), (69.23, 50, 0.11), (94.15, 20, 0.05)))
    result = compare_waveforms(recording(time), recording(time - delay / RATE), rate=RATE)
    assert is_strict_recording_match(result)
    assert result["whole_correlation"] > 0.999
    assert abs(result["source_fractional_sample_shift"] + delay) <= 0.01


def test_subsample_alignment_does_not_merge_an_edit_with_a_changed_ending():
    time = np.arange(RATE * 95) / RATE
    original = 100 * np.sin(time * 2 * np.pi * 43.17) + 70 * np.sin(time * 2 * np.pi * 81.29)
    shifted = 100 * np.sin((time - 0.33 / RATE) * 2 * np.pi * 43.17) + 70 * np.sin((time - 0.33 / RATE) * 2 * np.pi * 81.29)
    shifted[RATE * 75:] = np.random.default_rng(41).normal(0, 100, RATE * 20)
    result = compare_waveforms(original, shifted, rate=RATE)
    assert result["status"] == "strong_audio_match"
    assert not is_strict_recording_match(result)


def test_unrelated_audio_has_no_recording_match():
    rng = np.random.default_rng(12)
    left, right = rng.normal(0, 100, (2, RATE * 45))
    assert compare_waveforms(left, right, rate=RATE)["status"] == "no_audio_match"


def _clock_recording(time):
    # Independent analytic phases make each excerpt identifiable without using
    # the interpolator being tested to generate either recording.
    rng = np.random.default_rng(84)
    frequencies = rng.uniform(5, 175, 43)
    volumes = rng.uniform(8, 25, 43)
    slopes = rng.uniform(-0.04, 0.3, 43)
    phases = rng.uniform(0, 2 * np.pi, 43)
    return sum(volume * np.sin(2 * np.pi * (frequency * time + slope * time * time) + phase)
               for frequency, volume, slope, phase in zip(frequencies, volumes, slopes, phases))


@pytest.mark.parametrize("factor", [0.99998, 1.000005, 1.00002])
def test_uniform_clock_difference_requires_agreement_throughout_the_recording(factor):
    time = np.arange(RATE * 85) / RATE
    left, right = _clock_recording(time), _clock_recording((time - 0.31 / RATE) / factor)
    assert not is_strict_recording_match(compare_recordings(left, right, rate=RATE))
    result = compare_recordings(left, right, rate=RATE, check_clock=True)
    assert is_strict_recording_match(result)
    assert abs(result["clock_alignment"]["factor"] - factor) < 0.000001
    assert result["clock_alignment"]["consistent_windows"] >= 4


def test_clock_alignment_cannot_confirm_a_shared_intro_with_a_different_ending():
    time = np.arange(RATE * 95) / RATE
    left, right = _clock_recording(time), _clock_recording(time / 1.00002)
    right[RATE * 75:] = np.random.default_rng(72).normal(0, 100, RATE * 20)
    assert not is_strict_recording_match(compare_recordings(left, right, rate=RATE, check_clock=True))


def test_clock_alignment_cannot_merge_different_singers_over_shared_backing():
    time = np.arange(RATE * 85) / RATE
    original = _clock_recording(time) + 60 * np.sin(2 * np.pi * 17.13 * time)
    source_time = time / 1.00002
    cover = _clock_recording(source_time) + 60 * np.sin(2 * np.pi * 29.71 * source_time)
    assert not is_strict_recording_match(compare_recordings(original, cover, rate=RATE, check_clock=True))


def test_clock_alignment_does_not_allow_substantial_speed_changes():
    time = np.arange(RATE * 85) / RATE
    assert not is_strict_recording_match(compare_recordings(_clock_recording(time), _clock_recording(time / 1.04), rate=RATE, check_clock=True))


@pytest.mark.parametrize("seconds, status", [(5, "insufficient_audio"), (45, "silent_audio")])
def test_silent_or_short_clips_cannot_supply_recording_evidence(seconds, status):
    samples = np.zeros(RATE * seconds)
    result = compare_waveforms(samples, samples, rate=RATE)
    assert result["status"] == status
    assert not is_strict_recording_match(result)
