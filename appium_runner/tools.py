import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_bounds(bounds: str):
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
        "center_y": (top + bottom) // 2,
        "width": right - left,
        "height": bottom - top
    }


def is_inside(inner, outer):
    """
    判断 inner 这个矩形是否在 outer 矩形内部。
    用于把 TextView 文本归属到可点击父容器上，生成 nearby_text。
    """
    if inner is None or outer is None:
        return False

    return (
        inner["left"] >= outer["left"]
        and inner["right"] <= outer["right"]
        and inner["top"] >= outer["top"]
        and inner["bottom"] <= outer["bottom"]
    )


class AppiumTools:
    """
    封装 Appium 操作函数。

    重点：
    1. get_page_info() 使用 page_source + XML 解析，避免逐个 get_attribute 导致卡死；
    2. clickable_elements 支持 nearby_text；
    3. click_by_id() 使用 bounds 中心点点击，适合无文字图标和整行 FrameLayout；
    4. 增加 go_home() 和 launch_app_from_desktop()，支持多应用批量测试。
    """

    def __init__(self, driver, app_name: str):
        self.driver = driver
        self.app_name = app_name
        self.current_clickable_elements = []
        self.current_switches = []

    def save_screenshot(self, step_name: str):
        """
        保存当前页面截图。
        当前实验中建议 take_screenshot=False，避免部分手机 Appium 截图超时。
        """
        out_dir = Path("results/screenshots") / self.app_name
        out_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        safe_step_name = str(step_name).replace("/", "_").replace("\\", "_")
        path = out_dir / f"{timestamp}_{safe_step_name}.png"

        self.driver.save_screenshot(str(path))
        return str(path)

    def get_page_info(self, step_name: str = "page", take_screenshot: bool = False):
        """
        快速获取当前页面信息。

        不再使用：
            find_elements(By.XPATH, "//*") + 多次 get_attribute

        改为：
            一次性读取 driver.page_source，然后本地解析 XML。
        """

        print("[get_page_info] 开始获取 page_source ...")
        source = self.driver.page_source
        print("[get_page_info] page_source 获取完成，开始解析 XML ...")

        try:
            root = ET.fromstring(source)
        except Exception as e:
            print("[get_page_info] XML 解析失败：", e)
            return {
                "texts": [],
                "clickable_elements": [],
                "switches": [],
                "screenshot": None,
                "error": f"XML 解析失败：{str(e)}"
            }

        texts = []
        text_nodes = []
        raw_clickable_elements = []
        switches = []

        for node in root.iter():
            text = node.attrib.get("text", "") or ""
            desc = node.attrib.get("content-desc", "") or ""
            class_name = node.attrib.get("class", "") or ""
            clickable = node.attrib.get("clickable", "false") or "false"
            enabled = node.attrib.get("enabled", "false") or "false"
            checked = node.attrib.get("checked", "false") or "false"
            bounds = node.attrib.get("bounds", "") or ""

            if text == "null":
                text = ""
            if desc == "null":
                desc = ""

            visible_name = text if text else desc

            if visible_name:
                texts.append(visible_name)
                text_nodes.append({
                    "text": visible_name,
                    "class": class_name,
                    "bounds": bounds,
                    "pos": parse_bounds(bounds)
                })

            if clickable == "true" and enabled == "true":
                raw_clickable_elements.append({
                    "text": text,
                    "content_desc": desc,
                    "class": class_name,
                    "bounds": bounds,
                    "pos": parse_bounds(bounds)
                })

            if self._is_switch_like(class_name, checked):
                switches.append({
                    "switch_id": len(switches) + 1,
                    "text": text,
                    "content_desc": desc,
                    "class": class_name,
                    "checked": checked,
                    "clickable": clickable,
                    "enabled": enabled,
                    "bounds": bounds
                })

        clickable_elements = []

        for idx, item in enumerate(raw_clickable_elements, start=1):
            outer_pos = item["pos"]

            inner_texts = []
            for tn in text_nodes:
                if is_inside(tn["pos"], outer_pos):
                    inner_texts.append(tn["text"])

            nearby_text = " ".join(dict.fromkeys(inner_texts))
            position_hint = self.get_position_hint(item["bounds"])

            clickable_elements.append({
                "element_id": idx,
                "text": item["text"],
                "content_desc": item["content_desc"],
                "nearby_text": nearby_text,
                "class": item["class"],
                "bounds": item["bounds"],
                "position_hint": position_hint
            })

        self.current_clickable_elements = clickable_elements
        self.current_switches = switches

        screenshot = None
        if take_screenshot:
            try:
                screenshot = self.save_screenshot(step_name)
            except Exception as e:
                screenshot = f"截图失败：{str(e)}"

        print("[get_page_info] 页面解析完成。")

        return {
            "texts": list(dict.fromkeys(texts)),
            "clickable_elements": clickable_elements,
            "switches": switches,
            "screenshot": screenshot
        }

    def get_position_hint(self, bounds: str):
        """
        根据控件坐标给出位置提示。
        主要用于识别没有文字的图标按钮，比如顶部齿轮、三道横线、更多按钮。
        """
        pos = parse_bounds(bounds)
        if pos is None:
            return ""

        try:
            size = self.driver.get_window_size()
            width = size["width"]
            height = size["height"]
        except Exception:
            return ""

        cx = pos["center_x"]
        cy = pos["center_y"]

        if cy < height * 0.15:
            if cx > width * 0.75:
                return "top_right_icon_candidate"
            elif cx < width * 0.25:
                return "top_left_icon_candidate"
            else:
                return "top_bar_icon_candidate"

        if cy > height * 0.85:
            return "bottom_navigation_candidate"

        return ""

    def _is_switch_like(self, class_name: str, checked):
        """
        更严格地判断一个控件是否是开关。
        不要仅凭 checked=false 就认为它是开关。
        """
        switch_keywords = [
            "Switch",
            "CheckBox",
            "CompoundButton",
            "ToggleButton"
        ]

        return any(keyword in class_name for keyword in switch_keywords)

    def click_by_id(self, element_id: int):
        """
        根据 get_page_info 返回的 element_id 点击元素。
        当前版本主要使用 bounds 中心点点击。
        """

        target = None

        for item in self.current_clickable_elements:
            if item["element_id"] == element_id:
                target = item
                break

        if target is None:
            return {
                "success": False,
                "message": f"没有找到 element_id={element_id} 的元素"
            }

        pos = parse_bounds(target.get("bounds", ""))
        if pos is not None:
            x = pos["center_x"]
            y = pos["center_y"]

            self.driver.tap([(x, y)])
            time.sleep(1.2)

            return {
                "success": True,
                "message": f"已通过 bounds 中心点点击元素 {element_id}: ({x}, {y})",
                "clicked": target
            }

        return {
            "success": False,
            "message": f"元素 {element_id} 没有有效 bounds，无法点击",
            "clicked": target
        }

    def click_by_text(self, text: str):
        """
        根据文本点击元素。
        当前阶段主要用于兜底，常规流程建议使用 click_by_id。
        """
        source_info = self.get_page_info(take_screenshot=False)
        clickable_elements = source_info.get("clickable_elements", [])

        for item in clickable_elements:
            name_parts = [
                item.get("text", ""),
                item.get("content_desc", ""),
                item.get("nearby_text", "")
            ]
            name = " ".join([p for p in name_parts if p and p != "null"])

            if text in name:
                return self.click_by_id(item["element_id"])

        return {
            "success": False,
            "message": f"没有找到文本：{text}"
        }

    def back(self):
        """
        系统返回。
        Android keycode 4 = BACK。
        """
        self.driver.press_keycode(4)
        time.sleep(1)
        return {
            "success": True,
            "message": "已执行系统返回"
        }

    def tap_top_left_back(self):
        """
        点击左上角返回按钮位置。
        这是兜底方法，适合某些 App 不响应系统 back 的情况。
        """
        self.driver.tap([(60, 120)])
        time.sleep(1)
        return {
            "success": True,
            "message": "已点击左上角返回坐标"
        }

    def go_home(self):
        """
        回到手机桌面。
        Android keycode 3 = HOME。
        等价于点击底部中间的系统 Home 键，比坐标点击更稳定。
        """
        self.driver.press_keycode(3)
        time.sleep(1.5)
        return {
            "success": True,
            "message": "已回到桌面"
        }

    def tap_bottom_home_button(self):
        """
        点击屏幕底部中间 Home 导航键。
        仅作为兜底方案，不如 press_keycode(3) 稳定。
        """
        size = self.driver.get_window_size()
        width = size["width"]
        height = size["height"]

        x = width // 2
        y = int(height * 0.965)

        self.driver.tap([(x, y)])
        time.sleep(1.5)

        return {
            "success": True,
            "message": f"已点击底部中间 Home 键坐标 ({x}, {y})"
        }

    def launch_app_from_desktop(self, app_display_name: str):
        """
        从桌面点击 App 图标启动应用。

        要求：
        1. 当前已经在桌面；
        2. App 图标在当前桌面页面可见；
        3. App 图标的 text、content-desc 或 nearby_text 能被 Appium 识别。
        """

        page_info = self.get_page_info(
            step_name=f"desktop_find_{app_display_name}",
            take_screenshot=False
        )

        clickable_elements = page_info.get("clickable_elements", [])

        def get_name(item):
            parts = [
                item.get("text") or "",
                item.get("content_desc") or "",
                item.get("nearby_text") or ""
            ]
            return " ".join([p for p in parts if p and p != "null"])

        # 1. 精确匹配优先
        for item in clickable_elements:
            name = get_name(item)
            if name == app_display_name:
                result = self.click_by_id(item["element_id"])
                return {
                    "success": result.get("success", False),
                    "message": f"已从桌面点击 App：{app_display_name}",
                    "clicked": item,
                    "raw_result": result
                }

        # 2. 包含匹配
        for item in clickable_elements:
            name = get_name(item)
            if app_display_name in name:
                result = self.click_by_id(item["element_id"])
                return {
                    "success": result.get("success", False),
                    "message": f"已从桌面点击疑似 App：{app_display_name}",
                    "clicked": item,
                    "raw_result": result
                }

        return {
            "success": False,
            "message": f"桌面当前页面没有找到 App 图标：{app_display_name}"
        }

    def scroll_down(self):
        """
        向下滑动页面。
        """
        size = self.driver.get_window_size()
        width = size["width"]
        height = size["height"]

        start_x = width // 2
        start_y = int(height * 0.75)
        end_y = int(height * 0.25)

        self.driver.swipe(start_x, start_y, start_x, end_y, 600)
        time.sleep(1)

        return {
            "success": True,
            "message": "已向下滑动"
        }

    def scroll_up(self):
        """
        向上滑动页面。
        """
        size = self.driver.get_window_size()
        width = size["width"]
        height = size["height"]

        start_x = width // 2
        start_y = int(height * 0.25)
        end_y = int(height * 0.75)

        self.driver.swipe(start_x, start_y, start_x, end_y, 600)
        time.sleep(1)

        return {
            "success": True,
            "message": "已向上滑动"
        }

    def toggle_switch(self, switch_id: int):
        """
        点击指定编号的开关，并检测 checked 状态是否变化。
        当前阶段主要验证 declared_path 是否走通；这个函数暂时保留。
        """
        target = None

        for item in self.current_switches:
            if item["switch_id"] == switch_id:
                target = item
                break

        if target is None:
            return {
                "success": False,
                "message": f"没有找到 switch_id={switch_id} 的开关"
            }

        before = target.get("checked")

        pos = parse_bounds(target.get("bounds", ""))
        if pos is None:
            return {
                "success": False,
                "message": "开关没有有效 bounds，无法切换",
                "switch": target
            }

        x = pos["center_x"]
        y = pos["center_y"]

        self.driver.tap([(x, y)])
        time.sleep(1.2)

        new_page_info = self.get_page_info(take_screenshot=False)
        after = None

        for sw in new_page_info.get("switches", []):
            sw_pos = parse_bounds(sw.get("bounds", ""))
            if sw_pos is None:
                continue

            if abs(sw_pos["center_x"] - x) < 30 and abs(sw_pos["center_y"] - y) < 30:
                after = sw.get("checked")
                break

        return {
            "success": True,
            "message": "已尝试切换开关",
            "before": before,
            "after": after,
            "changed": before != after if after is not None else None,
            "switch": target
        }
