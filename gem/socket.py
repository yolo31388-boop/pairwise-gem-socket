"""宝石镶嵌与合成系统"""
import random
import time
from dataclasses import dataclass, field

ADVANCED_LEVEL = 7          # 达到该等级视为高级宝石，拥有专属词条
SAME_TYPE_LIMIT = 3         # 同类型(同名)宝石在一件装备上的叠加上限
REMOVE_COOLDOWN = 300       # 拆除冷却(秒)，冷却内再次拆除只返还碎片
MISMATCH_DECAY = 0.5        # 孔位不匹配强行镶嵌时的效果衰减比例
PITY_FAILS = 5              # 连续失败达到此次数后保底成功
PITY_BONUS = 0.15           # 每次连续失败增加的成功率
MAX_LEVEL = 10


@dataclass
class Gem:
    gid: str
    name: str
    level: int
    slot_type: str  # red/blue/yellow/green
    stats: dict = field(default_factory=dict)


@dataclass
class GemFragment:
    """宝石碎片：冷却期内拆除的返还物"""
    gid: str
    name: str
    level: int
    slot_type: str
    count: int


# 高级宝石专属词条：随等级成长
_ADVANCED_AFFIX = {
    "red": ("crit_dmg", 5),        # 暴击伤害
    "blue": ("cooldown_reduce", 2),  # 冷却缩减(%)
    "yellow": ("luck", 3),         # 幸运/掉宝
    "green": ("lifesteal", 2),     # 吸血(%)
}
_ADVANCED_NAME = {
    "red": "烈焰·狂暴",
    "blue": "深海·不息",
    "yellow": "雷鸣·天眷",
    "green": "生命·吞噬",
}


