from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "supermind_baselines" / "supermind_baseline_3_1_high_attack_adaptive_expiry.py"
TARGET = ROOT / "supermind_baselines" / "supermind_baseline_3_1_high_attack_adaptive_expiry_daily.py"
TARGET_120K = ROOT / "supermind_baselines" / "supermind_baseline_3_1_high_attack_adaptive_expiry_daily_120k.py"
TARGET_120K_DYNAMIC = ROOT / "supermind_baselines" / "supermind_baseline_3_1_high_attack_adaptive_expiry_daily_120k_dynamic20.py"


def replace_once(text, old, new):
    count = text.count(old)
    if count != 1:
        raise RuntimeError("expected exactly one match, found %d: %r" % (count, old[:80]))
    return text.replace(old, new, 1)


def main():
    text = SOURCE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '"""SuperMind minute-frequency realistic execution strategy for STAR events.\n\n'
        "The single-file build embeds the model and needs no project attachment.\n"
        "Core position state is reconciled from the live account instead of depending on\n"
        "order callbacks. Set frequency to 1 minute. This is not investment advice.\n"
        '"""',
        '"""SuperMind daily-frequency execution strategy for STAR events.\n\n'
        "The single-file build embeds the model and needs no project attachment.\n"
        "Set the SuperMind backtest/simulation frequency to daily. Signals, entries and\n"
        "risk exits are evaluated once per trading day at the platform daily callback.\n"
        "This is not investment advice.\n"
        '"""',
    )
    text = replace_once(
        text,
        'log.info("High Attack Adaptive Expiry v1 initialized; threshold=0.63; calendar expiry=30/60d; cost=%s" % COST_SCENARIO)',
        'log.info("High Attack Adaptive Expiry DAILY initialized; threshold=0.63; calendar expiry=30/60d; cost=%s" % COST_SCENARIO)',
    )
    text = replace_once(
        text,
        '    """Return (tradable, locked_up, locked_down, price).\n\n'
        "    The explicit check is deliberately conservative. A candidate locked at the\n"
        "    upper limit is retried in later minute bars and can only be submitted after\n"
        "    it opens. A sell remains pending in strategy state while the lower limit is\n"
        "    locked. Platform matching and volume limits still make the final decision.\n"
        '    """',
        '    """Return the tradability and price-limit state at the daily callback.\n\n'
        "    A stock locked at its limit is skipped for the day. Daily mode does not\n"
        "    retry later intraday, so platform matching makes the final decision.\n"
        '    """',
    )
    text = replace_once(
        text,
        '    """Use actual account holdings as the source of truth every minute."""',
        '    """Use actual account holdings as the daily source of truth."""',
    )
    text = replace_once(
        text,
        "            if not tradable or locked_up:\n"
        "                # Do not mark the day done: a limit-up candidate may open later.\n"
        "                continue",
        "            if not tradable or locked_up:\n"
        "                # Daily mode has no later intraday retry.\n"
        "                continue",
    )
    text = replace_once(
        text,
        "        # Keep checking unsubmitted limit-up candidates until the final bars.\n"
        "        if now.hour > 14 or (now.hour == 14 and now.minute >= 55):\n"
        "            g.buy_done_date = now.date()\n"
        "    # Minute-level risk management.",
        "        # Exactly one entry pass per trading day.\n"
        "        g.buy_done_date = now.date()\n"
        "    # Daily snapshot risk management: this is not an intraday touch stop.",
    )
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(TARGET)

    small = text
    small = replace_once(
        small,
        '"""SuperMind daily-frequency execution strategy for STAR events.',
        '"""SuperMind daily-frequency execution strategy for a 120,000 CNY STAR account.',
    )
    small = replace_once(
        small,
        "}\n\n\n_EMBEDDED_MODEL_B64",
        "}\n\n\n# Small-account execution controls. Six 15% positions use at most 90% of NAV.\n"
        "TARGET_POSITION_FRACTION = 0.15\n"
        "MAX_POSITIONS_120K = 6\n"
        "MIN_STAR_SHARES = 200\n"
        "MIN_CASH_RESERVE_FRACTION = 0.10\n\n\n_EMBEDDED_MODEL_B64",
    )
    small = replace_once(
        small,
        '    g.model["threshold"] = 0.63\n',
        '    g.model["threshold"] = 0.63\n'
        '    g.model["max_positions"] = MAX_POSITIONS_120K\n'
        '    g.model["top_per_day"] = MAX_POSITIONS_120K\n',
    )
    small = replace_once(
        small,
        'log.info("High Attack Adaptive Expiry DAILY initialized; threshold=0.63; calendar expiry=30/60d; cost=%s" % COST_SCENARIO)',
        'log.info("High Attack Adaptive Expiry DAILY 120K initialized; threshold=0.63; max_positions=%d; target=%.1f%%; reserve=%.1f%%; cost=%s" % '
        '(MAX_POSITIONS_120K, TARGET_POSITION_FRACTION * 100.0, MIN_CASH_RESERVE_FRACTION * 100.0, COST_SCENARIO))',
    )
    small = replace_once(
        small,
        "            # STAR orders require at least 200 shares. This also prevents a\n"
        "            # batch of target-percent orders from silently oversubscribing cash.\n"
        "            if _available_cash(context) < price * 200 * 1.005:\n"
        "                continue\n"
        "            order_id = order_target_percent(symbol, 0.10)",
        "            # A 120K account cannot represent a 15% target when the STAR\n"
        "            # minimum 200-share order already costs more than that target.\n"
        "            total_value = float(context.portfolio.stock_account.total_value)\n"
        "            target_value = total_value * TARGET_POSITION_FRACTION\n"
        "            minimum_order_value = price * MIN_STAR_SHARES * 1.005\n"
        "            reserve_value = total_value * MIN_CASH_RESERVE_FRACTION\n"
        "            if target_value < minimum_order_value:\n"
        "                log.info(\"skip expensive %s price=%.2f min200=%.2f target=%.2f\" %\n"
        "                         (symbol, price, minimum_order_value, target_value))\n"
        "                continue\n"
        "            if _available_cash(context) - target_value < reserve_value:\n"
        "                continue\n"
        "            order_id = order_target_percent(symbol, TARGET_POSITION_FRACTION)",
    )
    TARGET_120K.write_text(small, encoding="utf-8", newline="\n")
    print(TARGET_120K)

    dynamic = text
    dynamic = replace_once(
        dynamic,
        '"""SuperMind daily-frequency execution strategy for STAR events.',
        '"""SuperMind daily-frequency execution strategy with 120K dynamic STAR sizing.',
    )
    dynamic = replace_once(
        dynamic,
        "}\n\n\n_EMBEDDED_MODEL_B64",
        "}\n\n\n# Preserve the original strategy and only relax its 10% position target when\n"
        "# the STAR Market 200-share minimum requires more capital.\n"
        "BASE_POSITION_FRACTION = 0.10\n"
        "MAX_POSITION_FRACTION_120K = 0.20\n"
        "MIN_STAR_SHARES = 200\n"
        "MIN_ORDER_BUFFER = 1.01\n\n\n_EMBEDDED_MODEL_B64",
    )
    dynamic = replace_once(
        dynamic,
        'log.info("High Attack Adaptive Expiry DAILY initialized; threshold=0.63; calendar expiry=30/60d; cost=%s" % COST_SCENARIO)',
        'log.info("High Attack Adaptive Expiry DAILY 120K DYNAMIC initialized; base=%.1f%%; cap=%.1f%%; cost=%s" % '
        '(BASE_POSITION_FRACTION * 100.0, MAX_POSITION_FRACTION_120K * 100.0, COST_SCENARIO))',
    )
    dynamic = replace_once(
        dynamic,
        "            # STAR orders require at least 200 shares. This also prevents a\n"
        "            # batch of target-percent orders from silently oversubscribing cash.\n"
        "            if _available_cash(context) < price * 200 * 1.005:\n"
        "                continue\n"
        "            order_id = order_target_percent(symbol, 0.10)",
        "            # Keep the original 10% target whenever it can buy at least 200\n"
        "            # shares. Raise only the minimum necessary fraction for expensive\n"
        "            # stocks, subject to a hard 20% single-name cap.\n"
        "            total_value = float(context.portfolio.stock_account.total_value)\n"
        "            minimum_fraction = (price * MIN_STAR_SHARES * MIN_ORDER_BUFFER) / total_value\n"
        "            target_fraction = max(BASE_POSITION_FRACTION, minimum_fraction)\n"
        "            if target_fraction > MAX_POSITION_FRACTION_120K:\n"
        "                log.info(\"skip cap %s price=%.2f required=%.4f cap=%.4f\" %\n"
        "                         (symbol, price, target_fraction, MAX_POSITION_FRACTION_120K))\n"
        "                continue\n"
        "            required_cash = total_value * target_fraction * 1.005\n"
        "            if _available_cash(context) < required_cash:\n"
        "                continue\n"
        "            order_id = order_target_percent(symbol, target_fraction)",
    )
    TARGET_120K_DYNAMIC.write_text(dynamic, encoding="utf-8", newline="\n")
    print(TARGET_120K_DYNAMIC)


if __name__ == "__main__":
    main()
