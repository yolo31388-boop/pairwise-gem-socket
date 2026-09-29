"""宝石镶嵌与合成系统 - 红态测试"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gem.socket import GemSocket, Gem

class TestCombineFailure:
    def test_combine_can_fail(self):
        gs = GemSocket(seed=1)
        gems = [Gem(f"g{i}", "ruby", 5, "red") for i in range(3)]
        results = [gs.combine(gems) for _ in range(20)]
        success = sum(1 for r, _ in results if r)
        assert success < 20  # bug1: 全成功

class TestStatsVariance:
    def test_same_level_gems_have_variance(self):
        gs = GemSocket(seed=42)
        stats_list = [gs.roll_stats(5) for _ in range(20)]
        values = [s["atk"] for s in stats_list]
        assert len(set(values)) > 1  # bug2: 都是50

class TestSlotType:
    def test_red_gem_cannot_go_blue_slot(self):
        gs = GemSocket()
        gem = Gem("g1", "ruby", 5, "red")
        assert gs.can_socket(gem, "blue") == False  # bug3: True
        assert gs.can_socket(gem, "red") == True

class TestAdvancedEffect:
    def test_high_level_gem_has_unique_effect(self):
        gs = GemSocket()
        gem = Gem("g1", "ruby", 10, "red")
        effect = gs.get_advanced_effect(gem)
        assert effect != {}  # bug4: 空

class TestSameTypeLimit:
    def test_same_type_gem_has_limit(self):
        gs = GemSocket()
        assert gs.get_same_type_limit() < 5  # bug5: 999

class TestRemoveRefund:
    def test_removed_gem_returned(self):
        gs = GemSocket()
        gem = Gem("g1", "ruby", 5, "red")
        gs.equipment_slots["e1"] = [gem]
        removed = gs.remove_gem("e1", 0)
        assert removed is not None  # bug6: None
        assert removed.gid == "g1"

class TestCombineCost:
    def test_higher_level_costs_more(self):
        gs = GemSocket()
        c1 = gs.get_combine_cost(1)
        c10 = gs.get_combine_cost(10)
        assert c10 > c1  # bug7: 都是10
