import time

from appium_runner.driver import create_driver
from appium_runner.tools import AppiumTools


def main():
    driver = create_driver(
        app_package="com.dianping.v1",
        app_activity="com.dianping.v1.NovaMainActivity"
    )

    try:
        # 等待 App 完全启动
        time.sleep(8)

        tools = AppiumTools(driver, "大众点评_启动测试")

        page_info = tools.get_page_info("first_page", take_screenshot=False)

        print("\n========== 当前页面文本 ==========")
        for text in page_info["texts"]:
            print(text)

        print("\n========== 当前页面可点击元素 ==========")
        for item in page_info["clickable_elements"]:
            print(item)

        print("\n========== 当前页面开关元素 ==========")
        for item in page_info["switches"]:
            print(item)

        print("\n========== 截图路径 ==========")
        print(page_info["screenshot"])

    finally:
        driver.quit()


if __name__ == "__main__":
    main()