"""宝石镶嵌与合成系统 - 含7个bug"""
import random
from dataclasses import dataclass, field

@dataclass
class Gem:
    gid: str
    name: str
    level: int
    slot_type: str  # red/blue/yellow/green
    stats: dict = field(default_factory=dict)

class GemSocket:
    def __init__(self, seed=42):
        self.rng = random.Random(seed)
        self.equipment_slots: dict[str, list] = {}  # equip_id -> [Gem|None]

    def combine(self, gems: list[Gem]) -> tuple[Gem | None, str]:
        # bug1: 100%成功
        if len(gems) < 3:
            return None, "need 3 gems"
        result = Gem(f"g{self.rng.randint(1000,9999)}", gems[0].name, gems[0].level + 1, gems[0].slot_type)
        return result, "success"

    def roll_stats(self, level: int) -> dict:
        # bug2: 固定值无浮动
        return {"atk": level * 10}

    def can_socket(self, gem: Gem, slot_type: str) -> bool:
        # bug3: 不检查孔位类型
        return True

    def get_advanced_effect(self, gem: Gem) -> dict:
        # bug4: 高级宝石无专属属性
        return {}

    def get_same_type_limit(self) -> int:
        # bug5: 无数量限制
        return 999

    def remove_gem(self, equip_id: str, slot_index: int) -> Gem | None:
        # bug6: 拆除不返还
        if equip_id in self.equipment_slots and slot_index < len(self.equipment_slots[equip_id]):
            gem = self.equipment_slots[equip_id][slot_index]
            self.equipment_slots[equip_id][slot_index] = None
            return None
        return None

    def get_combine_cost(self, target_level: int) -> int:
        # bug7: 固定消耗
        return 10
