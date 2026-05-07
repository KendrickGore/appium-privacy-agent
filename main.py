import time
import re
from copy import deepcopy

from agent.llm_agent import LLMAgent
from appium_runner.driver import create_driver, create_driver_attach_current
from appium_runner.tools import AppiumTools
from appium_runner.executor import execute_action
from utils.json_utils import load_json, save_json
from utils.logger import TaskLogger


# =========================
# True  = 接管手机当前页面，不重新启动 Appium session
# False = 根据 package/activity 启动 Appium session
# =========================
ATTACH_CURRENT_PAGE = True

# 关闭截图，避免 Appium screenshot 超时
TAKE_SCREENSHOT = False

# 不同 App 之间：先回桌面，再用 package 启动 App
LAUNCH_APP_AFTER_HOME = True


def get_successful_click_count(history):
    count = 0
    for item in history:
        decision = item.get("decision", {})
        result = item.get("result", {})
        if decision.get("action") == "click_by_id" and result.get("success"):
            count += 1
    return count


def get_current_goal(task, history):
    """
    根据已成功点击次数，估计当前应该寻找 declared_path 中的哪一步。
    """
    declared_path = task.get("declared_path", [])
    success_clicks = get_successful_click_count(history)

    if success_clicks < len(declared_path):
        return declared_path[success_clicks]

    return task.get("target_name")


def summarize_result(task, history):
    """
    当前阶段的评价标准：
    只要智能体能够按照 declared_path 成功走完路径，
    就认为该测试项声明的执行位置真实存在。
    """
    declared_path = task.get("declared_path", [])

    final = {
        "test_name": task.get("test_name"),
        "app_name": task.get("app_name"),
        "target_name": task.get("target_name"),
        "declared_path": declared_path,
        "declared_path_completed": False,
        "path_reachable": False,
        "successful_clicks": 0,
        "score": 0,
        "conclusion": ""
    }

    successful_clicks = get_successful_click_count(history)
    final["successful_clicks"] = successful_clicks

    if successful_clicks >= len(declared_path):
        final["declared_path_completed"] = True
        final["path_reachable"] = True
        final["score"] = 1
        final["conclusion"] = "声明路径已成功走完，说明隐私政策中声明的执行位置真实存在。"
    elif successful_clicks > 0:
        final["score"] = 0
        final["conclusion"] = "声明路径部分可达，但未能完整走到目标位置。"
    else:
        final["score"] = 0
        final["conclusion"] = "未能按照声明路径进入目标位置。"

    return final


def print_page_summary(page_info):
    texts = page_info.get("texts", [])
    clickable_elements = page_info.get("clickable_elements", [])
    switches = page_info.get("switches", [])

    print("页面文本数量：", len(texts))
    print("可点击元素数量：", len(clickable_elements))
    print("开关元素数量：", len(switches))

    print("页面主要文本：")
    for text in texts[:30]:
        print("  -", text)

    print("前 15 个可点击元素：")
    for item in clickable_elements[:15]:
        print("  -", item)


def parse_bounds_for_main(bounds: str):
    nums = list(map(int, re.findall(r"\d+", bounds or "")))
    if len(nums) != 4:
        return None

    left, top, right, bottom = nums
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "center_x": (left + right) // 2,
        "center_y": (top + bottom) // 2
    }


def element_name(item):
    parts = [
        item.get("text") or "",
        item.get("content_desc") or "",
        item.get("nearby_text") or ""
    ]
    return " ".join([p for p in parts if p and p != "null"])


def make_click_decision(element_id, reason):
    return {
        "action": "click_by_id",
        "element_id": element_id,
        "switch_id": None,
        "success": None,
        "reason": reason
    }


