import os
import json
from dotenv import load_dotenv
from openai import OpenAI

from agent.prompt import SYSTEM_PROMPT, build_user_prompt


load_dotenv()


class LLMAgent:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

        if not self.api_key:
            self.client = None
        else:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )

    def decide(self, task, page_info, history, current_goal):
        """
        让 DeepSeek 根据当前页面信息和任务目标，决定下一步动作。
        普通版本：不启用 reasoning_effort 和 thinking。
        """

        if self.client is None:
            return {
                "action": "stop",
                "element_id": None,
                "switch_id": None,
                "success": False,
                "reason": "DeepSeek API Key 未配置，请检查 .env 中的 DEEPSEEK_API_KEY"
            }

        user_prompt = build_user_prompt(
            task=task,
            page_info=page_info,
            history=history,
            current_goal=current_goal
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                stream=False,
                temperature=0
            )

            content = response.choices[0].message.content.strip()
            return self._parse_json(content)

        except Exception as e:
            return {
                "action": "stop",
                "element_id": None,
                "switch_id": None,
                "success": False,
                "reason": f"DeepSeek API 调用失败：{str(e)}"
            }

    def _parse_json(self, content):
        """
        解析模型输出的 JSON。
        兼容模型偶尔输出 ```json ... ``` 的情况。
        """

        content = content.strip()

        if content.startswith("```json"):
            content = content[len("```json"):].strip()

        if content.startswith("```"):
            content = content[len("```"):].strip()

        if content.endswith("```"):
            content = content[:-3].strip()

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return {
                "action": "stop",
                "element_id": None,
                "switch_id": None,
                "success": False,
                "reason": f"DeepSeek 输出不是合法 JSON：{content}"
            }

        return self._normalize_decision(data)

    def _normalize_decision(self, data):
        """
        对模型输出做基本校验，防止 action 不合法。
        """

        allowed_actions = {
            "click_by_id",
            "toggle_switch",
            "scroll_down",
            "scroll_up",
            "back",
            "tap_top_left_back",
            "stop"
        }

        action = data.get("action")

        if action not in allowed_actions:
            return {
                "action": "stop",
                "element_id": None,
                "switch_id": None,
                "success": False,
                "reason": f"模型输出了非法 action：{action}"
            }

        return {
            "action": action,
            "element_id": data.get("element_id"),
            "switch_id": data.get("switch_id"),
            "success": data.get("success"),
            "reason": data.get("reason", "")
        }