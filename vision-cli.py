"""直接调用视觉模型识别图片，绕过代理链路，输出结果到 stdout。"""
import sys, base64, json, requests, os, time

# SiliconFlow 视觉 API 直连
VISION_API_URL = "https://api.siliconflow.cn/v1/chat/completions"
VISION_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
TIMEOUT = 180
MAX_RETRIES = 2


CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".vision_key")


def _get_api_key() -> str:
    """获取 API Key：环境变量 > 配置文件 > 交互式输入（自动保存）。"""
    # 1. 环境变量优先
    key = os.environ.get("VISION_API_KEY") or os.environ.get("SILICONFLOW_API_KEY")
    if key:
        return key
    # 2. 配置文件
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            key = f.read().strip()
            if key:
                return key
    # 3. 首次使用，交互输入并保存
    print("首次使用，需要配置 SiliconFlow API Key（免费注册获取）。")
    print("注册地址：https://cloud.siliconflow.cn")
    key = input("请输入你的 SiliconFlow API Key: ").strip()
    if key:
        with open(CONFIG_FILE, "w") as f:
            f.write(key)
        print(f"已保存到 {CONFIG_FILE}，下次无需再输入。")
    return key


VISION_API_KEY = None  # 延迟初始化，首次调用时获取

PROMPT = (
    "请详细描述这张图片的内容，包括但不限于："
    "界面布局、文字信息、颜色、关键元素、可能的应用或游戏名称。"
    "用中文回答，尽可能具体。"
)


def recognize(image_path: str) -> str:
    global VISION_API_KEY
    if VISION_API_KEY is None:
        VISION_API_KEY = _get_api_key()

    if not os.path.exists(image_path):
        return f"[错误] 图片不存在: {image_path}"

    file_size = os.path.getsize(image_path) / 1024 / 1024
    if file_size > 10:
        return f"[错误] 图片过大 ({file_size:.1f}MB)，请压缩到 10MB 以内"

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png",
                ".gif": "gif", ".webp": "webp", ".bmp": "bmp"}
    mime = mime_map.get(ext, "jpeg")

    payload = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/{mime};base64,{img_b64}"
                }}
            ]
        }],
        "max_tokens": 1024,
    }

    last_error = ""
    for attempt in range(1 + MAX_RETRIES):
        try:
            resp = requests.post(
                VISION_API_URL,
                headers={
                    "Authorization": f"Bearer {VISION_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=TIMEOUT,
            )

            if resp.status_code != 200:
                last_error = f"API 返回 {resp.status_code}: {resp.text[:200]}"
                if attempt < MAX_RETRIES:
                    time.sleep(3)
                continue

            data = resp.json()
            if "choices" in data:
                content = data["choices"][0]["message"]["content"]
                # 检测无效回复（模型说看不到图片等）
                if content and len(content) > 30:
                    return content
                last_error = f"模型返回内容过短或为空: {content}"
            else:
                last_error = f"响应格式异常: {json.dumps(data, ensure_ascii=False)[:300]}"

        except requests.exceptions.ReadTimeout:
            last_error = f"请求超时（{TIMEOUT}s），第 {attempt + 1}/{1 + MAX_RETRIES} 次"
        except Exception as e:
            last_error = f"{e}，第 {attempt + 1}/{1 + MAX_RETRIES} 次"

        if attempt < MAX_RETRIES:
            time.sleep(3)

    return f"[错误] {last_error}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python vision.py <图片路径>")
        sys.exit(1)
    print(recognize(sys.argv[1]))
