def execute_action(decision, tools):
    """
    根据 LLM 返回的 JSON 决策调用对应工具函数。
    """

    action = decision.get("action")

    if action == "click_by_id":
        element_id = decision.get("element_id")
        if element_id is None:
            return {
                "success": False,
                "message": "click_by_id 缺少 element_id"
            }
        return tools.click_by_id(int(element_id))

    elif action == "toggle_switch":
        switch_id = decision.get("switch_id")
        if switch_id is None:
            return {
                "success": False,
                "message": "toggle_switch 缺少 switch_id"
            }
        return tools.toggle_switch(int(switch_id))

    elif action == "scroll_down":
        return tools.scroll_down()

    elif action == "scroll_up":
        return tools.scroll_up()

    elif action == "back":
        return tools.back()

    elif action == "tap_top_left_back":
        return tools.tap_top_left_back()

    elif action == "stop":
        return {
            "success": decision.get("success"),
            "message": decision.get("reason", "任务结束")
        }

    else:
        return {
            "success": False,
            "message": f"未知动作：{action}"
        }