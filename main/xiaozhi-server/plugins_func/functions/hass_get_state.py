from plugins_func.register import register_function, ToolType, ActionResponse, Action
from plugins_func.functions.hass_init import initialize_hass_handler
from config.logger import setup_logging
import asyncio
import requests

TAG = __name__
logger = setup_logging()

hass_get_state_function_desc = {
    "type": "function",
    "function": {
        "name": "hass_get_state",
        "description": "获取homeassistant里设备的状态,包括查询灯光亮度、颜色、色温,媒体播放器的音量,设备的暂停、继续操作",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "需要操作的设备id,homeassistant里的entity_id",
                }
            },
            "required": ["entity_id"],
        },
    },
}


@register_function("hass_get_state", hass_get_state_function_desc, ToolType.SYSTEM_CTL)
def hass_get_state(conn, entity_id=""):
    try:

        future = asyncio.run_coroutine_threadsafe(
            handle_hass_get_state(conn, entity_id), conn.loop
        )
        # 添加10秒超时
        ha_response = future.result(timeout=10)
        return ActionResponse(Action.REQLLM, ha_response, None)
    except asyncio.TimeoutError:
        logger.bind(tag=TAG).error("获取Home Assistant状态超时")
        return ActionResponse(Action.ERROR, "请求超时", None)
    except Exception as e:
        error_msg = f"执行Home Assistant操作失败"
        logger.bind(tag=TAG).error(error_msg)
        return ActionResponse(Action.ERROR, error_msg, None)


async def handle_hass_get_state(conn, entity_id):
    ha_config = initialize_hass_handler(conn)
    api_key = ha_config.get("api_key")
    base_url = ha_config.get("base_url")
    url = f"{base_url}/api/states/{entity_id}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        resp_json = response.json()
        logger.bind(tag=TAG).info(f"api返回内容: {resp_json}")
        responsetext = "设备状态:" + resp_json["state"] + " "

        # 温度设备解析
        if resp_json["attributes"].get("device_class") == "temperature":
            try:
                temperature = float(resp_json["state"])
                unit = resp_json["attributes"].get("unit_of_measurement", "")
                responsetext = f"温度: {temperature}{unit}"
            except Exception:
                responsetext = f"温度解析失败，原始值: {resp_json['state']}"

        if "media_title" in resp_json["attributes"]:
            responsetext += " 正在播放的是:" + str(resp_json["attributes"]["media_title"])
        if "volume_level" in resp_json["attributes"]:
            responsetext += " 音量是:" + str(resp_json["attributes"]["volume_level"])
        if "color_temp_kelvin" in resp_json["attributes"]:
            responsetext += " 色温是:" + str(resp_json["attributes"]["color_temp_kelvin"])
        if "rgb_color" in resp_json["attributes"]:
            responsetext += " rgb颜色是:" + str(resp_json["attributes"]["rgb_color"])
        if "brightness" in resp_json["attributes"]:
            responsetext += " 亮度是:" + str(resp_json["attributes"]["brightness"])

        logger.bind(tag=TAG).info(f"查询返回内容: {responsetext}")
        return responsetext
    else:
        return f"切换失败，错误码: {response.status_code}"
