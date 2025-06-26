import json
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ValidationError

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.outputs import Generation
from langchain_core.utils.pydantic import (
    TBaseModel
)
from langchain_core.exceptions import OutputParserException

class RemoveFunctionCallOutputParser(PydanticOutputParser):
    @staticmethod
    def filter_function_call(text: str) -> str:
        """
        去掉特殊格式的函数调用文本
        
        示例输入:
        <|FunctionCallBegin|>[{"name": "Queries", "parameters": {"queries": ["query1", "query2"]}}]<|FunctionCallEnd|>
        
        返回:
        去掉函数调用文本后的字符串
        """
        try:
            # 使用正则表达式提取 JSON 部分
            pattern = r'<\|FunctionCallBegin\|>(.*?)<\|FunctionCallEnd\|>'
            match = re.search(pattern, text)
            
            if not match:
                return text
                
            # 解析 JSON
            json_str = match.group(1)
            return json_str
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"解析错误: {str(e)}")
            return None

    def parse_result(
        self, result: list[Generation], *, partial: bool = False
    ) -> Optional[TBaseModel]:
        """Parse the result of an LLM call to a pydantic object.

        Args:
            result: The result of the LLM call.
            partial: Whether to parse partial JSON objects.
                If True, the output will be a JSON object containing
                all the keys that have been returned so far.
                Defaults to False.

        Returns:
            The parsed pydantic object.
        """
        try:
            text = result[0].text
            text = text.strip()
            text = self.filter_function_call(text)
            result[0].text = text
            json_object = super().parse_result(result)
            return self._parse_obj(json_object)
        except OutputParserException:
            if partial:
                return None
            raise