def find_explicit_goal_entry(page_info, current_goal):
    """
    如果当前页面中存在显式 current_goal 入口，则直接返回对应元素。

    注意：
    对“设置”这种短词，不使用 contains 匹配，避免误点“点击设置昵称”。
    """
    if not current_goal:
        return None

    clickable_elements = page_info.get("clickable_elements", [])

    # 1. 精确匹配优先
    for item in clickable_elements:
        name = element_name(item)
        if name == current_goal:
            return item

    # 2. “设置”是短词，不能 contains 匹配
    if current_goal == "设置":
        allowed_setting_names = {
            "设置",
            "设置中心",
            "系统设置",
            "账号设置",
            "应用设置"
        }

        for item in clickable_elements:
            name = element_name(item)
            if name in allowed_setting_names:
                return item

        return None

    # 3. 其他路径节点可以使用包含匹配
    for item in clickable_elements:
        name = element_name(item)
        if current_goal in name:
            return item

    return None


def choose_icon_by_position(page_info, position):
    """
    从无文字可点击元素中，按照位置选择候选图标。

    position:
    - top_right
    - top_left
    - top_bar
    """
    clickable_elements = page_info.get("clickable_elements", [])

    parsed_items = []
    screen_right = 0
    screen_bottom = 0

    for item in clickable_elements:
        pos = parse_bounds_for_main(item.get("bounds", ""))
        if pos:
            parsed_items.append((item, pos))
            screen_right = max(screen_right, pos["right"])
            screen_bottom = max(screen_bottom, pos["bottom"])

    candidates = []

    for item, pos in parsed_items:
        name = element_name(item)

        # 只选择无文字、无 nearby_text 的图标型元素
        if name:
            continue

        cx = pos["center_x"]
        cy = pos["center_y"]

        is_top = cy <= screen_bottom * 0.15

        if not is_top:
            continue

        if position == "top_right":
            if cx >= screen_right * 0.65:
                candidates.append((item, pos))
        elif position == "top_left":
            if cx <= screen_right * 0.35:
                candidates.append((item, pos))
        elif position == "top_bar":
            candidates.append((item, pos))

    if not candidates:
        return None

    if position == "top_right":
        candidates.sort(key=lambda x: x[1]["center_x"], reverse=True)
    elif position == "top_left":
        candidates.sort(key=lambda x: x[1]["center_x"])
    else:
        candidates.sort(key=lambda x: x[1]["center_y"])

    return candidates[0][0]


def make_forced_decision(task, page_info, current_goal):
    """
    规则兜底决策。

    逻辑：
    1. 如果页面中有显式 current_goal，例如“我的”“设置”“隐私管理”，直接点击；
    2. 如果没有显式 current_goal，再查看 special_hints；
    3. 如果 special_hints 没有配置，则返回 None，交给 LLM。
    """
    explicit_entry = find_explicit_goal_entry(page_info, current_goal)
    if explicit_entry is not None:
        return make_click_decision(
            explicit_entry.get("element_id"),
            f"页面中存在显式入口：{current_goal}，直接点击"
        )

    special_hints = task.get("special_hints", {})
    hint = special_hints.get(current_goal)

    if not hint:
        return None

    strategy = hint.get("strategy")

    if strategy == "manual_element_id":
        element_id = hint.get("element_id")
        if element_id is None:
            return None

        return make_click_decision(
            element_id,
            f"页面中没有显式入口 {current_goal}，根据 special_hints 使用 manual_element_id={element_id}"
        )

    if strategy == "top_right_icon":
        candidate = choose_icon_by_position(page_info, position="top_right")
        if candidate is None:
            return None

        return make_click_decision(
            candidate.get("element_id"),
            f"页面中没有显式入口 {current_goal}，根据 special_hints 使用 top_right_icon"
        )

    if strategy == "top_left_icon":
        candidate = choose_icon_by_position(page_info, position="top_left")
        if candidate is None:
            return None

        return make_click_decision(
            candidate.get("element_id"),
            f"页面中没有显式入口 {current_goal}，根据 special_hints 使用 top_left_icon"
        )

    if strategy == "top_bar_icon":
        candidate = choose_icon_by_position(page_info, position="top_bar")
        if candidate is None:
            return None

        return make_click_decision(
            candidate.get("element_id"),
            f"页面中没有显式入口 {current_goal}，根据 special_hints 使用 top_bar_icon"
        )

    return None


