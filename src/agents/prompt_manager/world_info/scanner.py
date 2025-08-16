import re
import random
import time
from typing import List, Dict, Set, Optional, Any
from enum import Enum
from dataclasses import dataclass
from .models import WorldInfoEntry, WorldInfoBook
from .manager import DBManager

class ScanState(Enum):
    """扫描状态枚举"""
    INITIAL = "initial"
    RECURSION = "recursion"
    MIN_ACTIVATIONS = "min_activations"
    NONE = "none"

class WorldInfoLogic(Enum):
    """世界信息逻辑枚举"""
    AND_ALL = 0
    AND_ANY = 1
    NOT_ALL = 2
    NOT_ANY = 3

class WorldInfoPosition(Enum):
    """世界信息位置枚举"""
    BEFORE = 0
    AFTER = 1
    EM_TOP = 2
    EM_BOTTOM = 3
    AN_TOP = 4
    AN_BOTTOM = 5
    AT_DEPTH = 6

@dataclass
class WIGlobalScanData:
    """全局扫描数据"""
    trigger: str = "chat"
    character_name: str = ""
    character_tags: List[str] = None
    
    def __post_init__(self):
        if self.character_tags is None:
            self.character_tags = []

@dataclass
class WIActivated:
    """激活的世界信息结果"""
    world_info_before: str = ""
    world_info_before_tokens: int = 0
    world_info_after: str = ""
    world_info_after_tokens: int = 0
    wi_depth_entries: List[Dict] = None
    em_entries: List[Dict] = None
    an_before_entries: List[str] = None
    an_after_entries: List[str] = None
    all_activated_entries: Set[WorldInfoEntry] = None
    
    def __post_init__(self):
        if self.wi_depth_entries is None:
            self.wi_depth_entries = []
        if self.em_entries is None:
            self.em_entries = []
        if self.an_before_entries is None:
            self.an_before_entries = []
        if self.an_after_entries is None:
            self.an_after_entries = []
        if self.all_activated_entries is None:
            self.all_activated_entries = set()

class WorldInfoBuffer:
    """世界信息缓冲区"""
    def __init__(self, chat: List[str], global_scan_data: WIGlobalScanData):
        self.chat = chat
        self.global_scan_data = global_scan_data
        self.injected_text = ""
        self.recursive_text = ""
        self.external_effects = {}
        self.scan_depth = 0
        
    def get(self, entry: WorldInfoEntry, scan_state: ScanState) -> str:
        """获取要扫描的文本"""
        text = "".join(self.chat[-1000:]) if self.chat else ""  # 限制扫描范围
        if self.injected_text:
            text += "\n" + self.injected_text
        if self.recursive_text and scan_state == ScanState.RECURSION:
            text += "\n" + self.recursive_text
        return text
    
    def add_inject(self, text: str):
        """添加注入文本"""
        self.injected_text += "\n" + text
    
    def add_recurse(self, text: str):
        """添加递归文本"""
        self.recursive_text += "\n" + text
    
    def get_externally_activated(self, entry: WorldInfoEntry) -> Optional[WorldInfoEntry]:
        """获取外部激活的条目"""
        return self.external_effects.get(f"{entry.world_info_book_id}.{entry.uid}")
    
    def match_keys(self, text: str, key: str, entry: WorldInfoEntry) -> bool:
        """匹配关键词"""
        if not key:
            return False
        
        if entry.caseSensitive:
            return key in text
        else:
            return key.lower() in text.lower()
    
    def has_recurse(self) -> bool:
        """是否有递归文本"""
        return bool(self.recursive_text)
    
    def get_depth(self) -> int:
        """获取扫描深度"""
        return self.scan_depth
    
    def advance_scan(self):
        """推进扫描深度"""
        self.scan_depth += 1
    
    def reset_external_effects(self):
        """重置外部效果"""
        self.external_effects = {}

