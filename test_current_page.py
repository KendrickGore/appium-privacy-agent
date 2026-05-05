import time

from appium_runner.driver import create_driver_attach_current
from appium_runner.tools import AppiumTools


def main():
    driver = create_driver_attach_current()

    try:
        time.sleep(2)

        tools = AppiumTools(driver, "当前页面测试")
        page_info = tools.get_page_info("current_page", take_screenshot=False)

        print("\n========== 当前页面文本 ==========")
        for text in page_info["texts"]:
            print(text)

        print("\n========== 当前页面可点击元素 ==========")
        for item in page_info["clickable_elements"]:
            print(item)

        print("\n========== 当前页面开关元素 ==========")
        for item in page_info["switches"]:
            print(item)

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()