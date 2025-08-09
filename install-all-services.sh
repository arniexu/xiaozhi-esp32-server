#!/bin/bash

# XiaoZhi ESP32 全套服务安装脚本
# 安装 manager-api, manager-web, xiaozhi-server, mcp-endpoint-server 四个服务

PROJECT_ROOT="/home/xuqianjin/xiaozhi-esp32-server"
BASE_DIR="$PROJECT_ROOT"
SYSTEMD_DIR="/etc/systemd/system"
MCP_ENDPOINT_DIR="$PROJECT_ROOT/main/mcp-endpoint-server"

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
    
    # 检查 mcp-endpoint-server 的 docker-compose 文件
    if [ ! -f "$MCP_ENDPOINT_DIR/docker-compose.yml" ]; then
        missing_files+=("mcp-endpoint-server/docker-compose.yml")
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

    # Docker 服务需要确保docker服务启用
    if ! systemctl is-enabled docker &>/dev/null; then
        print_info "启用 Docker 服务..."
        systemctl enable docker
    fi
    print_success "mcp-endpoint-server (Docker) 依赖准备完成"
}

# 启动数据库服务 (Docker)
start_database_services() {
    print_info "启动数据库服务..."
    
    # 确保 Docker 服务运行
    if ! systemctl is-active --quiet docker; then
        print_info "启动 Docker 服务..."
        systemctl start docker
        sleep 2
    fi
    
    # 启动 MySQL 容器
    print_info "启动 MySQL 数据库容器..."
    if ! docker ps -a --format "{{.Names}}" | grep -q "^xiaozhi-esp32-server-db$"; then
        docker run --name xiaozhi-esp32-server-db \
            -e MYSQL_ROOT_PASSWORD=123456 \
            -p 3306:3306 \
            -e MYSQL_DATABASE=xiaozhi_esp32_server \
            -e MYSQL_INITDB_ARGS="--character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci" \
            -d mysql:latest
        print_success "MySQL 容器创建并启动成功"
    elif ! docker ps --format "{{.Names}}" | grep -q "^xiaozhi-esp32-server-db$"; then
        docker start xiaozhi-esp32-server-db
        print_success "MySQL 容器启动成功"
    else
        print_info "MySQL 容器已在运行"
    fi
    
    # 启动 Redis 容器
    print_info "启动 Redis 缓存容器..."
    if ! docker ps -a --format "{{.Names}}" | grep -q "^xiaozhi-esp32-server-redis$"; then
        docker run --name xiaozhi-esp32-server-redis \
            -d -p 6379:6379 redis
        print_success "Redis 容器创建并启动成功"
    elif ! docker ps --format "{{.Names}}" | grep -q "^xiaozhi-esp32-server-redis$"; then
        docker start xiaozhi-esp32-server-redis
        print_success "Redis 容器启动成功"
    else
        print_info "Redis 容器已在运行"
    fi
    
    # 等待数据库服务准备就绪
    print_info "等待数据库服务准备就绪..."
    sleep 10
}

# 启动服务
start_services() {
    print_info "启动服务..."
    
    # 首先启动数据库服务
    start_database_services
    
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
    
    print_info "启动 mcp-endpoint-server (Docker)..."
    start_mcp_endpoint_service
    sleep 3
    
    print_success "所有服务启动完成"
}

# 停止数据库服务 (Docker)
stop_database_services() {
    print_info "停止数据库服务..."
    
    # 停止 MySQL 容器
    if docker ps --format "{{.Names}}" | grep -q "^xiaozhi-esp32-server-db$"; then
        print_info "停止 MySQL 容器..."
        docker stop xiaozhi-esp32-server-db
        print_success "MySQL 容器已停止"
    fi
    
    # 停止 Redis 容器
    if docker ps --format "{{.Names}}" | grep -q "^xiaozhi-esp32-server-redis$"; then
        print_info "停止 Redis 容器..."
        docker stop xiaozhi-esp32-server-redis
        print_success "Redis 容器已停止"
    fi
}

# 启动 MCP Endpoint 服务 (Docker)
start_mcp_endpoint_service() {
    if [ ! -d "$MCP_ENDPOINT_DIR" ]; then
        print_error "MCP Endpoint 目录不存在: $MCP_ENDPOINT_DIR"
        return 1
    fi
    
    cd "$MCP_ENDPOINT_DIR"
    
    # 确保 Docker 服务运行
    if ! systemctl is-active --quiet docker; then
        print_info "启动 Docker 服务..."
        systemctl start docker
        sleep 2
    fi
    
    # 启动 mcp-endpoint-server
    print_info "使用 docker-compose 启动 mcp-endpoint-server..."
    docker compose -f docker-compose.yml up -d
    
    if [ $? -eq 0 ]; then
        print_success "mcp-endpoint-server 启动成功"
    else
        print_error "mcp-endpoint-server 启动失败"
    fi
    
    cd - > /dev/null
}

# 停止 MCP Endpoint 服务 (Docker)
stop_mcp_endpoint_service() {
    if [ ! -d "$MCP_ENDPOINT_DIR" ]; then
        print_warning "MCP Endpoint 目录不存在: $MCP_ENDPOINT_DIR"
        return 0
    fi
    
    cd "$MCP_ENDPOINT_DIR"
    
    print_info "停止 mcp-endpoint-server..."
    docker compose -f docker-compose.yml down
    
    if [ $? -eq 0 ]; then
        print_success "mcp-endpoint-server 已停止"
    else
        print_warning "mcp-endpoint-server 停止可能未完全成功"
    fi
    
    cd - > /dev/null
}

