import importlib.util
import sys
import types
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


class SuperMindExportTest(unittest.TestCase):
    def load(self, closes, held=0, available=0):
        api = types.ModuleType("mindgo_api")
        for name in ("set_benchmark", "set_commission", "set_slippage",
                     "set_volume_limit", "enable_open_bar"):
            setattr(api, name, lambda *args, **kwargs: None)
        api.PriceSlippage = lambda *args: None
        api.PerShare = lambda **kwargs: None
        sys.modules["mindgo_api"] = api
        here = Path(__file__).resolve().parent
        build_spec = importlib.util.spec_from_file_location("build_supermind_test", here / "build_supermind.py")
        build_module = importlib.util.module_from_spec(build_spec)
        build_spec.loader.exec_module(build_module)
        path = here / "默认SuperMind策略.py"
        spec = importlib.util.spec_from_file_location("supermind_basic_ma_test", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        dates = pd.bdate_range("2025-01-02", periods=len(closes))
        frame = pd.DataFrame({"close": closes}, index=dates)
        orders = []
        module.g = types.SimpleNamespace()
        module.log = types.SimpleNamespace(info=lambda *args: None)
        module.history = lambda *args, **kwargs: {module.SYMBOL: frame}
        module.get_datetime = lambda: (dates[-1] + pd.offsets.BDay()).to_pydatetime()
        module.order = lambda symbol, qty, price=None: orders.append((symbol, qty, price)) or "order-1"
        position = types.SimpleNamespace(amount=held, available_amount=available)
        positions = {module.SYMBOL: position} if held else {}
        account = types.SimpleNamespace(total_value=100000.0, available_cash=100000.0)
        context = types.SimpleNamespace(portfolio=types.SimpleNamespace(
            positions=positions, stock_account=account))
        bar = types.SimpleNamespace(open=10.0, high_limit=11.0, low_limit=9.0,
                                    is_paused=False, volume=100000.0)
        module.init(context)
        return module, context, {module.SYMBOL: bar}, orders

    def test_buy_signal_submits_round_lot(self):
        module, context, bars, orders = self.load([10.0] * 20 + [12.0] * 5)
        module.handle_bar(context, bars)
        self.assertEqual(len(orders), 1)
        self.assertGreater(orders[0][1], 0)
        self.assertEqual(orders[0][1] % 100, 0)

    def test_sell_signal_uses_available_amount(self):
        module, context, bars, orders = self.load([10.0] * 20 + [8.0] * 5,
                                                   held=1000, available=600)
        module.g.want_long = True
        module.handle_bar(context, bars)
        self.assertEqual(orders[0][1], -600)


if __name__ == "__main__":
    unittest.main()
