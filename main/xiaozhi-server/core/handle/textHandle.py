import json
from core.handle.abortHandle import handleAbortMessage
from core.handle.helloHandle import handleHelloMessage
from core.providers.tools.device_mcp import handle_mcp_message
from core.utils.util import remove_punctuation_and_length, filter_sensitive_info
from core.handle.receiveAudioHandle import startToChat, handleAudioMessage
from core.handle.sendAudioHandle import send_stt_message, send_tts_message
from core.providers.tools.device_iot import handleIotDescriptors, handleIotStatus
from core.handle.reportHandle import enqueue_asr_report
from core.handle.faceHandle import add_person, find_person, list_people
import asyncio

TAG = __name__


async def handleTextMessage(conn, message):
    """处理文本消息"""
    conn.logger.bind(tag=TAG).debug(f"开始处理文本消息，消息长度：{len(message)}")
    try:
        conn.logger.bind(tag=TAG).debug(f"尝试解析JSON消息：{message[:200]}...")
        msg_json = json.loads(message)
        conn.logger.bind(tag=TAG).debug(f"JSON解析成功，消息类型：{type(msg_json)}")
        
        if isinstance(msg_json, int):
            conn.logger.bind(tag=TAG).info(f"收到整数类型文本消息：{message}")
            await conn.websocket.send(message)
            conn.logger.bind(tag=TAG).debug(f"已回发整数消息")
            return
        if msg_json["type"] == "hello":
            conn.logger.bind(tag=TAG).info(f"收到hello消息：{message}")
            conn.logger.bind(tag=TAG).debug(f"开始处理hello消息")
            await handleHelloMessage(conn, msg_json)
            conn.logger.bind(tag=TAG).debug(f"hello消息处理完成")
        elif msg_json["type"] == "abort":
            conn.logger.bind(tag=TAG).info(f"收到abort消息：{message}")
            conn.logger.bind(tag=TAG).debug(f"开始处理abort消息")
            await handleAbortMessage(conn)
            conn.logger.bind(tag=TAG).debug(f"abort消息处理完成")
        elif msg_json["type"] == "listen":
            conn.logger.bind(tag=TAG).info(f"收到listen消息：{message}")
            conn.logger.bind(tag=TAG).debug(f"开始处理listen消息，当前状态：{msg_json.get('state', 'unknown')}")
            
            if "mode" in msg_json:
                old_mode = conn.client_listen_mode
                conn.client_listen_mode = msg_json["mode"]
                conn.logger.bind(tag=TAG).debug(
                    f"客户端拾音模式更新：{old_mode} -> {conn.client_listen_mode}"
                )
                
            if msg_json["state"] == "start":
                conn.logger.bind(tag=TAG).debug(f"设置客户端语音状态：have_voice=True, voice_stop=False")
                conn.client_have_voice = True
                conn.client_voice_stop = False
            elif msg_json["state"] == "stop":
                conn.logger.bind(tag=TAG).debug(f"设置客户端语音状态：have_voice=True, voice_stop=True")
                conn.client_have_voice = True
                conn.client_voice_stop = True
                conn.logger.bind(tag=TAG).debug(f"当前ASR音频缓存长度：{len(conn.asr_audio)}")
                if len(conn.asr_audio) > 0:
                    conn.logger.bind(tag=TAG).debug(f"开始处理停止状态下的音频消息")
                    await handleAudioMessage(conn, b"")
                    conn.logger.bind(tag=TAG).debug(f"音频消息处理完成")
            elif msg_json["state"] == "detect":
                conn.logger.bind(tag=TAG).debug(f"进入detect状态，清空ASR音频缓存")
                conn.client_have_voice = False
                conn.asr_audio.clear()
                if "text" in msg_json:
                    original_text = msg_json["text"]  # 保留原始文本
                    conn.logger.bind(tag=TAG).debug(f"检测到文本内容：{original_text}")
                    
                    filtered_len, filtered_text = remove_punctuation_and_length(
                        original_text
                    )
                    conn.logger.bind(tag=TAG).debug(f"文本过滤结果：长度={filtered_len}, 内容='{filtered_text}'")

                    # 识别是否是唤醒词
                    wakeup_words = conn.config.get("wakeup_words", [])
                    is_wakeup_words = filtered_text in wakeup_words
                    conn.logger.bind(tag=TAG).debug(f"唤醒词检测：'{filtered_text}' in {wakeup_words} = {is_wakeup_words}")
                    
                    # 是否开启唤醒词回复
                    enable_greeting = conn.config.get("enable_greeting", True)
                    conn.logger.bind(tag=TAG).debug(f"唤醒词回复开关：{enable_greeting}")

                    if is_wakeup_words and not enable_greeting:
                        # 如果是唤醒词，且关闭了唤醒词回复，就不用回答
                        conn.logger.bind(tag=TAG).info(f"唤醒词'{filtered_text}'被识别，但回复功能已关闭")
                        await send_stt_message(conn, original_text)
                        await send_tts_message(conn, "stop", None)
                        conn.client_is_speaking = False
                        conn.logger.bind(tag=TAG).debug(f"已发送STT消息和停止TTS消息")
                    elif is_wakeup_words:
                        conn.logger.bind(tag=TAG).info(f"识别到唤醒词'{filtered_text}'，开始唤醒流程")
                        conn.just_woken_up = True
                        # 上报纯文字数据（复用ASR上报功能，但不提供音频数据）
                        enqueue_asr_report(conn, "嘿，你好呀", [])
                        conn.logger.bind(tag=TAG).debug(f"已入队ASR报告，开始对话流程")
                        await startToChat(conn, "嘿，你好呀")
                        conn.logger.bind(tag=TAG).debug(f"唤醒对话流程完成")
                    else:
                        conn.logger.bind(tag=TAG).info(f"普通文本消息'{original_text}'，开始LLM对话流程")
                        # 上报纯文字数据（复用ASR上报功能，但不提供音频数据）
                        enqueue_asr_report(conn, original_text, [])
                        conn.logger.bind(tag=TAG).debug(f"已入队ASR报告，开始LLM对话")
                        # 否则需要LLM对文字内容进行答复
                        await startToChat(conn, original_text)
                        conn.logger.bind(tag=TAG).debug(f"LLM对话流程完成")
            else:
                conn.logger.bind(tag=TAG).warning(f"未知的listen状态：{msg_json.get('state', 'unknown')}")
            conn.logger.bind(tag=TAG).debug(f"listen消息处理完成")
        elif msg_json["type"] == "iot":
            conn.logger.bind(tag=TAG).info(f"收到iot消息：{message}")
            conn.logger.bind(tag=TAG).debug(f"开始处理iot消息")
            if "descriptors" in msg_json:
                conn.logger.bind(tag=TAG).debug(f"处理IoT描述符，数量：{len(msg_json['descriptors']) if isinstance(msg_json['descriptors'], list) else 'unknown'}")
                asyncio.create_task(handleIotDescriptors(conn, msg_json["descriptors"]))
            if "states" in msg_json:
                conn.logger.bind(tag=TAG).debug(f"处理IoT状态，数量：{len(msg_json['states']) if isinstance(msg_json['states'], list) else 'unknown'}")
                asyncio.create_task(handleIotStatus(conn, msg_json["states"]))
            conn.logger.bind(tag=TAG).debug(f"iot消息处理完成")
        elif msg_json["type"] == "mcp":
            conn.logger.bind(tag=TAG).info(f"收到mcp消息：{message[:100]}")
            conn.logger.bind(tag=TAG).debug(f"开始处理mcp消息，完整长度：{len(message)}")
            if "payload" in msg_json:
                payload_size = len(str(msg_json["payload"])) if msg_json["payload"] else 0
                conn.logger.bind(tag=TAG).debug(f"MCP payload大小：{payload_size} 字符")
                asyncio.create_task(
                    handle_mcp_message(conn, conn.mcp_client, msg_json["payload"])
                )
                conn.logger.bind(tag=TAG).debug(f"MCP消息处理任务已创建")
            else:
                conn.logger.bind(tag=TAG).warning(f"MCP消息缺少payload字段")
            conn.logger.bind(tag=TAG).debug(f"mcp消息处理完成")
        elif msg_json["type"] == "face":
            # 有三种，添加生人，查找已添加的人的名字，列出所有已添加人的名字
            conn.logger.bind(tag=TAG).info(f"收到人脸消息：{message}")
            conn.logger.bind(tag=TAG).debug(f"开始处理人脸消息")
            if "action" in msg_json:
                action = msg_json["action"]
                conn.logger.bind(tag=TAG).info(f"人脸操作类型：{action}")
                
                if action == "add":
                    # 添加生人，两个参数，name和image
                    conn.logger.bind(tag=TAG).info("开始处理添加人员请求")
                    if "image" not in msg_json or "name" not in msg_json:
                        conn.logger.bind(tag=TAG).error("添加人员失败：缺少必要参数 name 或 image")
                        await conn.websocket.send(
                            json.dumps({"type": "face", "status": "error", "message": "缺少参数"})
                        )
                        return                        
                    name = msg_json["name"]
                    image = msg_json["image"]
                    conn.logger.bind(tag=TAG).info(f"准备添加人员：{name}，图片数据长度：{len(image) if image else 0}")
                    conn.logger.bind(tag=TAG).debug(f"开始调用add_person函数")
                    # 添加生人
                    await add_person(conn, name, image)
                    conn.logger.bind(tag=TAG).info(f"完成添加人员请求：{name}")
                    
                elif action == "find":
                    # 参数是image返回是name
                    conn.logger.bind(tag=TAG).info("开始处理查找人员请求")
                    image = msg_json.get("image", "")
                    if not image:
                        conn.logger.bind(tag=TAG).error("查找人员失败：缺少图片数据")
                        await conn.websocket.send(
                            json.dumps({"type": "face", "status": "error", "message": "缺少图片数据"})
                        )
                        return
                    conn.logger.bind(tag=TAG).info(f"准备查找人员，图片数据长度：{len(image)}")
                    conn.logger.bind(tag=TAG).debug(f"开始调用find_person函数")
                    result = await find_person(conn, image)
                    conn.logger.bind(tag=TAG).info("完成查找人员请求")
                    conn.logger.bind(tag=TAG).debug(f"查找结果：{result}")
                    
                elif action == "list":
                    # 没有参数
                    conn.logger.bind(tag=TAG).info("开始处理列出所有人员请求")
                    conn.logger.bind(tag=TAG).debug(f"开始调用list_people函数")
                    names = await list_people(conn)
                    conn.logger.bind(tag=TAG).info("完成列出所有人员请求")
                    conn.logger.bind(tag=TAG).debug(f"列出人员数量：{len(names) if names else 0}")
                    
                else:
                    conn.logger.bind(tag=TAG).error(f"未知的人脸操作类型：{action}")
                    await conn.websocket.send(
                        json.dumps({"type": "face", "status": "error", "message": f"未知操作类型：{action}"})
                    )
            else:
                conn.logger.bind(tag=TAG).error("人脸消息缺少 action 参数")
                await conn.websocket.send(
                    json.dumps({"type": "face", "status": "error", "message": "缺少操作类型参数"})
                )
            conn.logger.bind(tag=TAG).debug(f"人脸消息处理完成")
        elif msg_json["type"] == "server":
            # 记录日志时过滤敏感信息
            conn.logger.bind(tag=TAG).info(
                f"收到服务器消息：{filter_sensitive_info(msg_json)}"
            )
            conn.logger.bind(tag=TAG).debug(f"开始处理服务器消息")
            
            # 如果配置是从API读取的，则需要验证secret
            if not conn.read_config_from_api:
                conn.logger.bind(tag=TAG).debug("配置非API读取模式，跳过服务器消息处理")
                return
                
            # 获取post请求的secret
            post_secret = msg_json.get("content", {}).get("secret", "")
            secret = conn.config["manager-api"].get("secret", "")
            conn.logger.bind(tag=TAG).debug(f"Secret验证：post_secret长度={len(post_secret)}, config_secret长度={len(secret)}")
            
            # 如果secret不匹配，则返回
            if post_secret != secret:
                conn.logger.bind(tag=TAG).warning("服务器密钥验证失败")
                await conn.websocket.send(
                    json.dumps(
                        {
                            "type": "server",
                            "status": "error",
                            "message": "服务器密钥验证失败",
                        }
                    )
                )
                return
                
            conn.logger.bind(tag=TAG).debug("Secret验证通过")
            action = msg_json.get("action", "unknown")
            conn.logger.bind(tag=TAG).debug(f"服务器操作类型：{action}")
            
            # 动态更新配置
            if action == "update_config":
                conn.logger.bind(tag=TAG).info("开始处理配置更新请求")
                try:
                    # 更新WebSocketServer的配置
                    if not conn.server:
                        conn.logger.bind(tag=TAG).error("无法获取服务器实例")
                        await conn.websocket.send(
                            json.dumps(
                                {
                                    "type": "server",
                                    "status": "error",
                                    "message": "无法获取服务器实例",
                                    "content": {"action": "update_config"},
                                }
                            )
                        )
                        return

                    conn.logger.bind(tag=TAG).debug("开始调用服务器更新配置方法")
                    if not await conn.server.update_config():
                        conn.logger.bind(tag=TAG).error("服务器配置更新失败")
                        await conn.websocket.send(
                            json.dumps(
                                {
                                    "type": "server",
                                    "status": "error",
                                    "message": "更新服务器配置失败",
                                    "content": {"action": "update_config"},
                                }
                            )
                        )
                        return

                    conn.logger.bind(tag=TAG).info("配置更新成功")
                    # 发送成功响应
                    await conn.websocket.send(
                        json.dumps(
                            {
                                "type": "server",
                                "status": "success",
                                "message": "配置更新成功",
                                "content": {"action": "update_config"},
                            }
                        )
                    )
                except Exception as e:
                    conn.logger.bind(tag=TAG).error(f"更新配置失败: {str(e)}")
                    await conn.websocket.send(
                        json.dumps(
                            {
                                "type": "server",
                                "status": "error",
                                "message": f"更新配置失败: {str(e)}",
                                "content": {"action": "update_config"},
                            }
                        )
                    )
            # 重启服务器
            elif action == "restart":
                conn.logger.bind(tag=TAG).info("开始处理服务器重启请求")
                conn.logger.bind(tag=TAG).debug("调用conn.handle_restart方法")
                await conn.handle_restart(msg_json)
                conn.logger.bind(tag=TAG).debug("服务器重启处理完成")
            else:
                conn.logger.bind(tag=TAG).warning(f"未知的服务器操作类型：{action}")
            conn.logger.bind(tag=TAG).debug(f"服务器消息处理完成")
        else:
            conn.logger.bind(tag=TAG).error(f"收到未知类型消息：{message}")
            conn.logger.bind(tag=TAG).debug(f"未知消息类型：{msg_json.get('type', 'missing_type')}")
    except json.JSONDecodeError as e:
        conn.logger.bind(tag=TAG).error(f"JSON解析失败：{str(e)}, 原始消息：{message[:200]}")
        conn.logger.bind(tag=TAG).debug(f"回发原始消息")
        await conn.websocket.send(message)
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"处理文本消息时发生异常：{str(e)}")
        conn.logger.bind(tag=TAG).debug(f"异常详情：{type(e).__name__}: {str(e)}")
        raise  # 重新抛出异常以便上层处理
    
    conn.logger.bind(tag=TAG).debug(f"文本消息处理完成")
