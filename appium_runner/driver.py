from appium import webdriver
from appium.options.android import UiAutomator2Options


def create_driver(app_package: str, app_activity: str, device_name: str = "Android"):
    """
    创建 Appium driver，用于连接真实 Android 手机并启动指定 App。
    """

    options = UiAutomator2Options()

    options.platform_name = "Android"
    options.automation_name = "UiAutomator2"
    options.device_name = device_name

    options.app_package = app_package
    options.app_activity = app_activity

    # 不清空 App 数据，保留登录态
    options.no_reset = True

    # 支持中文输入
    options.unicode_keyboard = True
    options.reset_keyboard = True

    # 防止长时间无命令导致 session 断开
    options.new_command_timeout = 300

    driver = webdriver.Remote(
        command_executor="http://127.0.0.1:4723",
        options=options
    )

    return driver

def create_driver_attach_current(device_name: str = "Android"):
    """
    不主动启动任何 App，只连接当前手机页面。
    适合手动打开 App 后，让 Appium 读取当前页面。
    """

    options = UiAutomator2Options()

    options.platform_name = "Android"
    options.automation_name = "UiAutomator2"
    options.device_name = device_name

    options.no_reset = True
    options.new_command_timeout = 300

    driver = webdriver.Remote(
        command_executor="http://127.0.0.1:4723",
        options=options
    )

    return driver