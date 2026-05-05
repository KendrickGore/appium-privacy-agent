import time

from agent.llm_agent import LLMAgent
from appium_runner.driver import create_driver_attach_current
from appium_runner.tools import AppiumTools


def main():
    task = {
        "app_name": "大众点评",
        "right_type": "同意权",
        "target_name": "个性化推荐开关",
        "declared_path": ["我的", "设置", "隐私管理", "系统权限管理"],
        "target_keywords": [
            "隐私管理",
            "系统权限管理",
            "个性化推荐",
            "个性化广告",
            "广告推荐",
            "推荐管理"
        ]
    }

    current_goal = "隐私管理"

    driver = create_driver_attach_current()
    agent = LLMAgent()

    try:
        time.sleep(2)

        tools = AppiumTools(driver, "大众点评_LLM单步测试")
        page_info = tools.get_page_info(
            step_name="llm_once",
            take_screenshot=False
        )

        print("\n========== 当前页面文本 ==========")
        for text in page_info["texts"]:
            print(text)

        print("\n========== 当前页面可点击元素 ==========")
        for item in page_info["clickable_elements"]:
            print(item)

        history = []

        decision = agent.decide(
            task=task,
            page_info=page_info,
            history=history,
            current_goal=current_goal
        )

        print("\n========== LLM 决策 ==========")
        print(decision)

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()