def return_by_click_count(tools, click_count):
    """
    同一个 App 的不同测试项之间：
    本次 declared_path 成功点击了几次，就按几次系统返回键，
    尽量回到本条测试路径开始前的 App 首页。

    当前阶段不做 home_signals 判断，也不做 skip_back_count。
    """
    back_times = max(int(click_count or 0), 0)

    print(f"准备按成功点击次数回退：{back_times} 次")

    for i in range(back_times):
        try:
            print(f"执行第 {i + 1}/{back_times} 次返回")
            tools.back()
            time.sleep(0.8)
        except Exception as e:
            print("系统返回失败，尝试左上角返回：", e)
            try:
                tools.tap_top_left_back()
                time.sleep(0.8)
            except Exception as e2:
                print("左上角返回也失败：", e2)
                return {
                    "success": False,
                    "message": f"第 {i + 1} 次返回失败：{str(e2)}",
                    "back_times": i
                }

    return {
        "success": True,
        "message": f"已按成功点击次数返回 {back_times} 次",
        "back_times": back_times
    }


def merge_app_and_test_config(app_config, consent_test):
    """
    将 App 层配置和单个 consent_test 配置合并成原 run_task 能识别的 task。
    """
    task = deepcopy(app_config)
    task.pop("consent_tests", None)

    app_hints = deepcopy(app_config.get("special_hints", {}))
    test_hints = deepcopy(consent_test.get("special_hints", {}))
    merged_hints = app_hints
    merged_hints.update(test_hints)

    task.update(consent_test)
    task["special_hints"] = merged_hints
    task["app_name"] = app_config.get("app_name")
    task["package"] = app_config.get("package")
    task["activity"] = app_config.get("activity")

    if not task.get("test_name"):
        task["test_name"] = task.get("target_name", "未命名测试项")

    return task


def run_single_consent_test(task, agent, tools, test_index):
    """
    执行单个同意权测试项。
    该函数只负责执行路径，不负责回退。
    回退由 run_app_tests() 根据 successful_clicks 统一处理。
    """
    app_name = task["app_name"]
    test_name = task.get("test_name", f"test_{test_index}")
    max_steps = task.get("max_steps", 10)

    print(f"\n====== 开始测试项：{app_name} / {test_name} ======")

    logger_name = f"{app_name}_{test_index}_{test_name}"
    logger = TaskLogger(logger_name)
    history = []

    for step_index in range(max_steps):
        current_goal = get_current_goal(task, history)

        print(f"\n---------- {test_name} / Step {step_index} ----------")
        print("当前目标：", current_goal)

        page_info = tools.get_page_info(
            step_name=f"{test_index}_{step_index}",
            take_screenshot=TAKE_SCREENSHOT
        )

        print_page_summary(page_info)

        forced_decision = make_forced_decision(
            task=task,
            page_info=page_info,
            current_goal=current_goal
        )

        if forced_decision is not None:
            decision = forced_decision
            print("使用规则决策：", decision)
        else:
            try:
                decision = agent.decide(
                    task=task,
                    page_info=page_info,
                    history=history,
                    current_goal=current_goal
                )
            except Exception as e:
                decision = {
                    "action": "stop",
                    "element_id": None,
                    "switch_id": None,
                    "success": False,
                    "reason": f"LLM 决策异常：{str(e)}"
                }

        print("LLM/规则决策：", decision)

        try:
            result = execute_action(decision, tools)
        except Exception as e:
            result = {
                "success": False,
                "message": f"动作执行异常：{str(e)}"
            }

        print("执行结果：", result)

        record = {
            "step_index": step_index,
            "current_goal": current_goal,
            "page_info": page_info,
            "decision": decision,
            "result": result
        }

        history.append(record)
        logger.add_step(step_index, page_info, decision, result)

        action = decision.get("action")

        if action == "stop":
            print("LLM 请求停止测试。")
            break

        declared_path = task.get("declared_path", [])
        stop_when_path_completed = task.get("stop_when_path_completed", True)
        successful_clicks = get_successful_click_count(history)

        if stop_when_path_completed and successful_clicks >= len(declared_path):
            print("声明路径已经走完，判定路径真实性验证成功，停止测试项。")
            break

        if action == "toggle_switch" and result.get("success"):
            print("已经执行开关切换，结束当前测试项。")
            break

        time.sleep(1)

    log_path = logger.save()
    final_result = summarize_result(task, history)
    final_result["log_path"] = log_path
    final_result["test_index"] = test_index

    print(f"\n====== 测试项结束：{app_name} / {test_name} ======")
    print("测试项结果：", final_result)

    return final_result


