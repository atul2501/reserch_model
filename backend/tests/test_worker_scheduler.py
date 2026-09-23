from app.worker.scheduler import (
    confirmation_time_ms, council_due, last_confirmed_open_time, seconds_until_next_confirmation,
)

I, G = 60_000, 1_500
T = 1_700_000_040_000  # a minute boundary (divisible by 60_000)


def test_last_confirmed_bar_flips_exactly_at_close_plus_grace():
    close_of_prev = T - 1                      # bar opening at T-I closes at T-1
    just_before = close_of_prev + G - 1
    exactly = close_of_prev + G
    assert last_confirmed_open_time(just_before, I, G) == T - 2 * I
    assert last_confirmed_open_time(exactly, I, G) == T - I


def test_mid_bar_never_returns_the_open_bar():
    assert last_confirmed_open_time(T + 30_000, I, G) == T - I


def test_sleep_targets_next_confirmation_not_a_fixed_interval():
    now = T + 10_000  # 10s into the bar opening at T
    delay = seconds_until_next_confirmation(now, I, G)
    # bar T confirms at T + 59_999 + 1_500
    assert delay == (confirmation_time_ms(T, I, G) - now) / 1000
    assert 0 < delay < 60


def test_delay_never_negative_and_no_drift_after_long_cycle():
    # Cycle finished 5s after confirmation: next wake is ~55s later, not +60s.
    just_after_confirm = confirmation_time_ms(T, I, G) + 5_000
    assert 50 < seconds_until_next_confirmation(just_after_confirm, I, G) < 56


def test_council_cadence_is_derived_from_candle_time():
    due = [council_due(T + k * I, I, 5) for k in range(10)]
    assert sum(due) == 2 and due[0] != due[1]
    assert council_due(T, I, 1) is True
