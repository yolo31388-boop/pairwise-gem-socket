"""宝石镶嵌与合成系统。

机制总览：
- 合成有成功率，目标等级越高成功率越低，设成功率地板 + 连续失败保底。
- 宝石属性在基础值上下浮动，区分次品 / 普通 / 精品 / 极品。
- 镶嵌校验孔位颜色，颜色不符默认拒绝，强制插入只生效 50%。
- 7 级及以上为高级宝石，带专属词条；同色高级宝石凑 2/4 件触发套装。
- 同类型宝石每件装备有数量上限，超出不再叠加。
- 拆除返还宝石本体（有冷却）；也可粉碎成碎片。
- 合成材料随目标等级指数递增。
"""
import random
import time
from dataclasses import dataclass, field

SLOT_RED = "red"
SLOT_BLUE = "blue"
SLOT_YELLOW = "yellow"
SLOT_GREEN = "green"
VALID_SLOT_TYPES = (SLOT_RED, SLOT_BLUE, SLOT_YELLOW, SLOT_GREEN)

# 目标等级 -> 基础成功率，等级越高越低
BASE_SUCCESS_RATE = {
    1: 1.00,
    2: 1.00,
    3: 0.95,
    4: 0.90,
    5: 0.85,
    6: 0.78,
    7: 0.70,
    8: 0.60,
    9: 0.50,
    10: 0.40,
}
MIN_SUCCESS_RATE = 0.20        # 成功率地板（等级保底）
PITY_FAIL_THRESHOLD = 3        # 连续失败达到此次数后，下次合成必成（次数保底）

STAT_VARIANCE = 0.20           # 属性在基础值 ±20% 浮动
GRADE_FAULTY = "faulty"        # 次品
GRADE_NORMAL = "normal"
GRADE_FINE = "fine"            # 精品
GRADE_PERFECT = "perfect"      # 极品
_GRADE_BANDS = (
    (0.90, GRADE_FAULTY),
    (1.05, GRADE_NORMAL),
    (1.15, GRADE_FINE),
)

ADVANCED_LEVEL = 7             # 达到该等级解锁专属词条与套装
SAME_TYPE_LIMIT = 3            # 同类型宝石每件装备最多镶嵌数
REMOVE_COOLDOWN = 60.0         # 同一孔位拆除冷却（秒）
MISMATCH_EFFECT_RATIO = 0.5    # 颜色不符强制插入时的生效比例

ADVANCED_EFFECTS = {
    SLOT_RED: {"crit_dmg": 0.15, "berserk": 0.10},
    SLOT_BLUE: {"cd_reduce": 0.10, "frost_shield": 0.15},
    SLOT_YELLOW: {"gold_find": 0.20, "lucky_strike": 0.08},
    SLOT_GREEN: {"lifesteal": 0.08, "thorn_poison": 0.12},
}

# 同色高级宝石的套装效果（2 件套 / 4 件套）
SET_BONUSES = {
    2: {
        SLOT_RED: {"set_crit_rate": 0.05},
        SLOT_BLUE: {"set_dmg_reduce": 0.08},
        SLOT_YELLOW: {"set_drop_rate": 0.15},
        SLOT_GREEN: {"set_hp_regen": 0.10},
    },
    4: {
        SLOT_RED: {"set_berserk_up": 0.25},
        SLOT_BLUE: {"set_mana_shield": 0.20},
        SLOT_YELLOW: {"set_luck_up": 0.30},
        SLOT_GREEN: {"set_nature_blessing": 0.25},
    },
}


@dataclass
class Gem:
    gid: str
    name: str
    level: int
    slot_type: str  # red/blue/yellow/green
    stats: dict = field(default_factory=dict)
    grade: str = GRADE_NORMAL