def run_app_tests(app_config, agent):
    """
    执行一个 App 下的所有 consent_tests。

    不同 App 之间：
    - 回桌面
    - package 启动

    同一个 App 内不同测试项之间：
    - 不重启 App
    - 当前测试成功点击几次，就按几次返回键
    """
    app_name = app_config["app_name"]
    package = app_config.get("package")
    activity = app_config.get("activity")
    consent_tests = app_config.get("consent_tests", [])

    print(f"\n========== 开始测试 App：{app_name} ==========")

    if not consent_tests:
        # 兼容旧格式：如果没有 consent_tests，就把整个 app_config 当成一个测试项
        consent_tests = [{
            "test_name": app_config.get("target_name", "默认测试项"),
            "right_type": app_config.get("right_type"),
            "target_name": app_config.get("target_name"),
            "declared_path": app_config.get("declared_path", []),
            "target_keywords": app_config.get("target_keywords", []),
            "max_steps": app_config.get("max_steps", 10),
            "stop_when_path_completed": app_config.get("stop_when_path_completed", True)
        }]

    if ATTACH_CURRENT_PAGE:
        print("运行模式：接管当前手机页面")
        driver = create_driver_attach_current()
    else:
        print("运行模式：根据 package/activity 启动 App")
        driver = create_driver(package, activity)

    tools = AppiumTools(driver, app_name)

    app_result = {
        "app_name": app_name,
        "package": package,
        "activity": activity,
        "tests": []
    }

    try:
        time.sleep(1)

        if LAUNCH_APP_AFTER_HOME:
            print("准备回到桌面...")
            tools.go_home()
            time.sleep(1.5)

            print(f"准备使用 package 启动 App：{app_name} ({package})")
            try:
                driver.activate_app(package)
                time.sleep(4)
                print(f"App 启动成功：{app_name}")
            except Exception as e:
                raise RuntimeError(
                    f"无法通过 package 启动 App：{app_name}，package={package}，错误：{str(e)}"
                )

        for idx, consent_test in enumerate(consent_tests, start=1):
            task = merge_app_and_test_config(app_config, consent_test)

            try:
                test_result = run_single_consent_test(
                    task=task,
                    agent=agent,
                    tools=tools,
                    test_index=idx
                )
                app_result["tests"].append(test_result)

                # 同一 App 内，测试项结束后，根据本次成功点击次数返回相同次数
                successful_clicks = test_result.get("successful_clicks", 0)
                return_result = return_by_click_count(tools, successful_clicks)
                print("测试项结束后的回退结果：", return_result)

            except Exception as e:
                app_result["tests"].append({
                    "test_index": idx,
                    "test_name": consent_test.get("test_name"),
                    "target_name": consent_test.get("target_name"),
                    "declared_path": consent_test.get("declared_path"),
                    "error": str(e),
                    "score": 0,
                    "conclusion": "测试项执行过程中发生异常。"
                })

        return app_result

    finally:
        try:
            print(f"App 测试结束，准备回到桌面：{app_name}")
            tools.go_home()
        except Exception:
            pass

        try:
            driver.quit()
        except Exception:
            pass


def main():
    apps = load_json("config/apps.json")
    agent = LLMAgent()

    final_results = []

    for app_config in apps:
        try:
            app_result = run_app_tests(app_config, agent)
            final_results.append(app_result)
        except Exception as e:
            final_results.append({
                "app_name": app_config.get("app_name"),
                "package": app_config.get("package"),
                "error": str(e),
                "tests": [],
                "conclusion": "App 测试过程中发生异常。"
            })

    save_json(final_results, "results/final_results.json")

    print("\n========== 全部测试完成 ==========")
    print("结果已保存到 results/final_results.json")


if __name__ == "__main__":
    main()
