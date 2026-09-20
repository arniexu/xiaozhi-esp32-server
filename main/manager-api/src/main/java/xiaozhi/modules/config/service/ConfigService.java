package xiaozhi.modules.config.service;

import java.util.Map;

public interface ConfigService {
    /**
     * 获取服务器配置
     * 
     * @param isCache 是否缓存
     * @return 配置信息
     */
    Object getConfig(Boolean isCache);

    /**
     * 获取智能体模型配置
     * 
     * @param macAddress     MAC地址
     * @param selectedModule 客户端已实例化的模型
     * @return 模型配置信息
     */
    /**
     * 获取智能体模型配置
     *
     * @param macAddress     MAC地址
     * @param selectedModule 客户端已实例化的模型
     * @param agentId        可选：设备请求使用的角色 id。为空时用设备绑定的角色；
     *                       非空但校验不通过（不存在 / 不属于该设备所属用户）时
     *                       <b>静默回落到绑定角色</b>，不抛异常（保证设备始终能拿到配置）
     * @return 模型配置信息
     */
    Map<String, Object> getAgentModels(String macAddress, Map<String, String> selectedModule, String agentId);
}