class WorldInfoTimedEffects:
    """世界信息时间效果"""
    def __init__(self, chat: List[str], entries: List[WorldInfoEntry]):
        self.chat = chat
        self.entries = entries
        self.active_effects = {}
        
    def is_effect_active(self, effect_type: str, entry: WorldInfoEntry) -> bool:
        """检查效果是否激活"""
        effect_key = f"{entry.world_info_book_id}.{entry.uid}.{effect_type}"
        return effect_key in self.active_effects
    
    def check_timed_effects(self):
        """检查时间效果"""
        # 这里可以添加时间效果的检查逻辑
        pass
    
    def set_timed_effects(self, entries: List[WorldInfoEntry]):
        """设置时间效果"""
        # 这里可以添加时间效果的设置逻辑
        pass
    
    def clean_up(self):
        """清理时间效果"""
        self.active_effects = {}

class WorldInfoScanner:
    """
    Scans text to find and activate World Info entries based on keywords.
    """
    def __init__(self, activate_world_books: List[str] = None, activate_keys: List[str] = None):
        self.entries = []
        self.activate_keys = activate_keys
        self.activate_world_books = activate_world_books
    
    def substitute_params(self, text: str) -> str:
        """替换参数"""
        # 这里可以添加参数替换逻辑
        return text
    
    def get_token_count(self, text: str) -> int:
        """获取文本的token数量"""
        # 简单的token计数，可以根据需要改进
        return len(text.split())
    
    def filter_by_inclusion_groups(self, entries: List[WorldInfoEntry], 
                                 all_activated_entries: Dict[str, WorldInfoEntry],
                                 buffer: WorldInfoBuffer, scan_state: ScanState,
                                 timed_effects: WorldInfoTimedEffects):
        """按包含组过滤条目"""
        # 这里可以添加组过滤逻辑
        pass

    def set_activate_keys(self, activate_keys: List[str]):
        """设置激活的关键词"""
        self.activate_keys = activate_keys
    
    async def check_world_info(self, chat: List[str], max_context: int, 
                             global_scan_data: Optional[WIGlobalScanData] = None) -> WIActivated:
        """
        执行世界信息扫描并返回激活的世界信息
        
        Args:
            chat: 要扫描的聊天消息列表（倒序）
            max_context: 生成的最大上下文大小
            global_scan_data: 聊天无关的上下文扫描数据
        
        Returns:
            WIActivated: 激活的世界信息
        """
        if global_scan_data is None:
            global_scan_data = WIGlobalScanData()
        
        buffer = WorldInfoBuffer(chat, global_scan_data)
        
        print(f"[WI] --- START WI SCAN (on {len(chat)} messages, trigger = {global_scan_data.trigger}) ---")
        
        # 初始化变量
        scan_state = ScanState.INITIAL
        token_budget_overflowed = False
        count = 0
        all_activated_entries = {}
        failed_probability_checks = set()
        all_activated_text = ""
        
        # 计算预算
        world_info_budget = 10  # 默认10%
        world_info_budget_cap = 1000  # 默认1000 tokens
        budget = max(1, round(world_info_budget * max_context / 100))
        
        if world_info_budget_cap > 0 and budget > world_info_budget_cap:
            print(f"[WI] Budget {budget} exceeds cap {world_info_budget_cap}, using cap")
            budget = world_info_budget_cap
        
        print(f"[WI] Context size: {max_context}; WI budget: {budget} (max% = {world_info_budget}%, cap = {world_info_budget_cap})")
        
        # 获取排序的条目
        sorted_entries = sorted(self.entries, key=lambda x: (x.order, x.id))
        timed_effects = WorldInfoTimedEffects(chat, sorted_entries)
        
        timed_effects.check_timed_effects()
        
        if not sorted_entries:
            return WIActivated()
        
        # 获取可用的递归延迟级别
        available_recursion_delay_levels = sorted(list(set([
            entry.delayUntilRecursion for entry in sorted_entries 
            if entry.delayUntilRecursion
        ])))
        
        current_recursion_delay_level = available_recursion_delay_levels.pop(0) if available_recursion_delay_levels else 0
        
        print(f"[WI] --- SEARCHING ENTRIES (on {len(sorted_entries)} entries) ---")
        
        world_info_max_recursion_steps = 10  # 默认最大递归步数
        world_info_recursive = True  # 默认启用递归
        world_info_min_activations = 0  # 默认最小激活数
        world_info_min_activations_depth_max = 0  # 默认最小激活深度最大值
        
        while scan_state != ScanState.NONE:
            # 检查最大递归步数
            if world_info_max_recursion_steps and world_info_max_recursion_steps <= count:
                print(f'[WI] Search stopped by reaching max recursion steps {world_info_max_recursion_steps}')
                break
            
            count += 1
            print(f"[WI] --- LOOP #{count} START ---")
            print(f'[WI] Scan state: {scan_state.value}')
            
            next_scan_state = ScanState.NONE
            activated_now = set()
            
            for entry in sorted_entries:
                # 跳过已处理的条目
                if entry in failed_probability_checks or f"{entry.world_info_book_id}.{entry.uid}" in all_activated_entries:
                    continue
                
                # 检查触发器过滤
                if entry.triggers and global_scan_data.trigger not in entry.triggers:
                    print(f"[WI] Entry {entry.uid} skipped by generation type trigger filter")
                    continue
                
                # 检查角色过滤
                if entry.characterFilter:
                    char_filter = entry.characterFilter
                    if char_filter.get('names') and global_scan_data.character_name:
                        name_included = global_scan_data.character_name in char_filter['names']
                        filtered = char_filter.get('isExclude', False) and name_included or not name_included
                        if filtered:
                            print(f"[WI] Entry {entry.uid} filtered out by character")
                            continue
                
                # 检查时间效果
                is_sticky = timed_effects.is_effect_active('sticky', entry)
                is_cooldown = timed_effects.is_effect_active('cooldown', entry)
                is_delay = timed_effects.is_effect_active('delay', entry)
                
                if is_delay:
                    print(f"[WI] Entry {entry.uid} suppressed by delay")
                    continue
                
                if is_cooldown and not is_sticky:
                    print(f"[WI] Entry {entry.uid} suppressed by cooldown")
                    continue
                
                # 检查递归延迟
                if scan_state != ScanState.RECURSION and entry.delayUntilRecursion and not is_sticky:
                    print(f"[WI] Entry {entry.uid} suppressed by delay until recursion")
                    continue
                
                if (scan_state == ScanState.RECURSION and entry.delayUntilRecursion and 
                    entry.delayUntilRecursion > current_recursion_delay_level and not is_sticky):
                    print(f"[WI] Entry {entry.uid} suppressed by delay until recursion level")
                    continue
                
                if scan_state == ScanState.RECURSION and world_info_recursive and entry.excludeRecursion and not is_sticky:
                    print(f"[WI] Entry {entry.uid} suppressed by exclude recursion")
                    continue
                
                # 检查常驻条目
                if entry.constant:
                    print(f"[WI] Entry {entry.uid} activated because of constant")
                    activated_now.add(entry)
                    continue
                
                if is_sticky:
                    print(f"[WI] Entry {entry.uid} activated because active sticky")
                    activated_now.add(entry)
                    continue
                
                # 检查关键词
                if not entry.keys or len(entry.keys) == 0:
                    print(f"[WI] Entry {entry.uid} has no keys defined, skipped")
                    continue
                
                text_to_scan = buffer.get(entry, scan_state)
                
                # 检查主关键词
                primary_key_match = None
                for key in entry.keys:
                    substituted = self.substitute_params(key)
                    if substituted and buffer.match_keys(text_to_scan, substituted.strip(), entry):
                        primary_key_match = key
                        break
                
                if not primary_key_match:
                    continue
                
                # 检查次级关键词
                has_secondary_keywords = (entry.selective and entry.keysecondary and len(entry.keysecondary) > 0)
                
                if not has_secondary_keywords:
                    print(f"[WI] Entry {entry.uid} activated by primary key match: {primary_key_match}")
                    activated_now.add(entry)
                    continue
                
                # 处理次级关键词逻辑
                selective_logic = entry.selectiveLogic or 0
                print(f"[WI] Entry {entry.uid} with primary key match {primary_key_match} has secondary keywords. Checking with logic {selective_logic}")
                
                def match_secondary_keys() -> bool:
                    has_any_match = False
                    has_all_match = True
                    
                    for key_secondary in entry.keysecondary:
                        secondary_substituted = self.substitute_params(key_secondary)
                        has_secondary_match = secondary_substituted and buffer.match_keys(text_to_scan, secondary_substituted.strip(), entry)
                        
                        if has_secondary_match:
                            has_any_match = True
                        else:
                            has_all_match = False
                        
                        # AND ANY 逻辑
                        if selective_logic == WorldInfoLogic.AND_ANY.value and has_secondary_match:
                            print(f"[WI] Entry {entry.uid} activated. (AND ANY) Found match secondary keyword: {secondary_substituted}")
                            return True
                        
                        # NOT ALL 逻辑
                        if selective_logic == WorldInfoLogic.NOT_ALL.value and not has_secondary_match:
                            print(f"[WI] Entry {entry.uid} activated. (NOT ALL) Found not matching secondary keyword: {secondary_substituted}")
                            return True
                    
                    # NOT ANY 逻辑
                    if selective_logic == WorldInfoLogic.NOT_ANY.value and not has_any_match:
                        print(f"[WI] Entry {entry.uid} activated. (NOT ANY) No secondary keywords found")
                        return True
                    
                    # AND ALL 逻辑
                    if selective_logic == WorldInfoLogic.AND_ALL.value and has_all_match:
                        print(f"[WI] Entry {entry.uid} activated. (AND ALL) All secondary keywords found")
                        return True
                    
                    return False
                
                if match_secondary_keys():
                    activated_now.add(entry)
                else:
                    print(f"[WI] Entry {entry.uid} skipped. Secondary keywords not satisfied")
                    continue
            
            print(f"[WI] Search done. Found {len(activated_now)} possible entries.")
            
            # 排序条目
            new_entries = sorted(activated_now, key=lambda x: (
                not timed_effects.is_effect_active('sticky', x),
                sorted_entries.index(x)
            ))
            
            new_content = ""
            text_to_scan_tokens = self.get_token_count(all_activated_text)
            
            self.filter_by_inclusion_groups(new_entries, all_activated_entries, buffer, scan_state, timed_effects)
            
            print("[WI] --- PROBABILITY CHECKS ---")
            if not new_entries:
                print("[WI] No probability checks to do")
            
            for entry in new_entries:
                def verify_probability() -> bool:
                    if not entry.useProbability or entry.probability == 100:
                        print(f"[WI] Entry {entry.uid} does not use probability")
                        return True
                    
                    is_sticky = timed_effects.is_effect_active('sticky', entry)
                    if is_sticky:
                        print(f"[WI] Entry {entry.uid} is sticky, does not need to re-roll probability")
                        return True
                    
                    roll_value = random.random() * 100
                    if roll_value <= entry.probability:
                        print(f"[WI] Entry {entry.uid} passed probability check of {entry.probability}%")
                        return True
                    
                    failed_probability_checks.add(entry)
                    return False
                
                if not verify_probability():
                    print(f"[WI] Entry {entry.uid} failed probability check, removing from activated entries")
                    continue
                
                # 替换宏
                entry.content = self.substitute_params(entry.content)
                new_content += f"{entry.content}\n"
                
                if (text_to_scan_tokens + self.get_token_count(new_content)) >= budget:
                    print("[WI] --- BUDGET OVERFLOW CHECK ---")
                    print(f"[WI] budget of {budget} reached, stopping after {len(all_activated_entries)} entries")
                    token_budget_overflowed = True
                    break
                
                all_activated_entries[f"{entry.world_info_book_id}.{entry.uid}"] = entry
                print(f"[WI] Entry {entry.uid} activation successful, adding to prompt")
            
            successful_new_entries = [e for e in new_entries if e not in failed_probability_checks]
            successful_new_entries_for_recursion = [e for e in successful_new_entries if not e.preventRecursion]
            
            print(f"[WI] --- LOOP #{count} RESULT ---")
            if not new_entries:
                print("[WI] No new entries activated.")
            elif not successful_new_entries:
                print("[WI] Probability checks failed for all activated entries. No new entries activated.")
            else:
                print(f"[WI] Successfully activated {len(successful_new_entries)} new entries to prompt. {len(all_activated_entries)} total entries activated.")
            
            # 决定下一个扫描状态
            if world_info_recursive and not token_budget_overflowed and successful_new_entries_for_recursion:
                next_scan_state = ScanState.RECURSION
                print(f"[WI] Found {len(successful_new_entries_for_recursion)} new entries for recursion")
            
            # 检查最小激活数
            min_activations_not_satisfied = (world_info_min_activations > 0 and 
                                           len(all_activated_entries) < world_info_min_activations)
            
            if (not next_scan_state and not token_budget_overflowed and min_activations_not_satisfied):
                print("[WI] --- MIN ACTIVATIONS CHECK ---")
                
                over_max = ((world_info_min_activations_depth_max > 0 and 
                           buffer.get_depth() > world_info_min_activations_depth_max) or 
                           buffer.get_depth() > len(chat))
                
                if not over_max:
                    next_scan_state = ScanState.MIN_ACTIVATIONS
                    print(f"[WI] Min activations not reached ({len(all_activated_entries)}/{world_info_min_activations}), advancing depth to {buffer.get_depth() + 1}")
                    buffer.advance_scan()
                else:
                    print(f"[WI] Min activations not reached ({len(all_activated_entries)}/{world_info_min_activations}), but reached depth limit. Stopping")
            
            # 检查延迟递归级别
            if next_scan_state == ScanState.NONE and available_recursion_delay_levels:
                next_scan_state = ScanState.RECURSION
                current_recursion_delay_level = available_recursion_delay_levels.pop(0)
                print(f"[WI] Open delayed recursion levels left. Preparing next delayed recursion level {current_recursion_delay_level}")
            
            # 更新扫描状态
            scan_state = next_scan_state
            if scan_state != ScanState.NONE:
                text = "\n".join([e.content for e in successful_new_entries_for_recursion])
                if text:
                    buffer.add_recurse(text)
                    all_activated_text = text + "\n" + all_activated_text
            else:
                print("[WI] Scan done. No new entries to prompt. Stopping.")
        
        print("[WI] --- BUILDING PROMPT ---")
        
        # 构建结果
        world_info_before_entries = []
        world_info_before_tokens = 0
        world_info_after_entries = []
        world_info_after_tokens = 0
        em_entries = []
        an_top_entries = []
        an_bottom_entries = []
        wi_depth_entries = []
        
        # 按位置分类条目
        for entry in all_activated_entries.values():
            content = entry.content
            
            if not content:
                print(f"[WI] Entry {entry.uid} skipped adding to prompt due to empty content")
                continue
            
            position = entry.position
            if position == WorldInfoPosition.BEFORE.value:
                world_info_before_entries.insert(0, content)
                world_info_before_tokens += entry.tokens
            elif position == WorldInfoPosition.AFTER.value:
                world_info_after_entries.insert(0, content)
                world_info_after_tokens += entry.tokens
            elif position == WorldInfoPosition.EM_TOP.value:
                em_entries.insert(0, {"position": "before", "content": content})
            elif position == WorldInfoPosition.EM_BOTTOM.value:
                em_entries.insert(0, {"position": "after", "content": content})
            elif position == WorldInfoPosition.AN_TOP.value:
                an_top_entries.insert(0, content)
            elif position == WorldInfoPosition.AN_BOTTOM.value:
                an_bottom_entries.insert(0, content)
            elif position == WorldInfoPosition.AT_DEPTH.value:
                depth = entry.depth or 4
                role = entry.role or 0
                
                existing_depth_index = next((i for i, e in enumerate(wi_depth_entries) 
                                           if e['depth'] == depth and e['role'] == role), -1)
                
                if existing_depth_index != -1:
                    wi_depth_entries[existing_depth_index]['entries'].insert(0, content)
                else:
                    wi_depth_entries.append({
                        'depth': depth,
                        'entries': [content],
                        'role': role
                    })
        
        world_info_before = "\n".join(world_info_before_entries)
        world_info_after = "\n".join(world_info_after_entries)
        
        timed_effects.set_timed_effects(list(all_activated_entries.values()))
        buffer.reset_external_effects()
        timed_effects.clean_up()
        
        print(f"[WI] Adding {len(all_activated_entries)} entries to prompt")
        print(f"[WI] --- DONE ---")
        
        return WIActivated(
            world_info_before=world_info_before,
            world_info_before_tokens=world_info_before_tokens,
            world_info_after=world_info_after,
            world_info_after_tokens=world_info_after_tokens,
            wi_depth_entries=wi_depth_entries,
            em_entries=em_entries,
            an_before_entries=an_top_entries,
            an_after_entries=an_bottom_entries,
            all_activated_entries=set(all_activated_entries.values())
        )

    async def get_world_info_prompt(self, chat, max_context, global_scan_data):
        """
        Python 版本的 getWorldInfoPrompt
        :param chat: 聊天内容
        :param max_context: 最大上下文
        :param global_scan_data: 全局扫描数据
        :return: dict
        """
        world_info_string = ''
        world_info_before = ''
        world_info_after = ''
        if self.activate_keys is not None:
            self.entries = DBManager().list_all_activated_entries_by_keys(self.activate_world_books, self.activate_keys)
        else:
            self.entries = DBManager().list_all_activated_entries(self.activate_world_books)
        scan_data = WIGlobalScanData(
            trigger=global_scan_data.get('trigger', 'chat'),
            character_name=global_scan_data.get('character_name', ''),
            character_tags=global_scan_data.get('character_tags', [])
        )
        activated_world_info = await self.check_world_info(chat, max_context, scan_data)
        world_info_before = getattr(activated_world_info, 'world_info_before', '')
        world_info_before = re.sub(r'<env_desc>.*?</env_desc>\s*', '', world_info_before, flags=re.DOTALL)
        world_info_before_tokens = getattr(activated_world_info, 'world_info_before_tokens', 0)
        world_info_after = getattr(activated_world_info, 'world_info_after', '')
        world_info_after = re.sub(r'<env_desc>.*?</env_desc>\s*', '', world_info_after, flags=re.DOTALL)
        world_info_after_tokens = getattr(activated_world_info, 'world_info_after_tokens', 0)
        world_info_string = world_info_before + world_info_after

        return {
            "worldInfoString": world_info_string,
            "worldInfoBefore": world_info_before,
            "worldInfoBeforeTokens": world_info_before_tokens,
            "worldInfoAfter": world_info_after,
            "worldInfoAfterTokens": world_info_after_tokens,
            "worldInfoExamples": getattr(activated_world_info, 'em_entries', []) or [],
            "worldInfoDepth": getattr(activated_world_info, 'wi_depth_entries', []) or [],
            "anBefore": getattr(activated_world_info, 'an_before_entries', []) or [],
            "anAfter": getattr(activated_world_info, 'an_after_entries', []) or [],
        }