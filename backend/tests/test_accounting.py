"""Shared position accounting (spec phases 7-8): funding direction, bad debt, cash-identity reconciliation."""
from __future__ import annotations

import pytest

from app.execution import accounting
from app.models.enums import Side
from tests.helpers_agents import make_dna


def test_funding_direction_long_pays_positive_rate_short_receives():
    assert accounting.funding_payment(Side.LONG, 2.0, 100.0, 0.0001) == pytest.approx(0.02)      # long pays
    assert accounting.funding_payment(Side.SHORT, 2.0, 100.0, 0.0001) == pytest.approx(-0.02)    # short receives
    assert accounting.funding_payment(Side.LONG, 2.0, 100.0, -0.0001) == pytest.approx(-0.02)    # negative rate: long receives
    assert accounting.funding_payment(Side.SHORT, 2.0, 100.0, -0.0001) == pytest.approx(0.02)


def test_funding_is_proportional_to_notional():
    small = accounting.funding_payment(Side.LONG, 1.0, 100.0, 0.0001)
    big = accounting.funding_payment(Side.LONG, 10.0, 100.0, 0.0001)
    assert big == pytest.approx(10 * small)


def test_settle_close_without_shortfall():
    s = accounting.settle_close(100.0, gross_pnl=20.0, exit_fee=1.0)
    assert s.new_balance == pytest.approx(119.0) and s.bad_debt == 0.0


def test_settle_close_records_bad_debt_instead_of_hiding_it():
    s = accounting.settle_close(100.0, gross_pnl=-150.0, exit_fee=2.0)
    assert s.new_balance == 0.0                  # an account cannot go below zero ...
    assert s.bad_debt == pytest.approx(52.0)     # ... but the shortfall is RECORDED (100 - 150 - 2 = -52)


def test_liquidation_penalty_and_cooldown_expiry():
    assert accounting.liquidation_penalty(100.0, 2.0, 0.005) == pytest.approx(1.0)
    assert accounting.cooldown_expiry_ms(1_000_000, 0, 60_000) is None
    assert accounting.cooldown_expiry_ms(1_000_000, 3, 60_000) == 1_000_000 + 3 * 60_000
    assert accounting.cooldown_bars_after(None, -5.0) == 0


def test_entry_levels_follow_the_dna():
    dna = make_dna()
    lv = accounting.entry_levels(dna, Side.LONG, 100.0, atr=0.5, swing_low=None, swing_high=None)
    assert lv.stop_loss == pytest.approx(99.0)               # atr_multiple 2.0 * 0.5 below entry
    assert lv.take_profit == pytest.approx(102.0)            # risk_reward 2.0 x the 1.0 stop distance
    assert lv.trailing_distance is None and lv.trailing_active is False


def test_cash_identity_reconciles_through_wins_losses_and_bad_debt():
    start = balance = 100.0
    realized = bad_debt = 0.0
    # (entry_fee, funding, gross_pnl, exit_fee) per trade; the last one blows through the account
    for entry_fee, funding, gross, exit_fee in [(0.05, 0.01, 10.0, 0.06), (0.05, -0.02, -4.0, 0.05), (0.5, 0.1, -400.0, 2.0)]:
        balance -= entry_fee
        balance -= funding
        s = accounting.settle_close(balance, gross, exit_fee)
        realized += gross - (entry_fee + exit_fee) - funding
        balance, bad_debt = s.new_balance, bad_debt + s.bad_debt
        assert accounting.reconcile(starting_balance=start, balance=balance, realized_pnl=realized, bad_debt=bad_debt) == pytest.approx(0.0, abs=1e-9)
    assert bad_debt > 0 and balance == 0.0


def test_reconcile_accounts_for_the_open_positions_fee_and_funding():
    # entry fee 0.5 and funding 0.2 have already left the balance, but reach realized_pnl only on close
    assert accounting.reconcile(starting_balance=100.0, balance=99.3, realized_pnl=0.0, bad_debt=0.0,
                                open_entry_fee=0.5, open_funding=0.2) == pytest.approx(0.0)
