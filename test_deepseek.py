import os
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
)

response = client.chat.completions.create(
    model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    messages=[
        {
            "role": "system",
            "content": "你只能输出 JSON，不要输出 Markdown，不要输出代码块。"
        },
        {
            "role": "user",
            "content": """
请输出如下 JSON：
{
  "action": "click_by_id",
  "element_id": 1,
  "switch_id": null,
  "success": null,
  "reason": "测试"
}
"""
        }
    ],
    stream=False,
    temperature=0
)

print(response.choices[0].message.content)