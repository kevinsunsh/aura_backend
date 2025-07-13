import logging

from agents.aura_memory.person_info.person_store import PersonInfoModel, PersonInfo, PersonStore
import copy
import hashlib
from typing import Any, Callable, Dict, List
import datetime
import asyncio
from configuration import global_config, get_chat_model_by_type

import json  # 新增导入
from json_repair import repair_json


"""
PersonInfoManager 类方法功能摘要：
1. get_person_id - 根据平台和用户ID生成MD5哈希的唯一person_id
2. create_person_info - 创建新个人信息文档（自动合并默认值）
3. update_one_field - 更新单个字段值（若文档不存在则创建）
4. del_one_document - 删除指定person_id的文档
5. get_value - 获取单个字段值（返回实际值或默认值）
6. get_values - 批量获取字段值（任一字段无效则返回空字典）
7. del_all_undefined_field - 清理全集合中未定义的字段
8. get_specific_value_list - 根据指定条件，返回person_id,value字典
"""


logger = logging.getLogger(__name__)

JSON_SERIALIZED_FIELDS = ["points", "forgotten_points", "info_list"]

person_info_default = {
    "person_id": None,
    "person_name": None,
    "name_reason": None,  # Corrected from person_name_reason to match common usage if intended
    "platform": "unknown",
    "user_id": "unknown",
    "nickname": "Unknown",
    "know_times": 0,
    "know_since": None,
    "last_know": None,
    "impression": None,  # Corrected from persion_impression
    "short_impression": None,
    "info_list": None,
    "points": None,
    "forgotten_points": None,
    "relation_value": None,
    "attitude": 50,
}


