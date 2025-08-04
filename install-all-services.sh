#!/bin/bash

# XiaoZhi ESP32 全套服务安装脚本
# 安装 manager-api, manager-web, xiaozhi-server 三个服务

PROJECT_ROOT="/home/xuqianjin/xiaozhi-esp32-server"
SYSTEMD_DIR="/etc/systemd/system"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印函数
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查是否以root权限运行
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "此脚本需要root权限，请使用 sudo 运行"
        exit 1
    fi
}

# 检查服务文件是否存在
check_service_files() {
    local missing_files=()
    
    if [ ! -f "$PROJECT_ROOT/manager-api.service" ]; then
        missing_files+=("manager-api.service")
    fi
    
    if [ ! -f "$PROJECT_ROOT/manager-web.service" ]; then
        missing_files+=("manager-web.service")
    fi
    
    if [ ! -f "$PROJECT_ROOT/main/xixaozhi-server.service" ]; then
        missing_files+=("xixaozhi-server.service")
    fi
    
    if [ ${#missing_files[@]} -gt 0 ]; then
        print_error "以下服务文件缺失:"
        for file in "${missing_files[@]}"; do
            echo "  - $file"
        done
        exit 1
    fi
    
    print_success "所有服务文件检查完成"
}

# 安装服务文件
install_services() {
    print_info "开始安装服务文件..."
    
    # 安装 manager-api.service
    print_info "安装 manager-api.service..."
    cp "$PROJECT_ROOT/manager-api.service" "$SYSTEMD_DIR/"
    
    # 安装 manager-web.service
    print_info "安装 manager-web.service..."
    cp "$PROJECT_ROOT/manager-web.service" "$SYSTEMD_DIR/"
    
    # 安装 xiaozhi-server.service (重命名)
    print_info "安装 xiaozhi-server.service..."
    cp "$PROJECT_ROOT/main/xixaozhi-server.service" "$SYSTEMD_DIR/xiaozhi-server.service"
    
    print_success "服务文件安装完成"
}

# 重新加载systemd并启用服务
enable_services() {
    print_info "重新加载 systemd 配置..."
    systemctl daemon-reload
    
    print_info "启用服务开机自启..."
    
    # 按依赖顺序启用服务
    systemctl enable manager-api
    print_success "manager-api 服务已启用"
    
    systemctl enable manager-web
    print_success "manager-web 服务已启用"
    
    systemctl enable xiaozhi-server
    print_success "xiaozhi-server 服务已启用"
}

# 启动服务
start_services() {
    print_info "启动服务..."
    
    # 按依赖顺序启动服务
    print_info "启动 manager-api..."
    systemctl start manager-api
    sleep 3
    
    print_info "启动 manager-web..."
    systemctl start manager-web
    sleep 3
    
    print_info "启动 xiaozhi-server..."
    systemctl start xiaozhi-server
    sleep 3
    
    print_success "所有服务启动完成"
}

# 检查服务状态
check_services_status() {
    print_info "检查服务状态..."
    echo
    
    services=("manager-api" "manager-web" "xiaozhi-server")
    
    for service in "${services[@]}"; do
        echo "=========================================="
        echo "服务: $service"
        echo "=========================================="
        
        if systemctl is-active --quiet "$service"; then
            print_success "$service 运行正常"
        else
            print_error "$service 未运行"
        fi
        
        if systemctl is-enabled --quiet "$service"; then
            print_info "$service 已设置开机自启"
        else
            print_warning "$service 未设置开机自启"
        fi
        
        echo
        systemctl status "$service" --no-pager -l
        echo
    done
}

# 显示端口信息
show_ports() {
    print_info "检查端口监听状态..."
    echo
    
    ports=("8002" "8001" "8000")
    descriptions=("Manager API" "Manager Web" "XiaoZhi Server")
    
    for i in "${!ports[@]}"; do
        port="${ports[$i]}"
        desc="${descriptions[$i]}"
        
        if command -v ss >/dev/null 2>&1; then
            if ss -tlnp | grep ":$port" >/dev/null; then
                print_success "$desc (端口 $port): 正在监听"
            else
                print_warning "$desc (端口 $port): 未监听"
            fi
        elif command -v netstat >/dev/null 2>&1; then
            if netstat -tlnp | grep ":$port" >/dev/null; then
                print_success "$desc (端口 $port): 正在监听"
            else
                print_warning "$desc (端口 $port): 未监听"
            fi
        fi
    done
}

# 显示访问信息
show_access_info() {
    echo
    print_info "服务访问信息:"
    echo "  Manager API:  http://localhost:8002/xiaozhi/doc.html"
    echo "  Manager Web:  http://localhost:8001"
    echo "  XiaoZhi Server: http://localhost:8000"
    echo
}

# 卸载所有服务
uninstall_services() {
    print_info "开始卸载所有服务..."
    
    services=("xiaozhi-server" "manager-web" "manager-api")
    
    for service in "${services[@]}"; do
        print_info "卸载 $service..."
        
        # 停止服务
        if systemctl is-active --quiet "$service"; then
            systemctl stop "$service"
            print_success "$service 已停止"
        fi
        
        # 禁用服务
        if systemctl is-enabled --quiet "$service"; then
            systemctl disable "$service"
            print_success "$service 开机自启已禁用"
        fi
        
        # 删除服务文件
        if [ -f "$SYSTEMD_DIR/$service.service" ]; then
            rm -f "$SYSTEMD_DIR/$service.service"
            print_success "$service.service 文件已删除"
        fi
    done
    
    # 重新加载systemd
    systemctl daemon-reload
    print_success "systemd 配置已重新加载"
    
    print_success "所有服务卸载完成!"
}

# 主函数
main() {
    case "$1" in
        install)
            check_root
            echo "========================================"
            echo "XiaoZhi ESP32 全套服务安装"
            echo "========================================"
            
            check_service_files
            install_services
            enable_services
            
            print_success "所有服务安装完成!"
            print_info "使用 '$0 start' 启动所有服务"
            print_info "使用 '$0 status' 查看服务状态"
            ;;
            
        start)
            check_root
            start_services
            check_services_status
            show_ports
            show_access_info
            ;;
            
        stop)
            check_root
            print_info "停止所有服务..."
            systemctl stop xiaozhi-server
            systemctl stop manager-web
            systemctl stop manager-api
            print_success "所有服务已停止"
            ;;
            
        restart)
            check_root
            print_info "重启所有服务..."
            systemctl restart manager-api
            sleep 3
            systemctl restart manager-web
            sleep 3
            systemctl restart xiaozhi-server
            print_success "所有服务已重启"
            check_services_status
            ;;
            
        status)
            check_services_status
            show_ports
            show_access_info
            ;;
            
        uninstall)
            check_root
            uninstall_services
            ;;
            
        logs)
            service_name="${2:-manager-api}"
            print_info "显示 $service_name 服务日志 (按 Ctrl+C 退出):"
            journalctl -u "$service_name" -f --no-pager
            ;;
            
        *)
            echo "XiaoZhi ESP32 全套服务管理脚本"
            echo ""
            echo "使用方法: $0 [命令] [参数]"
            echo ""
            echo "可用命令:"
            echo "  install    - 安装所有服务"
            echo "  start      - 启动所有服务"
            echo "  stop       - 停止所有服务"
            echo "  restart    - 重启所有服务"
            echo "  status     - 查看所有服务状态"
            echo "  uninstall  - 卸载所有服务"
            echo "  logs       - 查看服务日志 [服务名]"
            echo ""
            echo "服务启动顺序:"
            echo "  1. manager-api   (Java Spring Boot)"
            echo "  2. manager-web   (Vue.js前端)"
            echo "  3. xiaozhi-server (Python后端)"
            echo ""
            echo "示例:"
            echo "  $0 install           # 安装所有服务"
            echo "  $0 start             # 启动所有服务"
            echo "  $0 status            # 查看状态"
            echo "  $0 logs manager-api  # 查看API日志"
            echo ""
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"