class GemSocket:
    def __init__(self, seed=42):
        self.rng = random.Random(seed)
        self.equipment_slots: dict[str, list] = {}  # equip_id -> [Gem|None]
        self.equipment_slot_types: dict[str, list[str]] = {}
        self._combine_fail_streak = 0
        self._remove_cooldown_until: dict[tuple[str, int], float] = {}
        self._mismatched: set[tuple[str, int]] = set()
        self._clock = time.monotonic
        self._gid_seq = 0

    # ---------- 合成 ----------

    def get_success_rate(self, target_level: int) -> float:
        """目标等级越高成功率越低，不低于成功率地板。"""
        rate = BASE_SUCCESS_RATE.get(target_level, MIN_SUCCESS_RATE)
        return max(MIN_SUCCESS_RATE, min(1.0, rate))

    def get_combine_cost(self, target_level: int) -> int:
        """材料消耗按目标等级指数递增：10, 20, 40, ..., 5120。"""
        if target_level < 1:
            raise ValueError("target_level must be >= 1")
        return 10 * (2 ** (target_level - 1))

    def _new_gid(self) -> str:
        self._gid_seq += 1
        return f"g{self.rng.randint(1000, 9999)}_{self._gid_seq}"

    def combine(self, gems: list[Gem], materials: int | None = None) -> tuple[Gem | None, str]:
        if len(gems) < 3:
            return None, "need 3 gems"
        base = gems[0]
        if any(g.level != base.level or g.slot_type != base.slot_type for g in gems):
            return None, "gems must share level and slot type"

        target_level = base.level + 1
        cost = self.get_combine_cost(target_level)
        if materials is not None and materials < cost:
            return None, f"need {cost} materials"

        forced_by_pity = self._combine_fail_streak >= PITY_FAIL_THRESHOLD
        if not forced_by_pity and self.rng.random() >= self.get_success_rate(target_level):
            self._combine_fail_streak += 1
            return None, "combine failed"

        self._combine_fail_streak = 0
        result = Gem(
            self._new_gid(),
            base.name,
            target_level,
            base.slot_type,
            stats=self.roll_stats(target_level),
        )
        result.grade = self.grade_of(result)
        effect = self.get_advanced_effect(result)
        if effect:
            result.stats.update(effect)
        return result, "success"

    # ---------- 属性浮动 ----------

    def roll_stats(self, level: int) -> dict:
        """基础值 level*10，在 ±20% 区间浮动。"""
        factor = 1.0 + self.rng.uniform(-STAT_VARIANCE, STAT_VARIANCE)
        return {"atk": max(1, round(level * 10 * factor))}

    @staticmethod
    def grade_from_factor(factor: float) -> str:
        for upper, grade in _GRADE_BANDS:
            if factor < upper:
                return grade
        return GRADE_PERFECT

    def grade_of(self, gem: Gem) -> str:
        base = max(1, gem.level * 10)
        factor = gem.stats.get("atk", base) / base
        return self.grade_from_factor(factor)

    # ---------- 镶嵌 ----------

    def can_socket(self, gem: Gem, slot_type: str) -> bool:
        """仅允许宝石颜色与孔位颜色一致。"""
        return slot_type in VALID_SLOT_TYPES and gem.slot_type == slot_type

    def get_same_type_limit(self) -> int:
        return SAME_TYPE_LIMIT

    def register_equipment(self, equip_id: str, slot_types: list[str]) -> None:
        invalid = [s for s in slot_types if s not in VALID_SLOT_TYPES]
        if invalid:
            raise ValueError(f"invalid slot types: {invalid}")
        self.equipment_slot_types[equip_id] = list(slot_types)
        self.equipment_slots[equip_id] = [None] * len(slot_types)

    def _count_same_type(self, equip_id: str, gem: Gem) -> int:
        return sum(
            1
            for equipped in self.equipment_slots.get(equip_id, [])
            if isinstance(equipped, Gem) and equipped.name == gem.name
        )

    def socket_gem(self, equip_id: str, slot_index: int, gem: Gem, force: bool = False) -> tuple[bool, str]:
        slots = self.equipment_slots.get(equip_id)
        slot_types = self.equipment_slot_types.get(equip_id)
        if slots is None or slot_index >= len(slots) or slot_index < 0:
            return False, "equipment or slot not found"
        if slots[slot_index] is not None:
            return False, "slot occupied"

        matched = self.can_socket(gem, slot_types[slot_index])
        if not matched and not force:
            return False, "slot type mismatch"

        if self._count_same_type(equip_id, gem) >= self.get_same_type_limit():
            return False, "same type limit reached"

        slots[slot_index] = gem
        if not matched:
            self._mismatched.add((equip_id, slot_index))
        return True, "socketed" if matched else "socketed with penalty"

    # ---------- 高级词条与套装 ----------

    def get_advanced_effect(self, gem: Gem) -> dict:
        """7 级及以上获得专属词条，数值随等级继续成长。"""
        if gem.level < ADVANCED_LEVEL:
            return {}
        scale = 1.0 + 0.1 * (gem.level - ADVANCED_LEVEL)
        return {
            key: (round(value * scale, 4) if isinstance(value, float) else value)
            for key, value in ADVANCED_EFFECTS.get(gem.slot_type, {}).items()
        }

    def get_set_effects(self, equip_id: str) -> dict:
        """同色高级宝石凑齐 2 / 4 件触发的套装效果。"""
        counts: dict[str, int] = {}
        for gem in self.equipment_slots.get(equip_id, []):
            if isinstance(gem, Gem) and gem.level >= ADVANCED_LEVEL:
                counts[gem.slot_type] = counts.get(gem.slot_type, 0) + 1

        bonuses: dict = {}
        for need, table in SET_BONUSES.items():
            for slot_type, count in counts.items():
                if count >= need:
                    bonuses.update(table.get(slot_type, {}))
        return bonuses

    def aggregate_stats(self, equip_id: str) -> dict:
        """汇总装备上全部生效属性；错色强制插入只按衰减比例生效。"""
        total: dict = {}
        for index, gem in enumerate(self.equipment_slots.get(equip_id, [])):
            if not isinstance(gem, Gem):
                continue
            ratio = MISMATCH_EFFECT_RATIO if (equip_id, index) in self._mismatched else 1.0
            for key, value in gem.stats.items():
                if isinstance(value, (int, float)):
                    total[key] = round(total.get(key, 0) + value * ratio, 4)
        total.update(self.get_set_effects(equip_id))
        return total

    # ---------- 拆除 / 粉碎 ----------

    def get_remove_cooldown_remaining(self, equip_id: str, slot_index: int, now: float | None = None) -> float:
        until = self._remove_cooldown_until.get((equip_id, slot_index))
        if until is None:
            return 0.0
        current = self._clock() if now is None else now
        return max(0.0, until - current)

    def remove_gem(self, equip_id: str, slot_index: int, now: float | None = None) -> Gem | None:
        """拆除返还宝石本体；同一孔位在冷却期内无法再次拆除。"""
        slots = self.equipment_slots.get(equip_id)
        if not slots or slot_index >= len(slots) or slot_index < 0:
            return None
        gem = slots[slot_index]
        if gem is None:
            return None

        current = self._clock() if now is None else now
        if self.get_remove_cooldown_remaining(equip_id, slot_index, current) > 0:
            return None

        slots[slot_index] = None
        self._mismatched.discard((equip_id, slot_index))
        self._remove_cooldown_until[(equip_id, slot_index)] = current + REMOVE_COOLDOWN
        return gem

    def crush_gem(self, equip_id: str, slot_index: int, now: float | None = None) -> int:
        """粉碎孔位中的宝石换取碎片（等级越高碎片越多），同样受拆除冷却限制。"""
        gem = self.remove_gem(equip_id, slot_index, now)
        if gem is None:
            return 0
        return gem.level * 5