# 检查服务状态
check_services_status() {
    print_info "检查服务状态..."
    echo
    
    # 检查数据库服务状态
    echo "=========================================="
    echo "数据库服务状态 (Docker)"
    echo "=========================================="
    
    # 检查 MySQL 状态
    if docker ps --format "{{.Names}}" | grep -q "^xiaozhi-esp32-server-db$"; then
        print_success "MySQL 数据库运行正常"
        docker ps --filter "name=xiaozhi-esp32-server-db" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        print_error "MySQL 数据库未运行"
    fi
    
    # 检查 Redis 状态
    if docker ps --format "{{.Names}}" | grep -q "^xiaozhi-esp32-server-redis$"; then
        print_success "Redis 缓存运行正常"
        docker ps --filter "name=xiaozhi-esp32-server-redis" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        print_error "Redis 缓存未运行"
    fi
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
    
    # 检查 mcp-endpoint-server Docker 状态
    echo "=========================================="
    echo "服务: mcp-endpoint-server (Docker)"
    echo "=========================================="
    
    if docker ps --format "table {{.Names}}\t{{.Status}}" | grep -q mcp-endpoint-server; then
        print_success "mcp-endpoint-server 运行正常"
        docker ps --filter "name=mcp-endpoint-server" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        print_error "mcp-endpoint-server 未运行"
    fi
    echo
}

# 显示端口信息
show_ports() {
    print_info "检查端口监听状态..."
    echo
    
    ports=("3306" "6379" "8002" "8001" "8000" "8004")
    descriptions=("MySQL Database" "Redis Cache" "Manager API" "Manager Web" "XiaoZhi Server" "MCP Endpoint")
    
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
    echo "  Manager API:    http://localhost:8002/xiaozhi/doc.html"
    echo "  Manager Web:    http://localhost:8001"
    echo "  XiaoZhi Server: http://localhost:8000"
    echo "  MCP Endpoint:   http://localhost:8004"
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
    
    # 停止并清理 mcp-endpoint-server
    if [ -f "$BASE_DIR/main/xiaozhi-server/mcp-endpoint-server/docker-compose.yml" ]; then
        print_info "卸载 mcp-endpoint-server..."
        cd "$BASE_DIR/main/xiaozhi-server/mcp-endpoint-server"
        docker compose down --volumes --remove-orphans
        print_success "mcp-endpoint-server 已停止并清理"
    fi
    
    # 停止并删除数据库容器
    print_info "清理数据库容器..."
    if docker ps -a --format "{{.Names}}" | grep -q "^xiaozhi-esp32-server-db$"; then
        docker stop xiaozhi-esp32-server-db 2>/dev/null || true
        docker rm xiaozhi-esp32-server-db 2>/dev/null || true
        print_success "MySQL 容器已删除"
    fi
    
    if docker ps -a --format "{{.Names}}" | grep -q "^xiaozhi-esp32-server-redis$"; then
        docker stop xiaozhi-esp32-server-redis 2>/dev/null || true
        docker rm xiaozhi-esp32-server-redis 2>/dev/null || true
        print_success "Redis 容器已删除"
    fi
    
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
            
            # 停止 mcp-endpoint-server
            if [ -f "$BASE_DIR/main/xiaozhi-server/mcp-endpoint-server/docker-compose.yml" ]; then
                cd "$BASE_DIR/main/xiaozhi-server/mcp-endpoint-server"
                docker compose down
            fi
            
            # 停止 systemd 服务
            if sudo systemctl is-active --quiet xiaozhi-server; then
                sudo systemctl stop xiaozhi-server
            fi
            if sudo systemctl is-active --quiet manager-web; then
                sudo systemctl stop manager-web
            fi
            if sudo systemctl is-active --quiet manager-api; then
                sudo systemctl stop manager-api
            fi
            
            # 停止数据库服务
            stop_database_services
            
            print_success "所有服务已停止"
            ;;
            
        restart)
            check_root
            print_info "重启所有服务..."
            
            # 停止所有服务（逆序）
            # 停止 mcp-endpoint-server
            if [ -f "$BASE_DIR/main/xiaozhi-server/mcp-endpoint-server/docker-compose.yml" ]; then
                cd "$BASE_DIR/main/xiaozhi-server/mcp-endpoint-server"
                docker compose down
            fi
            
            if sudo systemctl is-active --quiet xiaozhi-server; then
                sudo systemctl stop xiaozhi-server
            fi
            if sudo systemctl is-active --quiet manager-web; then
                sudo systemctl stop manager-web
            fi
            if sudo systemctl is-active --quiet manager-api; then
                sudo systemctl stop manager-api
            fi
            
            # 停止数据库服务
            stop_database_services
            
            sleep 3
            
            # 启动数据库服务
            start_database_services
            
            # 启动服务（正序）
            if systemctl list-unit-files | grep -q manager-api.service; then
                sudo systemctl start manager-api
                sleep 3
            fi
            if systemctl list-unit-files | grep -q manager-web.service; then
                sudo systemctl start manager-web
                sleep 3
            fi
            if systemctl list-unit-files | grep -q xiaozhi-server.service; then
                sudo systemctl start xiaozhi-server
                sleep 3
            fi
            
            # 启动 mcp-endpoint-server（在 xiaozhi-server 之后）
            if [ -f "$BASE_DIR/main/xiaozhi-server/mcp-endpoint-server/docker-compose.yml" ]; then
                cd "$BASE_DIR/main/xiaozhi-server/mcp-endpoint-server"
                docker compose up -d
            fi
            
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
            echo "  0. MySQL Database   (Docker 容器)"
            echo "  0. Redis Cache      (Docker 容器)"
            echo "  1. manager-api      (Java Spring Boot API)"
            echo "  2. manager-web      (Vue.js前端)"
            echo "  3. xiaozhi-server   (Python后端)"
            echo "  4. mcp-endpoint-server (MCP端点服务 Docker)"
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