class PersonInfoManager:
    def __init__(self):
        self.person_name_list = {}
        # TODO: API-Adapter修改标记
        self.qv_name_llm = LLMRequest(
            model=global_config.model.utils,
            request_type="relation.qv_name",
        )
        self.person_store = PersonStore.get_instance()
        
        # 初始化时读取所有person_name
        try:
            all_persons = self.person_store.get_all_persons()
            for person in all_persons:
                if person.person_name:
                    self.person_name_list[person.person_id] = person.person_name
            logger.debug(f"已加载 {len(self.person_name_list)} 个用户名称")
        except Exception as e:
            logger.error(f"加载 person_name_list 失败: {e}")

    @staticmethod
    def get_person_id(platform: str, user_id: int):
        """获取唯一id"""
        if "-" in platform:
            platform = platform.split("-")[1]

        components = [platform, str(user_id)]
        key = "_".join(components)
        return hashlib.md5(key.encode()).hexdigest()

    async def is_person_known(self, platform: str, user_id: int):
        """判断是否认识某人"""
        person_id = self.get_person_id(platform, user_id)

        def _db_check_known_sync(p_id: str):
            return self.person_store.get_person_by_id(p_id) is not None

        try:
            return await asyncio.to_thread(_db_check_known_sync, person_id)
        except Exception as e:
            logger.error(f"检查用户 {person_id} 是否已知时出错: {e}")
            return False

    def get_person_id_by_person_name(self, person_name: str):
        """根据用户名获取用户ID"""
        try:
            person = self.person_store.get_person_by_name(person_name)
            if person:
                return person.person_id
            else:
                return ""
        except Exception as e:
            logger.error(f"根据用户名 {person_name} 获取用户ID时出错: {e}")
            return ""

    @staticmethod
    async def create_person_info(person_id: str, data: dict = None):
        """创建一个项"""
        if not person_id:
            logger.debug("创建失败，personid不存在")
            return

        _person_info_default = copy.deepcopy(person_info_default)
        
        final_data = {"person_id": person_id}

        # Start with defaults for all fields
        for key, default_value in _person_info_default.items():
            final_data[key] = default_value

        # Override with provided data
        if data:
            for key, value in data.items():
                final_data[key] = value

        # Ensure person_id is correctly set from the argument
        final_data["person_id"] = person_id

        # Create PersonInfo object
        person_info = PersonInfo(**final_data)

        def _db_create_sync(person: PersonInfo):
            try:
                person_store = PersonStore.get_instance()
                return person_store.add_person(person)
            except Exception as e:
                logger.error(f"创建 PersonInfo 记录 {person.person_id} 失败: {e}")
                return False

        await asyncio.to_thread(_db_create_sync, person_info)

    async def update_one_field(self, person_id: str, field_name: str, value, data: dict = None):
        """更新某一个字段，会补全"""
        # 检查字段是否在PersonInfo模型中
        if not hasattr(PersonInfo, field_name):
            logger.debug(f"更新'{field_name}'失败，未在 PersonInfo 模型中定义的字段。")
            return

        def _db_update_sync(p_id: str, f_name: str, val_to_set):
            import time

            start_time = time.time()
            try:
                person_store = PersonStore.get_instance()
                # 使用新的 update_person_field 方法，更高效
                success = person_store.update_person_field(p_id, f_name, val_to_set)
                save_time = time.time()

                if success:
                    total_time = save_time - start_time
                    if total_time > 0.5:  # 如果超过500ms就记录日志
                        logger.warning(
                            f"数据库更新操作耗时 {total_time:.3f}秒 person_id={p_id}, field={f_name}"
                        )
                    return True, False  # Found and updated, no creation needed
                else:
                    total_time = time.time() - start_time
                    if total_time > 0.5:
                        logger.warning(f"数据库更新操作耗时 {total_time:.3f}秒 person_id={p_id}, field={f_name}")
                    return False, True  # Not found, needs creation
            except Exception as e:
                total_time = time.time() - start_time
                logger.error(f"数据库操作异常，耗时 {total_time:.3f}秒: {e}")
                raise

        found, needs_creation = await asyncio.to_thread(_db_update_sync, person_id, field_name, value)

        if needs_creation:
            logger.info(f"{person_id} 不存在，将新建。")
            creation_data = data if data is not None else {}
            # Ensure platform and user_id are present for context if available from 'data'
            # but primarily, set the field that triggered the update.
            # The create_person_info will handle defaults and serialization.
            creation_data[field_name] = value  # Pass original value to create_person_info

            # Ensure platform and user_id are in creation_data if available,
            # otherwise create_person_info will use defaults.
            if data and "platform" in data:
                creation_data["platform"] = data["platform"]
            if data and "user_id" in data:
                creation_data["user_id"] = data["user_id"]

            await self.create_person_info(person_id, creation_data)

    @staticmethod
    async def batch_update_fields(updates: List[tuple]) -> Dict[str, bool]:
        """批量更新多个用户的字段
        updates: List[tuple] - [(person_id, field_name, value), ...]
        returns: Dict[str, bool] - {person_id: success}
        """
        def _db_batch_update_sync(update_list: List[tuple]):
            try:
                person_store = PersonStore.get_instance()
                return person_store.batch_update_person_fields(update_list)
            except Exception as e:
                logger.error(f"批量更新字段失败: {e}")
                return {person_id: False for person_id, _, _ in update_list}

        return await asyncio.to_thread(_db_batch_update_sync, updates)

    @staticmethod
    async def has_one_field(person_id: str, field_name: str):
        """判断是否存在某一个字段"""
        if not hasattr(PersonInfo, field_name):
            logger.debug(f"检查字段'{field_name}'失败，未在 PersonInfo 模型中定义。")
            return False

        def _db_has_field_sync(p_id: str, f_name: str):
            person_store = PersonStore.get_instance()
            person = person_store.get_person_by_id(p_id)
            if person:
                return True
            return False

        try:
            return await asyncio.to_thread(_db_has_field_sync, person_id, field_name)
        except Exception as e:
            logger.error(f"检查字段 {field_name} for {person_id} 时出错: {e}")
            return False

    @staticmethod
    def _extract_json_from_text(text: str) -> dict:
        """从文本中提取JSON数据的高容错方法"""
        try:
            fixed_json = repair_json(text)
            if isinstance(fixed_json, str):
                parsed_json = json.loads(fixed_json)
            else:
                parsed_json = fixed_json

            if isinstance(parsed_json, list) and parsed_json:
                parsed_json = parsed_json[0]

            if isinstance(parsed_json, dict):
                return parsed_json

        except Exception as e:
            logger.warning(f"JSON提取失败: {e}")

        logger.warning(f"无法从文本中提取有效的JSON字典: {text}")
        logger.info(f"文本: {text}")
        return {"nickname": "", "reason": ""}

    async def _generate_unique_person_name(self, base_name: str) -> str:
        """生成唯一的 person_name，如果存在重复则添加数字后缀"""
        # 处理空昵称的情况
        if not base_name or base_name.isspace():
            base_name = "空格"

        # 检查基础名称是否已存在
        if base_name not in self.person_name_list.values():
            return base_name

        # 如果存在，添加数字后缀
        counter = 1
        while True:
            new_name = f"{base_name}[{counter}]"
            if new_name not in self.person_name_list.values():
                return new_name
            counter += 1

    async def qv_person_name(
        self, person_id: str, user_nickname: str, user_cardname: str, user_avatar: str, request: str = ""
    ):
        """给某个用户取名"""
        if not person_id:
            logger.debug("取名失败：person_id不能为空")
            return None

        old_name = await self.get_value(person_id, "person_name")
        old_reason = await self.get_value(person_id, "name_reason")

        max_retries = 8
        current_try = 0
        existing_names_str = ""
        current_name_set = set(self.person_name_list.values())

        while current_try < max_retries:
            # prompt_personality =get_individuality().get_prompt(x_person=2, level=1)
            bot_name = global_config.bot.nickname

            qv_name_prompt = f"你是{bot_name}，一个伪装成人类的AI，你不能让别人发现这一点，"
            qv_name_prompt += f"现在你想给一个用户取一个昵称，用户的qq昵称是{user_nickname}，"
            qv_name_prompt += f"用户的qq群昵称名是{user_cardname}，"
            if user_avatar:
                qv_name_prompt += f"用户的qq头像是{user_avatar}，"
            if old_name:
                qv_name_prompt += f"你之前叫他{old_name}，是因为{old_reason}，"

            qv_name_prompt += f"\n其他取名的要求是：{request}，不要太浮夸，简短，"
            qv_name_prompt += "\n请根据以上用户信息，想想你叫他什么比较好，不要太浮夸，请最好使用用户的qq昵称或群昵称原文，可以稍作修改，优先使用原文。优先使用用户的qq昵称或者群昵称原文。"

            if existing_names_str:
                qv_name_prompt += f"\n请注意，以下名称已被你尝试过或已知存在，请避免：{existing_names_str}。\n"

            if len(current_name_set) < 50 and current_name_set:
                qv_name_prompt += f"已知的其他昵称有: {', '.join(list(current_name_set)[:10])}等。\n"

            qv_name_prompt += "请用json给出你的想法，并给出理由，示例如下："
            qv_name_prompt += """{
                "nickname": "昵称",
                "reason": "理由"
            }"""
            response, (reasoning_content, model_name) = await self.qv_name_llm.generate_response_async(qv_name_prompt)
            # logger.info(f"取名提示词：{qv_name_prompt}\n取名回复：{response}")
            result = self._extract_json_from_text(response)

            if not result or not result.get("nickname"):
                logger.error("生成的昵称为空或结果格式不正确，重试中...")
                current_try += 1
                continue

            generated_nickname = result["nickname"]

            is_duplicate = False
            if generated_nickname in current_name_set:
                is_duplicate = True
                logger.info(f"尝试给用户{user_nickname} {person_id} 取名，但是 {generated_nickname} 已存在，重试中...")
            else:

                def _db_check_name_exists_sync(name_to_check):
                    person_store = PersonStore.get_instance()
                    return person_store.get_person_by_name(name_to_check) is not None

                if await asyncio.to_thread(_db_check_name_exists_sync, generated_nickname):
                    is_duplicate = True
                    current_name_set.add(generated_nickname)

            if not is_duplicate:
                await self.update_one_field(person_id, "person_name", generated_nickname)
                await self.update_one_field(person_id, "name_reason", result.get("reason", "未提供理由"))

                logger.info(
                    f"成功给用户{user_nickname} {person_id} 取名 {generated_nickname}，理由：{result.get('reason', '未提供理由')}"
                )

                self.person_name_list[person_id] = generated_nickname
                return result
            else:
                if existing_names_str:
                    existing_names_str += "、"
                existing_names_str += generated_nickname
                logger.debug(f"生成的昵称 {generated_nickname} 已存在，重试中...")
                current_try += 1

        # 如果多次尝试后仍未成功，使用唯一的 user_nickname 作为默认值
        unique_nickname = await self._generate_unique_person_name(user_nickname)
        logger.warning(f"在{max_retries}次尝试后未能生成唯一昵称，使用默认昵称 {unique_nickname}")
        await self.update_one_field(person_id, "person_name", unique_nickname)
        await self.update_one_field(person_id, "name_reason", "使用用户原始昵称作为默认值")
        self.person_name_list[person_id] = unique_nickname
        return {"nickname": unique_nickname, "reason": "使用用户原始昵称作为默认值"}

    @staticmethod
    async def del_one_document(person_id: str):
        """删除指定 person_id 的文档"""
        if not person_id:
            logger.debug("删除失败：person_id 不能为空")
            return

        def _db_delete_sync(p_id: str):
            try:
                person_store = PersonStore.get_instance()
                success = person_store.delete_person(p_id)
                return 1 if success else 0
            except Exception as e:
                logger.error(f"删除 PersonInfo {p_id} 失败: {e}")
                return 0

        deleted_count = await asyncio.to_thread(_db_delete_sync, person_id)

        if deleted_count > 0:
            logger.debug(f"删除成功：person_id={person_id}")
        else:
            logger.debug(f"删除失败：未找到 person_id={person_id} 或删除未影响行")

    @staticmethod
    async def get_value(person_id: str, field_name: str):
        """获取指定用户指定字段的值"""
        default_value_for_field = person_info_default.get(field_name)
        if field_name in JSON_SERIALIZED_FIELDS and default_value_for_field is None:
            default_value_for_field = []  # Ensure JSON fields default to [] if not in DB

        def _db_get_value_sync(p_id: str, f_name: str):
            person_store = PersonStore.get_instance()
            person = person_store.get_person_by_id(p_id)
            if person:
                val = getattr(person, f_name, None)
                return val
            return None  # Record not found

        try:
            value_from_db = await asyncio.to_thread(_db_get_value_sync, person_id, field_name)
            if value_from_db is not None:
                return value_from_db
            if field_name in person_info_default:
                return default_value_for_field
            logger.warning(f"字段 {field_name} 在 person_info_default 中未定义，且在数据库中未找到。")
            return None  # Ultimate fallback
        except Exception as e:
            logger.error(f"获取字段 {field_name} for {person_id} 时出错: {e}")
            # Fallback to default in case of any error during DB access
            if field_name in person_info_default:
                return default_value_for_field
            return None

    @staticmethod
    def get_value_sync(person_id: str, field_name: str):
        """同步获取指定用户指定字段的值"""
        default_value_for_field = person_info_default.get(field_name)
        if field_name in JSON_SERIALIZED_FIELDS and default_value_for_field is None:
            default_value_for_field = []

        person_store = PersonStore.get_instance()
        person = person_store.get_person_by_id(person_id)
        if person:
            val = getattr(person, field_name, None)
            return val

        if field_name in person_info_default:
            return default_value_for_field
        logger.warning(f"字段 {field_name} 在 person_info_default 中未定义，且在数据库中未找到。")
        return None

    @staticmethod
    async def get_values(person_id: str, field_names: list) -> dict:
        """获取指定person_id文档的多个字段值，若不存在该字段，则返回该字段的全局默认值"""
        if not person_id:
            logger.debug("get_values获取失败：person_id不能为空")
            return {}

        result = {}

        def _db_get_record_sync(p_id: str):
            person_store = PersonStore.get_instance()
            return person_store.get_person_by_id(p_id)

        person = await asyncio.to_thread(_db_get_record_sync, person_id)

        for field_name in field_names:
            if not hasattr(PersonInfo, field_name):
                if field_name in person_info_default:
                    result[field_name] = copy.deepcopy(person_info_default[field_name])
                    logger.debug(f"字段'{field_name}'不在PersonInfo模型中，使用默认配置值。")
                else:
                    logger.debug(f"get_values查询失败：字段'{field_name}'未在PersonInfo模型和默认配置中定义。")
                    result[field_name] = None
                continue

            if person:
                value = getattr(person, field_name)
                if value is not None:
                    result[field_name] = value
                else:
                    result[field_name] = copy.deepcopy(person_info_default.get(field_name))
            else:
                result[field_name] = copy.deepcopy(person_info_default.get(field_name))

        return result

    @staticmethod
    async def get_specific_value_list(
        field_name: str,
        way: Callable[[Any], bool],
    ) -> Dict[str, Any]:
        """
        获取满足条件的字段值字典
        """
        if not hasattr(PersonInfo, field_name):
            logger.error(f"字段检查失败：'{field_name}'未在 PersonInfo 模型中定义")
            return {}

        def _db_get_specific_sync(f_name: str):
            found_results = {}
            try:
                person_store = PersonStore.get_instance()
                all_persons = person_store.get_all_persons()
                for person in all_persons:
                    value = getattr(person, f_name)
                    if way(value):
                        found_results[person.person_id] = value
            except Exception as e_query:
                logger.error(f"数据库查询失败 (specific_value_list for {f_name}): {str(e_query)}", exc_info=True)
            return found_results

        try:
            return await asyncio.to_thread(_db_get_specific_sync, field_name)
        except Exception as e:
            logger.error(f"执行 get_specific_value_list 线程时出错: {str(e)}", exc_info=True)
            return {}

    async def get_or_create_person(
        self, platform: str, user_id: int, nickname: str = None, user_cardname: str = None, user_avatar: str = None
    ) -> str:
        """
        根据 platform 和 user_id 获取 person_id。
        如果对应的用户不存在，则使用提供的可选信息创建新用户。
        """
        person_id = self.get_person_id(platform, user_id)

        def _db_check_exists_sync(p_id: str):
            person_store = PersonStore.get_instance()
            return person_store.get_person_by_id(p_id)

        person = await asyncio.to_thread(_db_check_exists_sync, person_id)

        if person is None:
            logger.info(f"用户 {platform}:{user_id} (person_id: {person_id}) 不存在，将创建新记录。")
            unique_nickname = await self._generate_unique_person_name(nickname)
            initial_data = {
                "person_id": person_id,
                "platform": platform,
                "user_id": str(user_id),
                "nickname": nickname,
                "person_name": unique_nickname,  # 使用群昵称作为person_name
                "name_reason": "从群昵称获取",
                "know_times": 0,
                "know_since": int(datetime.datetime.now().timestamp()),
                "last_know": int(datetime.datetime.now().timestamp()),
                "impression": None,
                "points": [],
                "forgotten_points": [],
            }

            await self.create_person_info(person_id, data=initial_data)
            logger.info(f"已为 {person_id} 创建新记录，初始数据: {initial_data}")

        return person_id

    async def get_person_info_by_name(self, person_name: str) -> dict | None:
        """根据 person_name 查找用户并返回基本信息 (如果找到)"""
        if not person_name:
            logger.debug("get_person_info_by_name 获取失败：person_name 不能为空")
            return None

        found_person_id = None
        for pid, name_in_cache in self.person_name_list.items():
            if name_in_cache == person_name:
                found_person_id = pid
                break

        if not found_person_id:

            def _db_find_by_name_sync(p_name_to_find: str):
                person_store = PersonStore.get_instance()
                return person_store.get_person_by_name(p_name_to_find)

            person = await asyncio.to_thread(_db_find_by_name_sync, person_name)
            if person:
                found_person_id = person.person_id
                if (
                    found_person_id not in self.person_name_list
                    or self.person_name_list[found_person_id] != person_name
                ):
                    self.person_name_list[found_person_id] = person_name
            else:
                logger.debug(f"数据库中也未找到名为 '{person_name}' 的用户")
                return None

        if found_person_id:
            required_fields = [
                "person_id",
                "platform",
                "user_id",
                "nickname",
                "person_name",
                "name_reason",
            ]
            valid_fields_to_get = [
                f for f in required_fields if hasattr(PersonInfo, f) or f in person_info_default
            ]

            person_data = await self.get_values(found_person_id, valid_fields_to_get)

            if person_data:
                final_result = {key: person_data.get(key) for key in required_fields}
                # 添加不存在的字段的默认值
                final_result["user_cardname"] = None
                final_result["user_avatar"] = None
                return final_result
            else:
                logger.warning(f"找到了 person_id '{found_person_id}' 但 get_values 返回空")
                return None

        logger.error(f"逻辑错误：未能为 '{person_name}' 确定 person_id")
        return None


person_info_manager = None


def get_person_info_manager():
    global person_info_manager
    if person_info_manager is None:
        person_info_manager = PersonInfoManager()
    return person_info_manager
