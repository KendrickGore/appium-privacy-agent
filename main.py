import time
import re

from agent.llm_agent import LLMAgent
from appium_runner.driver import create_driver, create_driver_attach_current
from appium_runner.tools import AppiumTools
from appium_runner.executor import execute_action
from utils.json_utils import load_json, save_json
from utils.logger import TaskLogger


# =========================
# True  = 接管手机当前页面，不重新启动 App
# False = 根据 package/activity 启动 App
# =========================
ATTACH_CURRENT_PAGE = True

# 关闭截图，避免 Appium screenshot 超时
TAKE_SCREENSHOT = False

# 多应用测试模式：
# True  = 每个 App 测试前先回到桌面，再使用 package 启动 App
# False = 不回桌面，不启动 App，直接接管当前页面继续
LAUNCH_FROM_PACKAGE_AFTER_HOME = True


def get_current_goal(task, history):
    """
    简单估计当前应该寻找 declared_path 中的哪一步。

    规则：
    已经成功 click_by_id 几次，就认为路径推进了几步。
    """

    declared_path = task.get("declared_path", [])
    success_clicks = 0

    for record in history:
        decision = record.get("decision", {})
        result = record.get("result", {})

        if decision.get("action") == "click_by_id" and result.get("success"):
            success_clicks += 1

    if success_clicks < len(declared_path):
        return declared_path[success_clicks]

    return task.get("target_name")


def summarize_result(task, history):
    """
    当前阶段的评价标准：
    只要智能体能够按照 declared_path 成功走完路径，
    就认为该 App 声明的执行位置真实存在。
    """

    declared_path = task.get("declared_path", [])

    final = {
        "app_name": task.get("app_name"),
        "target_name": task.get("target_name"),
        "declared_path": declared_path,
        "declared_path_completed": False,
        "path_reachable": False,
        "successful_clicks": 0,
        "score": 0,
        "conclusion": ""
    }

    successful_clicks = 0

    for record in history:
        decision = record.get("decision", {})
        result = record.get("result", {})

        if decision.get("action") == "click_by_id" and result.get("success"):
            successful_clicks += 1

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
    """
    打印当前页面的简要信息，方便观察 LLM 决策依据。
    """

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
    """
    解析 Appium 返回的 bounds，例如 '[975,162][1051,238]'。
    """
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
    """
    综合 text、content_desc、nearby_text，得到元素语义名称。
    """
    parts = [
        item.get("text") or "",
        item.get("content_desc") or "",
        item.get("nearby_text") or ""
    ]

    return " ".join([
        p for p in parts
        if p and p != "null"
    ])


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
    第一优先级：
    如果当前页面中存在显式 current_goal 入口，则直接返回对应元素。

    对“设置”做特殊处理：
    不使用宽松 contains 匹配，避免把“点击设置昵称”“个人主页设置”误判为设置入口。
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

        # 顶部区域
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

    # 第一优先级：显式入口
    explicit_entry = find_explicit_goal_entry(page_info, current_goal)
    if explicit_entry is not None:
        return make_click_decision(
            explicit_entry.get("element_id"),
            f"页面中存在显式入口：{current_goal}，直接点击"
        )

    # 第二优先级：special_hints
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


def get_successful_click_count(history):
    count = 0

    for item in history:
        decision = item.get("decision", {})
        result = item.get("result", {})

        if decision.get("action") == "click_by_id" and result.get("success"):
            count += 1

    return count


def run_task(task, agent):
    app_name = task["app_name"]
    package = task.get("package")
    activity = task.get("activity")
    max_steps = task.get("max_steps", 10)

    print(f"\n========== 开始测试：{app_name} ==========")

    if ATTACH_CURRENT_PAGE:
        print("运行模式：接管当前手机页面")
        driver = create_driver_attach_current()
    else:
        print("运行模式：根据 package/activity 启动 App")
        driver = create_driver(package, activity)

    tools = AppiumTools(driver, app_name)
    logger = TaskLogger(app_name)

    history = []

    try:
        time.sleep(1)

        # 多应用批量测试：
        # 每个 App 测试前先回到桌面，然后直接使用 package 启动 App。
        if LAUNCH_FROM_PACKAGE_AFTER_HOME:
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

        for step_index in range(max_steps):
            current_goal = get_current_goal(task, history)

            print(f"\n---------- Step {step_index} ----------")
            print("当前目标：", current_goal)

            page_info = tools.get_page_info(
                step_name=f"step_{step_index}",
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

            print("LLM 决策：", decision)

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

            # 当前阶段：只要 declared_path 走完，就判定路径真实性验证成功
            declared_path = task.get("declared_path", [])
            stop_when_path_completed = task.get("stop_when_path_completed", True)
            successful_clicks = get_successful_click_count(history)

            if stop_when_path_completed and successful_clicks >= len(declared_path):
                print("声明路径已经走完，判定路径真实性验证成功，停止测试。")
                break

            if action == "toggle_switch" and result.get("success"):
                print("已经执行开关切换，结束核心验证。")
                break

            time.sleep(1)

        log_path = logger.save()
        final_result = summarize_result(task, history)
        final_result["log_path"] = log_path

        print("\n========== 单个 App 测试结束 ==========")
        print("最终结果：", final_result)

        return final_result

    finally:
        # 单个 App 结束后回到桌面，方便下一个 App 从桌面启动
        try:
            print("测试结束，准备回到桌面...")
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

    for task in apps:
        try:
            result = run_task(task, agent)
            final_results.append(result)
        except Exception as e:
            final_results.append({
                "app_name": task.get("app_name"),
                "target_name": task.get("target_name"),
                "error": str(e),
                "score": 0,
                "conclusion": "测试过程中发生异常。"
            })

    save_json(final_results, "results/final_results.json")

    print("\n========== 全部测试完成 ==========")
    print("结果已保存到 results/final_results.json")


if __name__ == "__main__":
    main()