class GemSocket:
    def __init__(self, seed=42):
        self.rng = random.Random(seed)
        self.equipment_slots: dict[str, list] = {}  # equip_id -> [Gem|None]
        self.equipment_slot_types: dict[str, list] = {}  # equip_id -> 各孔颜色
        # 合成保底：(name, level, slot_type) -> 连续失败次数
        self._combine_pity: dict[tuple, int] = {}
        # 拆除冷却：equip_id -> 上次完整拆除的时间戳
        self._last_remove_at: dict[str, float] = {}

    # ---------- 合成 ----------
    def base_success_rate(self, target_level: int) -> float:
        """基础成功率：目标等级越高越低"""
        rate = 0.95 - 0.07 * (target_level - 1)
        return max(0.25, min(0.95, rate))

    def combine(self, gems: list[Gem]) -> tuple[Gem | None, str]:
        if len(gems) < 3:
            return None, "need 3 gems"
        first = gems[0]
        if first.level >= MAX_LEVEL:
            return None, "max level reached"
        if any(g.level != first.level or g.name != first.name
               or g.slot_type != first.slot_type for g in gems):
            return None, "gems must be same type and level"

        key = (first.name, first.level, first.slot_type)
        target_level = first.level + 1
        fails = self._combine_pity.get(key, 0)

        guaranteed = fails >= PITY_FAILS - 1
        rate = 1.0 if guaranteed else min(
            1.0, self.base_success_rate(target_level) + fails * PITY_BONUS)

        if guaranteed or self.rng.random() < rate:
            self._combine_pity[key] = 0
            result = Gem(
                f"g{self.rng.randint(1000, 9999)}",
                first.name, target_level, first.slot_type,
                self.roll_stats(target_level),
            )
            effect = self.get_advanced_effect(result)
            if effect:
                result.stats.update(effect)
            return result, "success"

        self._combine_pity[key] = fails + 1
        left = PITY_FAILS - self._combine_pity[key]
        return None, f"combine failed, {left} fails until pity"

    # ---------- 属性浮动 ----------
    def roll_stats(self, level: int) -> dict:
        """基础值上下浮动 ±20%，区分极品/优秀/普通/次品"""
        base = level * 10
        factor = self.rng.uniform(0.8, 1.2)
        if factor >= 1.12:
            quality, quality_cn = "premium", "极品"
        elif factor >= 1.02:
            quality, quality_cn = "fine", "优秀"
        elif factor >= 0.9:
            quality, quality_cn = "normal", "普通"
        else:
            quality, quality_cn = "inferior", "次品"
        return {
            "atk": max(1, round(base * factor)),
            "quality": quality,
            "quality_cn": quality_cn,
            "variance": round((factor - 1.0) * 100),
        }

    # ---------- 孔位 ----------
    def can_socket(self, gem: Gem, slot_type: str) -> bool:
        """宝石颜色必须与孔位一致（万能孔 any 除外）"""
        return slot_type == "any" or gem.slot_type == slot_type

    def socket_gem(self, equip_id: str, slot_index: int,
                   gem: Gem, force: bool = False) -> str:
        """镶嵌：校验孔位颜色与同类型叠加上限。

        force=True 时允许颜色不匹配，但宝石效果衰减；正常情况下不匹配直接拒绝。
        """
        slots = self.equipment_slots.get(equip_id)
        if not slots or not (0 <= slot_index < len(slots)):
            return "slot not found"
        if slots[slot_index] is not None:
            return "slot occupied"

        same_type = sum(1 for g in slots
                        if g is not None and g.name == gem.name)
        if same_type >= self.get_same_type_limit():
            return "same type limit reached"

        slot_type = self._slot_color(equip_id, slot_index)
        if not self.can_socket(gem, slot_type) and not force:
            return "slot type mismatch"

        if force and not self.can_socket(gem, slot_type):
            gem.stats = {**gem.stats, "decayed": True}
        slots[slot_index] = gem
        return "success"

    def _slot_color(self, equip_id: str, slot_index: int) -> str:
        colors = self.equipment_slot_types.get(equip_id)
        if colors and slot_index < len(colors):
            return colors[slot_index]
        return "any"

    def effective_stats(self, gem: Gem, slot_type: str) -> dict:
        """宝石在指定孔位中的实际生效属性，不匹配时数值衰减"""
        stats = dict(gem.stats)
        if self.can_socket(gem, slot_type):
            return stats
        for key, value in list(stats.items()):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                stats[key] = round(value * MISMATCH_DECAY, 2)
        stats["decayed"] = True
        return stats

    # ---------- 高级宝石 ----------
    def get_advanced_effect(self, gem: Gem) -> dict:
        """高级宝石的专属词条；低级宝石返回空"""
        if gem.level < ADVANCED_LEVEL:
            return {}
        affix = _ADVANCED_AFFIX.get(gem.slot_type)
        if not affix:
            return {}
        key, per_level = affix
        return {
            key: per_level * gem.level,
            "unique_affix": _ADVANCED_NAME.get(gem.slot_type, "专属词条"),
        }

    def get_set_effect(self, gems: list[Gem]) -> dict:
        """套装效果：同类型高级宝石达到 2/3 件时激活"""
        advanced = [g for g in gems if g is not None and g.level >= ADVANCED_LEVEL]
        bonus: dict = {}
        for slot_type in ("red", "blue", "yellow", "green"):
            count = sum(1 for g in advanced if g.slot_type == slot_type)
            if count >= 3:
                bonus[f"{slot_type}_set_3"] = {"all_stats_pct": 15}
            elif count >= 2:
                bonus[f"{slot_type}_set_2"] = {"all_stats_pct": 8}
        return bonus

    # ---------- 叠加上限 ----------
    def get_same_type_limit(self) -> int:
        return SAME_TYPE_LIMIT

    # ---------- 拆除返还 ----------
    def remove_gem(self, equip_id: str, slot_index: int,
                   now: float | None = None) -> Gem | GemFragment | None:
        """拆除返还宝石；冷却内再次拆除只返还碎片"""
        if now is None:
            now = time.monotonic()
        slots = self.equipment_slots.get(equip_id)
        if not slots or slot_index >= len(slots):
            return None
        gem = slots[slot_index]
        if gem is None:
            return None
        slots[slot_index] = None

        last = self._last_remove_at.get(equip_id)
        if last is not None and now - last < REMOVE_COOLDOWN:
            return GemFragment(
                gem.gid, gem.name, gem.level, gem.slot_type,
                gem.level * 2,
            )

        self._last_remove_at[equip_id] = now
        return gem

    def remove_cooldown_left(self, equip_id: str,
                             now: float | None = None) -> float:
        if now is None:
            now = time.monotonic()
        last = self._last_remove_at.get(equip_id)
        if last is None:
            return 0.0
        return max(0.0, REMOVE_COOLDOWN - (now - last))

    # ---------- 合成材料 ----------
    def get_combine_cost(self, target_level: int) -> int:
        """材料消耗随目标等级指数递增：10 * 2^(L-1)"""
        if target_level < 1:
            raise ValueError("target_level must be >= 1")
        return 10 * (2 ** (target_level - 1))
