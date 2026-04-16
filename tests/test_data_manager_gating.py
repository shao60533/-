"""DataManager provider master-switch tests (Phase E.1).

The legacy DataManager is still used by some routes pending full migration
to DataRouter — verify it honors the new `providers.*_enabled` flags so
cloud deployments can disable IB/Polygon without touching the per-provider
.enabled keys.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from stock_trading_system.data.data_manager import DataManager


def _config(ib_enabled=False, polygon_enabled=False):
    return {
        "ib": {"enabled": True, "host": "localhost", "port": 7496},
        "providers": {
            "ib_enabled": ib_enabled,
            "polygon_enabled": polygon_enabled,
        },
    }


def test_master_switch_skips_ib_even_when_per_provider_enabled():
    cfg = _config(ib_enabled=False, polygon_enabled=True)
    with patch("stock_trading_system.data.data_manager.IBProvider") as IB, \
         patch("stock_trading_system.data.data_manager.PolygonProvider") as PG, \
         patch("stock_trading_system.data.data_manager.YFinanceProvider"), \
         patch("stock_trading_system.data.data_manager.AkShareProvider"), \
         patch("stock_trading_system.data.data_manager.QwenProvider"):
        ib_inst = IB.return_value
        ib_inst.get_stock_price = MagicMock(return_value={"last": 1})
        pg_inst = PG.return_value
        pg_inst.get_stock_price = MagicMock(return_value={"last": 2})

        dm = DataManager(cfg)
        # Reset auto-skip counters so we'd otherwise call providers.
        dm._fail_count = {}
        dm.get_price("AAPL")

        ib_inst.get_stock_price.assert_not_called()
        pg_inst.get_stock_price.assert_called_once()


def test_master_switch_skips_polygon():
    cfg = _config(ib_enabled=False, polygon_enabled=False)
    with patch("stock_trading_system.data.data_manager.IBProvider"), \
         patch("stock_trading_system.data.data_manager.PolygonProvider") as PG, \
         patch("stock_trading_system.data.data_manager.YFinanceProvider") as YF, \
         patch("stock_trading_system.data.data_manager.AkShareProvider"), \
         patch("stock_trading_system.data.data_manager.QwenProvider"):
        pg_inst = PG.return_value
        pg_inst.get_stock_price = MagicMock(return_value={"last": 2})
        yf_inst = YF.return_value
        yf_inst.get_stock_price = MagicMock(return_value={"last": 3})

        dm = DataManager(cfg)
        dm._fail_count = {}
        result = dm.get_price("AAPL")

        pg_inst.get_stock_price.assert_not_called()
        yf_inst.get_stock_price.assert_called_once()
        assert result["last"] == 3


def test_master_switch_gates_history_too():
    cfg = _config(ib_enabled=False, polygon_enabled=False)
    with patch("stock_trading_system.data.data_manager.IBProvider"), \
         patch("stock_trading_system.data.data_manager.PolygonProvider") as PG, \
         patch("stock_trading_system.data.data_manager.YFinanceProvider") as YF, \
         patch("stock_trading_system.data.data_manager.AkShareProvider"), \
         patch("stock_trading_system.data.data_manager.QwenProvider"):
        import pandas as pd
        pg_inst = PG.return_value
        pg_inst.get_stock_history = MagicMock(return_value=pd.DataFrame({"close": [1]}))
        yf_inst = YF.return_value
        yf_inst.get_stock_history = MagicMock(
            return_value=pd.DataFrame({"close": [2]})
        )

        dm = DataManager(cfg)
        df = dm.get_history("AAPL", period="1mo")

        pg_inst.get_stock_history.assert_not_called()
        yf_inst.get_stock_history.assert_called_once()
        assert df.iloc[0]["close"] == 2


def test_master_switch_default_keeps_legacy_behaviour():
    """Without `providers` block, both providers default to enabled."""
    cfg = {"ib": {"enabled": False}}  # no providers key
    with patch("stock_trading_system.data.data_manager.IBProvider"), \
         patch("stock_trading_system.data.data_manager.PolygonProvider") as PG, \
         patch("stock_trading_system.data.data_manager.YFinanceProvider"), \
         patch("stock_trading_system.data.data_manager.AkShareProvider"), \
         patch("stock_trading_system.data.data_manager.QwenProvider"):
        pg_inst = PG.return_value
        pg_inst.get_stock_price = MagicMock(return_value={"last": 9})
        dm = DataManager(cfg)
        dm._fail_count = {}
        result = dm.get_price("AAPL")
        # Polygon still gets called when no master switch is set
        pg_inst.get_stock_price.assert_called_once()
        assert result["last"] == 9
